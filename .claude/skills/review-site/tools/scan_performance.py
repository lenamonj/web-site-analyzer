#!/usr/bin/env python3
"""
Passive page-weight analyzer.

Measures the initial HTML document size and the weight of the static resources
the HTML declares (scripts, stylesheets, images), counts third-party origins,
and counts render-blocking head scripts. It only weighs what the shipped HTML
references; resources a single-page app loads later via JavaScript are not
counted, so the totals are a floor, not the full transfer. That limitation is
stated in the output rather than hidden.

Usage:
    python scan_performance.py <url> [output.json]
"""

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import common
import htmlmeta

MAX_RESOURCES = 40
RES_TIMEOUT = 8
MAX_WORKERS = 8          # browser-like fan-out; polite but not serial

CATEGORY = "performance"
SCOPE = "page"
HTML_WARN_BYTES = 150_000        # a shipped HTML doc heavier than this is notable
TOTAL_WARN_BYTES = 1_500_000     # measured static weight floor for a warning
TOTAL_FAIL_BYTES = 3_500_000
BLOCKING_SCRIPTS_WARN = 3

SCRIPT_RE = common.tag_attrs_re("script")
# (?<![-\w]) not \b: a consent-gated <script data-src=...> must not be
# measured as a live resource (a bare \b matches inside data-src).
SRC_RE = re.compile(r'(?<![-\w])src\s*=\s*["\']([^"\']+)["\']', re.I)
# async/defer as boolean attribute NAMES (token-bounded), not a bare substring:
# an attribute like data-async-init or a class must not read as async/defer.
ASYNC_ATTR_RE = re.compile(r"(?<![-\w])async(?![-\w])", re.I)
DEFER_ATTR_RE = re.compile(r"(?<![-\w])defer(?![-\w])", re.I)


def _kb(n):
    return round(n / 1024, 1)


def _script_resources(html, base):
    """Return script URLs with a render-blocking flag (no async and no defer)."""
    out = []
    for attrs in SCRIPT_RE.findall(html or ""):
        m = SRC_RE.search(attrs)
        if not m:
            continue
        # async/defer are boolean attributes; strip quoted values first so a src
        # path like async.js is not misread, then match the attribute NAME as a
        # token so data-async-init / an unrelated word does not count as async.
        bare = re.sub(r'"[^"]*"|\'[^\']*\'', "", attrs)
        blocking = not ASYNC_ATTR_RE.search(bare) and not DEFER_ATTR_RE.search(bare)
        url = common.safe_urljoin(base, m.group(1))
        if url is not None:
            out.append({"url": url, "blocking": blocking})
    return out


def _collect_resources(html, parsed, base):
    resources = []
    for s in _script_resources(html, base):
        resources.append({"url": s["url"], "type": "script", "blocking": s["blocking"]})
    for l in parsed["links"]:
        if "stylesheet" in (l.get("rel", "").lower()) and l.get("href"):
            url = common.safe_urljoin(base, l["href"])
            if url is not None:
                resources.append({"url": url, "type": "stylesheet", "blocking": True})
    for img in parsed["images"]:
        if img.get("src"):
            url = common.safe_urljoin(base, img["src"])
            if url is not None:
                resources.append({"url": url, "type": "image", "blocking": False})
    # De-duplicate by URL, keep first classification.
    seen, unique = set(), []
    for r in resources:
        if r["url"] in seen or urlparse(r["url"]).scheme not in ("http", "https"):
            continue
        seen.add(r["url"])
        unique.append(r)
    return unique


def _measure(resource):
    res = common.http_fetch(resource["url"], method="HEAD", want_body=False, timeout=RES_TIMEOUT)
    headers = res.get("final_headers") or {}
    # A duplicated Content-Length folds to a list (identical values per RFC 7230);
    # read the last value so str(...).isdigit() sees a string, not the list repr.
    # cache_control below stays list-valued on purpose: repeated Cache-Control
    # combines, and _cache_max_age joins it (unlike last-value, which would drop
    # directives).
    length = common.header_value(headers, "content-length")
    size = int(length) if length and str(length).isdigit() else None
    return {**resource, "bytes": size, "status": res.get("final_status"),
            "cache_control": headers.get("cache-control"),
            "expires": common.header_value(headers, "expires")}


def _cc_seconds(cc, directive):
    """Seconds from a Cache-Control delta-seconds directive (max-age, s-maxage),
    or None when absent. The (?<![-\\w]) lookbehind keeps max-age from matching
    inside another token and keeps the two directives distinct."""
    if not cc:
        return None
    if isinstance(cc, list):
        cc = ", ".join(cc)
    m = re.search(rf"(?<![-\w]){re.escape(directive)}\s*=\s*(\d+)", cc, re.I)
    return int(m.group(1)) if m else None


def _cache_max_age(cc):
    """max-age seconds from a Cache-Control value, or None when absent."""
    return _cc_seconds(cc, "max-age")


def _future_expires(expires):
    """True if an Expires header names a still-future instant. A malformed or
    past Expires (including the common Expires: 0) is already stale, so it is
    not a usable caching lifetime. Expires is the HTTP/1.0 freshness mechanism,
    honored by browsers when Cache-Control max-age is absent."""
    if not expires:
        return False
    if isinstance(expires, list):
        expires = expires[-1]
    try:
        exp = parsedate_to_datetime(expires)
    except (TypeError, ValueError):
        return False
    if exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > datetime.now(timezone.utc)


def _asset_caching_check(measured, inconclusive):
    """Grade caching on the declared static assets that answered 200. An asset
    with no freshness lifetime (no max-age and not immutable, or no-store /
    no-cache) is redownloaded on every repeat visit."""
    ok_assets = [r for r in measured if r.get("status") == 200]
    if inconclusive or not ok_assets:
        note = ("Page is client-rendered; declared assets are not representative."
                if inconclusive else "No declared assets answered to measure caching.")
        return {"verdict": "info", "measured": len(ok_assets), "note": note}
    uncached = []
    for r in ok_assets:
        cc = r.get("cache_control")
        low = (", ".join(cc) if isinstance(cc, list) else cc or "").lower()
        max_age = _cache_max_age(cc)
        s_maxage = _cc_seconds(cc, "s-maxage")
        has_lifetime = ("immutable" in low
                        or (max_age is not None and max_age > 0)
                        or (s_maxage is not None and s_maxage > 0)
                        or _future_expires(r.get("expires")))
        # Cache-Control no-store/no-cache override any Expires, matching browsers.
        cached = has_lifetime and "no-store" not in low and "no-cache" not in low
        if not cached:
            uncached.append(r["url"])
    if len(uncached) * 2 > len(ok_assets):
        return {"verdict": "warn", "measured": len(ok_assets), "uncached": len(uncached),
                "examples": uncached[:5],
                "note": (f"{len(uncached)} of {len(ok_assets)} measured static asset(s) have no "
                         "usable caching lifetime (no max-age or marked no-store); repeat visits "
                         "redownload them.")}
    return {"verdict": "pass", "measured": len(ok_assets), "uncached": len(uncached),
            "note": (f"{len(ok_assets) - len(uncached)} of {len(ok_assets)} measured static "
                     "asset(s) carry a caching lifetime.")}


def _redirect_chain_check(res):
    """Each redirect before the final URL adds a full round trip before the
    first byte of content."""
    hops = res.get("hops", [])
    redirects = max(0, len(hops) - 1)
    chain = [f'{h["status"]} {h["url"]}' for h in hops]
    if redirects >= 2:
        return {"verdict": "warn", "redirects": redirects, "chain": chain,
                "note": f"{redirects} redirects before the final URL; each adds a round trip."}
    if redirects == 1:
        return {"verdict": "pass", "redirects": 1, "chain": chain,
                "note": "One redirect to the final URL."}
    return {"verdict": "pass", "redirects": 0, "note": "No redirects; the URL serves directly."}


def _compression_check(res):
    enc = (res.get("content_encoding") or "").lower().strip()
    transfer, uncompressed = res.get("body_bytes", 0), res.get("uncompressed_bytes", 0)
    if enc in ("gzip", "deflate", "br"):
        ratio = round(uncompressed / transfer, 1) if transfer else None
        return {"encoding": enc, "transfer_kb": _kb(transfer), "uncompressed_kb": _kb(uncompressed),
                "ratio": ratio, "verdict": "pass",
                "note": f"HTML is served with {enc} compression ({ratio}x smaller on the wire)."}
    return {"encoding": None, "transfer_kb": _kb(transfer), "verdict": "warn",
            "note": "HTML response is not compressed; enabling gzip or brotli would cut transfer size."}


def _caching_check(headers):
    # Coalesce a duplicated Cache-Control (folded to a list) to one string so
    # the info note and stored value never render a Python list repr (L18).
    cc = common.header_value(headers, "cache-control")
    etag = bool(headers.get("etag"))
    if cc:
        return {"cache_control": cc, "etag": etag, "verdict": "info", "note": f"Cache-Control: {cc}."}
    return {"cache_control": None, "etag": etag, "verdict": "info",
            "note": "No Cache-Control on the HTML document" + (" (ETag present)." if etag else ".")}


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_performance", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    html = res["body"] or ""
    page_domain = common.registrable_domain(common.host_of(base))

    resources = _collect_resources(html, parsed, base)
    truncated = len(resources) > MAX_RESOURCES
    sample = resources[:MAX_RESOURCES]
    measured = []
    if sample:
        # executor.map preserves input order, so results stay deterministic.
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(sample))) as pool:
            measured = list(pool.map(_measure, sample))

    by_type = {}
    for r in measured:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    known = [r for r in measured if r["bytes"] is not None]
    resource_bytes = sum(r["bytes"] for r in known)
    unknown_size = len(measured) - len(known)
    third_party = sorted({common.host_of(r["url"]) for r in measured
                          if common.registrable_domain(common.host_of(r["url"])) != page_domain})
    blocking_scripts = [r for r in measured if r["type"] == "script" and r.get("blocking")]
    largest = sorted(known, key=lambda r: r["bytes"], reverse=True)[:5]

    html_bytes = res["body_bytes"]
    total_floor = html_bytes + resource_bytes

    checks = {
        "html_document_size": {
            "bytes": html_bytes, "kb": _kb(html_bytes),
            "verdict": "warn" if html_bytes > HTML_WARN_BYTES else "pass",
            "note": (f"Initial HTML document is {_kb(html_bytes)} KB."
                     + (" That is heavy for a first response." if html_bytes > HTML_WARN_BYTES else ""))},
        "static_weight": {
            "html_bytes": html_bytes, "resource_bytes": resource_bytes,
            "total_floor_bytes": total_floor, "total_floor_kb": _kb(total_floor),
            "resources_measured": len(measured), "resources_unknown_size": unknown_size,
            "verdict": ("fail" if total_floor > TOTAL_FAIL_BYTES
                        else "warn" if total_floor > TOTAL_WARN_BYTES else "pass"),
            "note": (f"Static weight floor is {_kb(total_floor)} KB across HTML plus "
                     f"{len(measured)} measured resource(s). JS-loaded resources are not counted.")},
        "render_blocking_scripts": {
            "count": len(blocking_scripts),
            "examples": [r["url"] for r in blocking_scripts[:5]],
            "verdict": "warn" if len(blocking_scripts) > BLOCKING_SCRIPTS_WARN else "pass",
            "note": (f"{len(blocking_scripts)} render-blocking script(s) in the shipped HTML "
                     "(no async or defer).")},
        "third_party_origins": {
            "count": len(third_party), "hosts": third_party[:15], "verdict": "info",
            "note": f"{len(third_party)} third-party resource origin(s)."},
        "compression": _compression_check(res),
        "caching": _caching_check(res.get("final_headers", {}) or {}),
        "asset_caching": _asset_caching_check(measured, render["likely_client_rendered"]),
        "redirect_chain": _redirect_chain_check(res),
    }
    if render["likely_client_rendered"]:
        checks["static_weight"]["note"] += " Page is client-rendered, so most weight is not visible here."

    tally = common.summarize(checks)

    return {
        "tool": "scan_performance",
        "target": url,
        "final_url": base,
        "ok": True,
        "render": render,
        "resource_counts": by_type,
        "largest_resources": [{"url": r["url"], "type": r["type"], "kb": _kb(r["bytes"])} for r in largest],
        "resources_truncated": truncated,
        "summary": tally,
        "checks": checks,
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    return common.finalize(result, CATEGORY)


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_performance.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
