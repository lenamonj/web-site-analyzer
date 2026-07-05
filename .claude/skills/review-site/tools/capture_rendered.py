#!/usr/bin/env python3
"""
Automated rendered-evidence capture (PLAN.md section 34).

Drives a locally installed headless Chrome or Edge over the Chrome DevTools
Protocol using only the standard library (a minimal RFC 6455 WebSocket
client on raw sockets) and writes the exact rendered-evidence handoff files
from PLAN.md sections 26 and 27: DOM snapshots plus manifest.json for
client-rendered pages, and metrics.json (LCP, CLS, TBT, WCAG contrast) for
every captured page. The measurement JavaScript is embedded verbatim from
tools/CAPTURE.md so the manual and automated paths measure identically.

This is a capture utility like crawler.py, not a registered scanner: the
scanners still never launch a browser and only consume the handoff files.
When no browser is installed the tool says so and the static inconclusive
verdicts stand. Unlike the manual pass, cookie/region overlays are NOT
dismissed; captured_with records that.

Usage:
    python capture_rendered.py [url] [--pages N] [--browser PATH]
    # reads planning/_evidence/<slug>_scan.json to plan the page set,
    # so run a scan first. run_review.py invokes this automatically.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib import error as urlerror
from urllib import request as urlrequest

import common

VIEWPORT = "1440px"
WINDOW_SIZE = "1440,900"
CAPTURED_WITH = "capture_rendered.py (headless Chrome DevTools; overlays not dismissed)"
DEFAULT_PAGE_CAP = 15
LAUNCH_WAIT_S = 15
LOAD_WAIT_S = 25
EVAL_TIMEOUT_S = 20
SETTLE_MS = 1500
PAGE_DELAY_S = 1.0
MAX_SNAPSHOT_CHARS = 5_000_000
MAX_WS_MESSAGE = 32 * 1024 * 1024
MAX_DEVTOOLS_BYTES = 2 * 1024 * 1024  # cap the DevTools HTTP JSON read so no
#                                       remote-JSON read in the project is unbounded
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# The measurement snippets, verbatim from tools/CAPTURE.md (sections 26/27).
VITALS_JS = r"""
(async () => {
  const byType = t => new Promise(res => {
    const es = [];
    const o = new PerformanceObserver(l => es.push(...l.getEntries()));
    try { o.observe({type: t, buffered: true}); } catch (e) {}
    setTimeout(() => { o.disconnect(); res(es); }, 400);
  });
  const lcp = (await byType('largest-contentful-paint')).pop();
  const shifts = await byType('layout-shift');
  const longtasks = await byType('longtask');
  const cls = shifts.filter(s => !s.hadRecentInput).reduce((a, s) => a + s.value, 0);
  const tbt = longtasks.reduce((a, t) => a + Math.max(0, t.duration - 50), 0);
  return {
    lcp_ms: lcp ? Math.round(lcp.startTime) : null,
    cls: Math.round(cls * 1000) / 1000,
    tbt_ms: Math.round(tbt)
  };
})()
"""

CONTRAST_JS = r"""
(() => {
  const lum = c => {
    const [r, g, b] = c.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number)
      .map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const bgOf = el => {
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      // A background image or gradient is painted above any background-color and
      // has no single color to measure, so the effective background is unknown.
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      const bg = cs.backgroundColor;
      if (bg && !bg.includes('rgba(0, 0, 0, 0)')) return bg;
    }
    return 'rgb(255, 255, 255)';
  };
  const out = {checked: 0, inconclusive: 0, violations: []};
  for (const el of document.querySelectorAll('body *')) {
    if (!el.innerText || !el.innerText.trim() || el.children.length) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const bg = bgOf(el);
    if (bg === null) { out.inconclusive++; continue; }  // over an image: not measurable, do not fabricate
    out.checked++;
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const required = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    const l1 = lum(cs.color), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    if (ratio < required) out.violations.push({
      sample: el.innerText.trim().slice(0, 40),
      ratio: Math.round(ratio * 100) / 100,
      required
    });
    if (out.violations.length >= 25) break;
  }
  return out;
})()
"""


class CaptureError(Exception):
    """A page-level or protocol-level capture failure. Always carries the reason."""


# ---------------------------------------------------------------------------
# RFC 6455 WebSocket primitives (pure functions so the tests can drive them
# without a socket).

def ws_accept_key(key):
    """The Sec-WebSocket-Accept value the server must return for our key."""
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def ws_encode_frame(opcode, payload):
    """One masked client-to-server frame (FIN set; the client never fragments)."""
    mask = os.urandom(4)
    length = len(payload)
    head = bytearray([0x80 | opcode])
    if length < 126:
        head.append(0x80 | length)
    elif length < 65536:
        head.append(0x80 | 126)
        head += struct.pack(">H", length)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", length)
    head += mask
    return bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def ws_read_frame(read_exact):
    """Read one frame via read_exact(n) -> bytes. Returns (fin, opcode, payload).
    Unmasks if the frame is masked (servers do not mask, but be correct)."""
    b1, b2 = read_exact(2)
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        (length,) = struct.unpack(">H", read_exact(2))
    elif length == 127:
        (length,) = struct.unpack(">Q", read_exact(8))
    if length > MAX_WS_MESSAGE:
        raise CaptureError(f"WebSocket frame too large ({length} bytes)")
    mask = read_exact(4) if masked else None
    payload = read_exact(length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload


class WsConn:
    """A WebSocket connection over an established, upgraded socket."""

    def __init__(self, sock):
        self.sock = sock

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise CaptureError("WebSocket closed by browser")
            buf += chunk
        return buf

    def send_text(self, text):
        self.sock.sendall(ws_encode_frame(0x1, text.encode("utf-8")))

    def read_message(self, timeout):
        """The next complete text message, assembling fragments and answering
        pings. Raises CaptureError on close or timeout."""
        deadline = time.monotonic() + timeout
        parts = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CaptureError(f"no DevTools message within {timeout}s")
            self.sock.settimeout(remaining)
            try:
                fin, opcode, payload = ws_read_frame(self._read_exact)
            except socket.timeout:
                raise CaptureError(f"no DevTools message within {timeout}s")
            if opcode == 0x9:  # ping -> pong, keep waiting
                self.sock.sendall(ws_encode_frame(0xA, payload))
                continue
            if opcode == 0x8:
                raise CaptureError("WebSocket closed by browser")
            if opcode in (0x1, 0x0):
                parts.append(payload)
                if sum(len(p) for p in parts) > MAX_WS_MESSAGE:
                    raise CaptureError("DevTools message too large")
                if fin:
                    return b"".join(parts).decode("utf-8", errors="replace")
            # other opcodes (binary, pong): ignore and keep reading

    def close(self):
        try:
            self.sock.sendall(ws_encode_frame(0x8, b""))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def ws_connect(ws_url, timeout=10):
    """Open and upgrade a WebSocket to a ws:// URL (DevTools is always local)."""
    parsed = urlparse(ws_url)
    host, port = parsed.hostname, parsed.port or 80
    path = parsed.path or "/"
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (f"GET {path} HTTP/1.1\r\n"
               f"Host: {host}:{port}\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise CaptureError("DevTools refused the WebSocket upgrade")
        response += chunk
        if len(response) > 65536:
            raise CaptureError("oversized WebSocket upgrade response")
    head = response.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    status = head.splitlines()[0]
    if " 101 " not in status + " ":
        raise CaptureError(f"WebSocket upgrade rejected: {status}")
    accept = None
    for line in head.splitlines()[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "sec-websocket-accept":
            accept = value.strip()
    if accept != ws_accept_key(key):
        raise CaptureError("WebSocket accept key mismatch")
    return WsConn(sock)


# ---------------------------------------------------------------------------
# Chrome DevTools Protocol session.

class CdpSession:
    """Command/response over one DevTools page WebSocket, buffering events."""

    def __init__(self, conn):
        self.conn = conn
        self._next_id = 0
        self._events = []

    def cmd(self, method, params=None, timeout=EVAL_TIMEOUT_S):
        self._next_id += 1
        msg_id = self._next_id
        self.conn.send_text(json.dumps(
            {"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CaptureError(f"{method}: no response within {timeout}s")
            msg = json.loads(self.conn.read_message(remaining))
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise CaptureError(f"{method}: {msg['error'].get('message', msg['error'])}")
                return msg.get("result", {})
            if "method" in msg:
                self._events.append(msg)

    def drop_events(self, method):
        self._events = [e for e in self._events if e.get("method") != method]

    def wait_event(self, method, timeout):
        """The next event of that method, or None on timeout (not an error:
        some pages never fire load and capture proceeds best-effort)."""
        for i, e in enumerate(self._events):
            if e.get("method") == method:
                return self._events.pop(i)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                msg = json.loads(self.conn.read_message(remaining))
            except CaptureError:
                return None
            if msg.get("method") == method:
                return msg
            if "method" in msg:
                self._events.append(msg)

    def evaluate(self, expression, await_promise=False, timeout=EVAL_TIMEOUT_S):
        result = self.cmd("Runtime.evaluate",
                          {"expression": expression, "returnByValue": True,
                           "awaitPromise": await_promise}, timeout)
        exc = result.get("exceptionDetails")
        if exc:
            detail = (exc.get("exception") or {}).get("description") or exc.get("text", "")
            raise CaptureError(f"page JavaScript failed: {detail[:200]}")
        return (result.get("result") or {}).get("value")


def _devtools_json(port, path, method="PUT"):
    """A DevTools HTTP endpoint response as parsed JSON. /json/new requires
    PUT on current Chrome; older builds only accept GET, so fall back."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urlrequest.urlopen(urlrequest.Request(url, method=method), timeout=10) as resp:
            return json.loads(resp.read(MAX_DEVTOOLS_BYTES).decode("utf-8"))
    except urlerror.HTTPError as e:
        if method == "PUT":
            return _devtools_json(port, path, method="GET")
        raise CaptureError(f"DevTools endpoint {path}: HTTP {e.code}")
    except OSError as e:
        raise CaptureError(f"DevTools endpoint {path}: {e}")


class ChromeSession:
    """Launch a throwaway headless browser profile and drive one tab."""

    def __init__(self, browser_path):
        self.browser_path = browser_path
        self.profile_dir = tempfile.mkdtemp(prefix="review-capture-")
        self.proc = None
        self.cdp = None
        try:
            port = self._launch()
            tab = _devtools_json(port, "/json/new?about:blank")
            ws_url = tab.get("webSocketDebuggerUrl")
            if not ws_url:
                raise CaptureError("DevTools /json/new returned no webSocketDebuggerUrl")
            self.cdp = CdpSession(ws_connect(ws_url))
            self.cdp.cmd("Page.enable")
        except Exception:
            self.close()
            raise

    def _launch(self):
        """Start the browser with port 0 and read the real port from the
        DevToolsActivePort file (no port race). Retries once with the legacy
        --headless flag for older builds."""
        for headless_flag in ("--headless=new", "--headless"):
            args = [self.browser_path, headless_flag,
                    "--remote-debugging-port=0",
                    f"--user-data-dir={self.profile_dir}",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-gpu", "--disable-extensions", "--mute-audio",
                    "--hide-scrollbars", f"--window-size={WINDOW_SIZE}",
                    "about:blank"]
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            port_file = Path(self.profile_dir) / "DevToolsActivePort"
            deadline = time.monotonic() + LAUNCH_WAIT_S
            while time.monotonic() < deadline:
                if port_file.is_file():
                    try:
                        return int(port_file.read_text(encoding="utf-8").splitlines()[0])
                    except (ValueError, IndexError, OSError):
                        pass  # file still being written; keep polling
                if self.proc.poll() is not None:
                    break  # browser exited; try the next flag
                time.sleep(0.1)
            self._stop_proc()
        raise CaptureError(f"browser at {self.browser_path} did not expose DevTools "
                           f"within {LAUNCH_WAIT_S}s")

    def goto(self, url, wait_s=LOAD_WAIT_S):
        """Navigate and wait for the load event. Returns whether it fired."""
        self.cdp.drop_events("Page.loadEventFired")
        result = self.cdp.cmd("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise CaptureError(f"navigation failed: {result['errorText']}")
        loaded = self.cdp.wait_event("Page.loadEventFired", wait_s) is not None
        time.sleep(SETTLE_MS / 1000)  # SPA hydration settle
        return loaded

    def evaluate(self, expression, await_promise=False):
        return self.cdp.evaluate(expression, await_promise=await_promise)

    def _stop_proc(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def close(self):
        if self.cdp:
            try:
                self.cdp.cmd("Browser.close", timeout=3)
            except CaptureError:
                pass
            self.cdp.conn.close()
            self.cdp = None
        self._stop_proc()
        time.sleep(0.2)  # let Windows release profile file locks
        shutil.rmtree(self.profile_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Browser discovery, capture planning, and the capture run itself.

def find_browser():
    """A local Chrome or Edge binary, or None. REVIEW_BROWSER (env or .env)
    overrides discovery."""
    override = common.env_value("REVIEW_BROWSER")
    if override:
        return override if Path(override).is_file() else None
    candidates = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def snapshot_filename(url, taken):
    """A safe, unique .html filename for a page snapshot. Mutates taken."""
    path = urlparse(url).path.strip("/")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", path).strip("-")[:80] or "home"
    base, i = name, 1
    while f"{name}.html" in taken:
        i += 1
        name = f"{base}-{i}"
    taken.add(f"{name}.html")
    return f"{name}.html"


def plan_from_scan(scan, cap=DEFAULT_PAGE_CAP):
    """The capture page set from a scan result: DOM snapshots for every
    client-rendered page (refreshed each run: the page is loaded for metrics
    anyway, so a fresh snapshot is free and never goes stale), metrics for
    every scanned page with the target first. The cap bounds filler pages
    only; the target and DOM pages always capture. Dropped pages are named,
    never silent."""
    pages_scanned = [common.normalize_url(u) for u in scan.get("pages_scanned") or []]
    dom_pages = [ps["url"] for ps in scan.get("page_scans") or []
                 if ps.get("likely_client_rendered")]
    ordered, seen = [], set()
    for url in pages_scanned[:1] + dom_pages + pages_scanned[1:]:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    mandatory = set(pages_scanned[:1]) | set(dom_pages)
    pages, dropped = [], []
    for url in ordered:
        if url in mandatory or len(pages) < cap:
            pages.append(url)
        else:
            dropped.append(url)
    return {"pages": pages, "dom_pages": dom_pages, "dropped": dropped}


def _load_or_new(path):
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("pages"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass  # unreadable handoff file: rebuild it rather than crash the run
    return {"captured_with": CAPTURED_WITH, "viewport": VIEWPORT, "pages": {}}


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def capture_pages(slug, plan, session_factory=None, browser=None, out_dir=None,
                  delay_s=PAGE_DELAY_S):
    """Capture the planned pages and write the section 26/27 handoff files,
    merging over any existing (for example hand-captured) manifest/metrics.
    Never raises for page-level trouble: failures are named in the summary."""
    pages = plan.get("pages") or []
    summary = {"ok": True, "captured": [], "failed": {},
               "dropped": plan.get("dropped") or []}
    if not pages:
        summary["note"] = "nothing to capture"
        return summary
    if session_factory is None:
        browser = browser or find_browser()
        if not browser:
            return {"ok": False, "captured": [], "failed": {},
                    "dropped": plan.get("dropped") or [],
                    "note": "no Chrome or Edge found (set REVIEW_BROWSER to override); "
                            "rendered evidence not captured"}
        summary["browser"] = browser
        session_factory = lambda: ChromeSession(browser)

    base = Path(out_dir) if out_dir else common.evidence_dir() / "rendered" / slug
    base.mkdir(parents=True, exist_ok=True)
    manifest = _load_or_new(base / "manifest.json")
    metrics = _load_or_new(base / "metrics.json")
    dom_pages = set(plan.get("dom_pages") or [])
    taken = {entry.get("file") for entry in manifest["pages"].values() if entry.get("file")}

    try:
        session = session_factory()
    except (CaptureError, OSError) as e:
        return {"ok": False, "captured": [], "failed": {},
                "dropped": plan.get("dropped") or [],
                "note": f"browser launch failed: {e}"}
    consecutive_failures = 0
    try:
        for i, url in enumerate(pages):
            if i:
                time.sleep(delay_s)
            problems = []
            try:
                loaded = session.goto(url)
                captured_at = _utc_now()
                if url in dom_pages:
                    html = session.evaluate("document.documentElement.outerHTML")
                    if isinstance(html, str) and html.strip():
                        # Reuse this URL's existing snapshot slot on a refresh; only a
                        # URL new to the manifest allocates a name. Otherwise taken
                        # (seeded from the manifest, which already holds this URL's own
                        # file) would push it to a new name each run, oscillating the
                        # filename and orphaning the prior snapshot on disk.
                        filename = (manifest["pages"].get(url, {}).get("file")
                                    or snapshot_filename(url, taken))
                        (base / filename).write_text(html[:MAX_SNAPSHOT_CHARS],
                                                     encoding="utf-8")
                        manifest["pages"][url] = {"file": filename,
                                                  "captured_at_utc": captured_at,
                                                  "load_event": loaded}
                    else:
                        problems.append("snapshot: page returned an empty document")
                vitals = {}
                try:
                    vitals = session.evaluate(VITALS_JS, await_promise=True) or {}
                except CaptureError as e:
                    problems.append(f"vitals: {e}")
                contrast = None
                try:
                    contrast = session.evaluate(CONTRAST_JS)
                except CaptureError as e:
                    problems.append(f"contrast: {e}")
                metrics["pages"][url] = {
                    "lcp_ms": vitals.get("lcp_ms"), "cls": vitals.get("cls"),
                    "tbt_ms": vitals.get("tbt_ms"), "contrast": contrast,
                    "captured_at_utc": captured_at,
                }
                summary["captured"].append(url)
                consecutive_failures = 0
                if problems:
                    summary["failed"][url] = problems
            except (CaptureError, OSError) as e:
                problems.append(f"page: {e}")
                summary["failed"][url] = problems
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    summary["ok"] = False
                    summary["note"] = ("3 consecutive page failures; "
                                       "aborting the capture run")
                    break
                # A dead browser kills every later page: restart the session once
                # per failure so one bad page cannot end the run.
                try:
                    session.close()
                    session = session_factory()
                except (CaptureError, OSError) as restart_err:
                    summary["ok"] = False
                    summary["note"] = f"browser restart failed: {restart_err}"
                    break
    finally:
        try:
            session.close()
        except (CaptureError, OSError):
            pass

    if manifest["pages"]:
        common.write_json(base / "manifest.json", manifest)
        summary["manifest_path"] = str(base / "manifest.json")
    if metrics["pages"]:
        common.write_json(base / "metrics.json", metrics)
        summary["metrics_path"] = str(base / "metrics.json")
    return summary


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    cap = DEFAULT_PAGE_CAP
    browser = None
    if "--pages" in args:
        idx = args.index("--pages")
        try:
            cap = int(args[idx + 1])
            del args[idx:idx + 2]
        except (IndexError, ValueError):
            print("Usage: python capture_rendered.py [url] [--pages N] [--browser PATH]")
            sys.exit(1)
    if "--browser" in args:
        idx = args.index("--browser")
        try:
            browser = args[idx + 1]
            del args[idx:idx + 2]
        except IndexError:
            print("Usage: python capture_rendered.py [url] [--pages N] [--browser PATH]")
            sys.exit(1)
    target = args[0] if args else common.read_target_file()
    if not target:
        print("No target given and no http line found in TARGET.txt")
        sys.exit(1)
    slug = common.slug_of(target)
    scan_path = common.evidence_dir() / f"{slug}_scan.json"
    if not scan_path.is_file():
        print(f"No scan found at {scan_path}; run scan_site.py or run_review.py first.")
        sys.exit(1)
    try:
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {scan_path}: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Could not read {scan_path}: {e}")
        sys.exit(1)
    if not isinstance(scan, dict):
        print(f"Scan JSON must be a JSON object, got {type(scan).__name__}: {scan_path}")
        sys.exit(1)

    plan = plan_from_scan(scan, cap=cap)
    print(f"Capture plan: {len(plan['pages'])} page(s), "
          f"{len(plan['dom_pages'])} needing DOM snapshots")
    for url in plan["dropped"]:
        print(f"  dropped (over --pages cap): {url}")
    summary = capture_pages(slug, plan, browser=browser)
    if summary.get("note"):
        print(summary["note"])
    if summary.get("browser"):
        print(f"Browser: {summary['browser']}")
    for url in summary["captured"]:
        print(f"  captured: {url}")
    for url, problems in summary["failed"].items():
        print(f"  FAILED {url}: {'; '.join(problems)}")
    if summary.get("manifest_path"):
        print(f"Wrote {summary['manifest_path']}")
    if summary.get("metrics_path"):
        print(f"Wrote {summary['metrics_path']}")
    if summary["captured"]:
        print("Re-run scan_site.py (or run_review.py) so the scanners consume "
              "the captured evidence.")
    sys.exit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
