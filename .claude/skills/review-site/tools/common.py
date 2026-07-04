#!/usr/bin/env python3
"""
Shared helpers for the passive website evaluation tools.

Pure standard library so the scanners install nothing beyond Python itself.
Everything here is passive: plain GET/HEAD requests, a TLS handshake, and
DNS-over-HTTPS lookups. No logins, no form posts, no path brute forcing.
"""

import gzip
import json
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from urllib.parse import urlparse, urljoin

# A truthful, identifiable user agent. Do not impersonate a real browser.
USER_AGENT = "website-review-bot/1.0 (+passive-audit; contact via site owner)"
DEFAULT_TIMEOUT = 15
MAX_BODY_BYTES = 3_000_000  # cap downloads so a huge page cannot stall a run


# One attribute-region pattern for every regex-based scanner: sequences of
# plain chars or COMPLETE quoted strings. A bare [^>]* would truncate at a '>'
# inside a quoted value (data-action="a->b", alt="x > y") and hide the
# attributes after it from the check.
_TAG_ATTRS = r"""((?:[^>"']|"[^"]*"|'[^']*')*)"""


def tag_attrs_re(tag):
    """Compiled regex capturing one tag's full attribute string, tolerating
    '>' inside quoted attribute values."""
    return re.compile(r"<%s\b%s>" % (tag, _TAG_ATTRS), re.I)


def normalize_url(url):
    """Add a scheme if the target was given bare (example.com -> https://example.com)."""
    url = url.strip()
    if not url:
        return url
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def host_of(url):
    return urlparse(normalize_url(url)).hostname or ""


def slug_of(url):
    """Match the slug rule in CLAUDE.md: drop scheme and leading www., dots to hyphens."""
    host = host_of(url)
    if host.startswith("www."):
        host = host[4:]
    return host.replace(".", "-")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable urllib's automatic redirect following so we can record each hop."""

    def redirect_request(self, *args, **kwargs):
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect)


def _headers_to_dict(msg):
    """Fold an HTTPMessage into a JSON-friendly dict. Repeated keys become lists."""
    out = {}
    for key, value in msg.items():
        lk = key.lower()
        if lk in out:
            if isinstance(out[lk], list):
                out[lk].append(value)
            else:
                out[lk] = [out[lk], value]
        else:
            out[lk] = value
    return out


def header_value(headers, name, default=None):
    """Return a single header value from a folded header dict.

    _headers_to_dict folds a header sent more than once (origin plus CDN is the
    common case) into a list. Return the last value in that case; identical
    duplicates, which is what the overwhelming majority of real double-sends
    are, collapse to the same string regardless. Absent header -> default.
    """
    val = headers.get(name.lower())
    if val is None:
        return default
    if isinstance(val, list):
        return val[-1] if val else default
    return val


def _decompress(raw, encoding):
    """Decode gzip or deflate bodies. Servers may compress even when not asked."""
    enc = (encoding or "").lower().strip()
    try:
        if enc == "gzip" or (not enc and raw[:2] == b"\x1f\x8b"):
            return gzip.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)  # raw deflate stream
        if enc == "br":
            try:
                import brotli
                return brotli.decompress(raw)
            except Exception:
                return raw  # brotli is not stdlib; leave the body as-is if unavailable
    except (OSError, zlib.error):
        return raw
    return raw


def _decode_body(raw, content_type):
    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return raw.decode("utf-8", errors="replace")


# Per-run fetch cache (PLAN.md section 16). Within one run the same URL is
# requested repeatedly (nav links on every page, shared assets, robots.txt);
# reusing one observation keeps the run polite to the target. Off by default;
# scan_site.run and run_review.pipeline enable it for their duration. Cached
# responses are treated as read-only by every scanner.
_FETCH_CACHE = None
_FETCH_CACHE_LOCK = threading.Lock()
_FETCH_CACHE_MAX = 512


def enable_fetch_cache():
    """Turn the per-run cache on. Keeps existing entries when already on, so
    a pipeline that enabled it before scan_site.run does not lose its warmup."""
    global _FETCH_CACHE
    with _FETCH_CACHE_LOCK:
        if _FETCH_CACHE is None:
            _FETCH_CACHE = {}


def disable_fetch_cache():
    global _FETCH_CACHE
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE = None


def http_fetch(url, method="GET", max_redirects=5, timeout=DEFAULT_TIMEOUT, want_body=True,
               extra_headers=None):
    """
    Fetch a URL, following redirects manually so the full chain is visible.

    Advertises gzip/deflate and decompresses the body, since some servers
    compress regardless. body_bytes is the transfer size over the wire (still
    compressed when the server compressed); uncompressed_bytes is the decoded
    size. Returns a dict with: ok, error, hops, final_url, final_status,
    final_headers, body, body_bytes, uncompressed_bytes, content_type,
    content_encoding, elapsed_ms.
    """
    url = normalize_url(url)
    cache_key = (method, url, want_body,
                 tuple(sorted((extra_headers or {}).items())))
    with _FETCH_CACHE_LOCK:
        if _FETCH_CACHE is not None and cache_key in _FETCH_CACHE:
            return _FETCH_CACHE[cache_key]
    opener = _opener()
    hops = []
    current = url
    started = time.perf_counter()
    body = None
    body_bytes = 0
    uncompressed_bytes = 0
    content_type = ""
    content_encoding = ""
    base_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    if extra_headers:
        base_headers.update(extra_headers)

    try:
        for _ in range(max_redirects + 1):
            req = urllib.request.Request(current, method=method, headers=base_headers)
            try:
                resp = opener.open(req, timeout=timeout)
                status = resp.status
                headers = resp.headers
            except urllib.error.HTTPError as e:
                # A 3xx with redirects disabled surfaces here; still a valid response.
                resp = e
                status = e.code
                headers = e.headers

            hop_headers = _headers_to_dict(headers)
            hops.append({"url": current, "status": status, "headers": hop_headers})

            location = headers.get("Location")
            if status in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                try:
                    resp.close()
                except Exception:
                    pass
                continue

            content_type = headers.get("Content-Type", "")
            content_encoding = headers.get("Content-Encoding", "")
            try:
                if want_body and method != "HEAD":
                    raw = resp.read(MAX_BODY_BYTES)
                    body_bytes = len(raw)
                    decompressed = _decompress(raw, content_encoding)
                    uncompressed_bytes = len(decompressed)
                    body = _decode_body(decompressed, content_type)
            finally:
                # Close on every path so a read error mid-body does not leak the
                # connection (it would otherwise skip straight to the outer except).
                try:
                    resp.close()
                except Exception:
                    pass
            break

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        final = hops[-1]
        result = {
            "ok": True,
            "error": None,
            "requested_url": url,
            "hops": hops,
            "final_url": final["url"],
            "final_status": final["status"],
            "final_headers": final["headers"],
            "content_type": content_type,
            "content_encoding": content_encoding,
            "body": body,
            "body_bytes": body_bytes,
            "uncompressed_bytes": uncompressed_bytes,
            "elapsed_ms": elapsed_ms,
        }
        # Only complete successes are cached; a transient failure on one page
        # must not poison the same URL for the rest of the run.
        with _FETCH_CACHE_LOCK:
            if _FETCH_CACHE is not None and len(_FETCH_CACHE) < _FETCH_CACHE_MAX:
                _FETCH_CACHE[cache_key] = result
        return result
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "requested_url": url,
            "hops": hops,
            "final_url": hops[-1]["url"] if hops else url,
            "final_status": hops[-1]["status"] if hops else None,
            "final_headers": hops[-1]["headers"] if hops else {},
            "content_type": content_type,
            "content_encoding": content_encoding,
            "body": body,
            "body_bytes": body_bytes,
            "uncompressed_bytes": uncompressed_bytes,
            "elapsed_ms": elapsed_ms,
        }


def env_value(name):
    """A secret from the environment, falling back to the repo-root .env file
    (which .gitignore excludes from version control). Never log the value."""
    import os
    if os.environ.get(name):
        return os.environ[name]
    path = repo_root() / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def http_post_json(url, payload, timeout=DEFAULT_TIMEOUT):
    """POST a JSON payload and parse a JSON response. Never raises; errors are
    returned. Part of the stubbed network-primitive set (see the contract
    tests), like http_fetch and doh_query."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status,
                    "json": json.loads(resp.read().decode("utf-8", errors="replace")),
                    "error": None}
    except urllib.error.HTTPError as e:
        detail = None
        try:
            detail = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            pass
        return {"ok": False, "status": e.code, "json": detail,
                "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "status": None, "json": None,
                "error": f"{type(e).__name__}: {e}"}


RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_rdap_bootstrap = None


def _http_get_json(url, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _rdap_base_for(tld, timeout=DEFAULT_TIMEOUT):
    """The registry's RDAP base URL for a TLD, from the cached IANA bootstrap."""
    global _rdap_bootstrap
    if _rdap_bootstrap is None:
        data = _http_get_json(RDAP_BOOTSTRAP_URL, timeout=timeout)
        mapping = {}
        for service in data.get("services", []):
            tlds, urls = service[0], service[1]
            if urls:
                base = urls[0].rstrip("/")
                for t in tlds:
                    mapping[t.lower()] = base
        _rdap_bootstrap = mapping
    return _rdap_bootstrap.get(tld.lower())


def parse_rdap_domain(data):
    """Registration facts from an RDAP domain response (pure, so it is unit
    tested offline). Reads the standard event actions. A non-object body (a
    stray null, array, or string from a third-party RDAP server) degrades to
    ok=False rather than raising."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "RDAP response was not a JSON object",
                "expiration": None, "registration": None}
    events = {e.get("eventAction"): e.get("eventDate")
              for e in (data.get("events") or []) if isinstance(e, dict) and e.get("eventAction")}
    return {"ok": True, "error": None,
            "expiration": events.get("expiration"),
            "registration": events.get("registration")}


def rdap_domain(domain, timeout=DEFAULT_TIMEOUT):
    """Public domain-registration facts via RDAP, the JSON successor to WHOIS,
    using the IANA bootstrap to find the registry's RDAP server. Passive (public
    registration data). Never raises: an unsupported TLD or any lookup failure
    returns ok=False so callers degrade honestly. Part of the stubbed
    network-primitive set (see the offline test header)."""
    tld = domain.rsplit(".", 1)[-1] if "." in domain else domain
    empty = {"ok": False, "expiration": None, "registration": None}
    try:
        base = _rdap_base_for(tld, timeout=timeout)
        if not base:
            return {**empty, "error": f"No RDAP service published for .{tld}"}
        data = _http_get_json(f"{base}/domain/{domain}", timeout=timeout)
    except Exception as e:
        return {**empty, "error": f"{type(e).__name__}: {e}"}
    return parse_rdap_domain(data)


def doh_query(name, rtype, timeout=DEFAULT_TIMEOUT):
    """
    Resolve a DNS record over HTTPS (Google public resolver).

    Passive and cross-platform: no local resolver library needed. Returns a dict
    with status and the raw answer list, or an error string.
    """
    q = f"https://dns.google/resolve?name={urllib.parse.quote(name)}&type={rtype}"
    req = urllib.request.Request(q, headers={"accept": "application/dns-json", "User-Agent": USER_AGENT})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
        answers = [a.get("data", "") for a in data.get("Answer", [])]
        return {"ok": True, "error": None, "status": data.get("Status"),
                "ad": data.get("AD", False), "answers": answers, "raw": data.get("Answer", [])}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "status": None,
                "ad": False, "answers": [], "raw": []}


def tls_info(host, port=443, timeout=DEFAULT_TIMEOUT):
    """Complete one TLS handshake and report the negotiated protocol,
    certificate, and ALPN result (offers h2 so HTTP/2 support is visible)."""
    import socket
    ctx = ssl.create_default_context()
    try:
        ctx.set_alpn_protocols(["h2", "http/1.1"])
    except NotImplementedError:
        pass  # ALPN unavailable in this OpenSSL; alpn stays None below
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                alpn = None
                try:
                    alpn = ss.selected_alpn_protocol()
                except NotImplementedError:
                    pass
                return {"ok": True, "error": None, "protocol": ss.version(),
                        "alpn": alpn, "cipher": ss.cipher(), "cert": ss.getpeercert()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "protocol": None, "alpn": None, "cipher": None, "cert": None}


def repo_root():
    """This file lives at .claude/skills/review-site/tools/common.py, so the
    repo root is four parents up (tools -> review-site -> skills -> .claude -> root)."""
    return Path(__file__).resolve().parents[4]


def evidence_dir():
    d = repo_root() / "planning" / "_evidence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_target_file():
    """First http line from TARGET.txt at the repo root, or None."""
    path = repo_root() / "TARGET.txt"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("http"):
            return line.strip()
    return None


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def verdicts_of(scan_result):
    """Every gradable verdict a scan produced. A scan that failed to run contributes nothing."""
    if not scan_result:
        return []
    if "checks" in scan_result:
        return [c.get("verdict") for c in scan_result["checks"].values() if c.get("verdict")]
    # A scanner that fell back to a single top-level verdict (for example a failed TLS handshake).
    top = scan_result.get("verdict")
    return [top] if top in ("pass", "warn", "fail") else []


def grade(verdicts):
    """
    Transparent posture band from the scanners' own verdicts. This is an
    aggregation of measured pass/warn/fail checks, not an invented benchmark:
    pass counts 1.0, warn 0.5, fail 0.0, info is not graded, and the raw counts
    always travel with the band. Shared by each tool (which grades its own
    checks) and the orchestrator scorecard, so the band logic lives in one place.
    """
    counts = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    graded = counts["pass"] + counts["warn"] + counts["fail"]
    if graded == 0:
        return {**counts, "graded": 0, "score": None, "band": "Not measured"}
    score = (counts["pass"] + counts["warn"] * 0.5) / graded
    band = ("Strong" if score >= 0.85 else "Adequate" if score >= 0.65
            else "Weak" if score >= 0.4 else "Poor")
    return {**counts, "graded": graded, "score": round(score, 2), "band": band}


def finalize(result, category):
    """Stamp a scan result with its own category and grade so the
    self-describing wrapper (PLAN.md section 4) is defined once here instead of
    copy-pasted into every scanner's scan(). The grade is the tool's own
    verdicts rolled up by grade(); returns the same dict for chaining."""
    result["category"] = category
    result["grade"] = grade(verdicts_of(result))
    return result


def summarize(checks):
    """Pass/warn/fail/info counts across a checks map, for a result's summary.
    Defined once instead of re-implemented in every scanner's _scan. A check
    with no verdict counts as info, so a malformed check never raises."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        verdict = c.get("verdict", "info")
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def enable_utf8_stdout():
    """Windows consoles default to cp1252 and choke on site content. Force UTF-8."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def print_json(obj):
    """Print JSON to stdout as UTF-8 bytes so non-ASCII page content never crashes the tool."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    try:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        print(json.dumps(obj, indent=2, ensure_ascii=True))
