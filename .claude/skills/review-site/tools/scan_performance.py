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
from urllib.parse import urljoin, urlparse

import common
import htmlmeta
import scan_dns_email as dns

MAX_RESOURCES = 40
RES_TIMEOUT = 8
HTML_WARN_BYTES = 150_000        # a shipped HTML doc heavier than this is notable
TOTAL_WARN_BYTES = 1_500_000     # measured static weight floor for a warning
TOTAL_FAIL_BYTES = 3_500_000
BLOCKING_SCRIPTS_WARN = 3

SCRIPT_RE = re.compile(r'<script\b([^>]*)>', re.I)
SRC_RE = re.compile(r'\bsrc\s*=\s*["\']([^"\']+)["\']', re.I)


def _kb(n):
    return round(n / 1024, 1)


def _script_resources(html, base):
    """Return script URLs with a render-blocking flag (no async and no defer)."""
    out = []
    for attrs in SCRIPT_RE.findall(html or ""):
        m = SRC_RE.search(attrs)
        if not m:
            continue
        low = attrs.lower()
        blocking = "async" not in low and "defer" not in low
        out.append({"url": urljoin(base, m.group(1)), "blocking": blocking})
    return out


def _collect_resources(html, parsed, base):
    resources = []
    for s in _script_resources(html, base):
        resources.append({"url": s["url"], "type": "script", "blocking": s["blocking"]})
    for l in parsed["links"]:
        if "stylesheet" in (l.get("rel", "").lower()) and l.get("href"):
            resources.append({"url": urljoin(base, l["href"]), "type": "stylesheet", "blocking": True})
    for img in parsed["images"]:
        if img.get("src"):
            resources.append({"url": urljoin(base, img["src"]), "type": "image", "blocking": False})
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
    length = res["final_headers"].get("content-length") if res.get("final_headers") else None
    size = int(length) if length and str(length).isdigit() else None
    return {**resource, "bytes": size, "status": res.get("final_status")}


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
    cc = headers.get("cache-control")
    etag = bool(headers.get("etag"))
    if cc:
        return {"cache_control": cc, "etag": etag, "verdict": "info", "note": f"Cache-Control: {cc}."}
    return {"cache_control": None, "etag": etag, "verdict": "info",
            "note": "No Cache-Control on the HTML document" + (" (ETag present)." if etag else ".")}


def scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_performance", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    html = res["body"] or ""
    page_domain = dns.registrable_domain(common.host_of(base))

    resources = _collect_resources(html, parsed, base)
    truncated = len(resources) > MAX_RESOURCES
    measured = [_measure(r) for r in resources[:MAX_RESOURCES]]

    by_type = {}
    for r in measured:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    known = [r for r in measured if r["bytes"] is not None]
    resource_bytes = sum(r["bytes"] for r in known)
    unknown_size = len(measured) - len(known)
    third_party = sorted({common.host_of(r["url"]) for r in measured
                          if dns.registrable_domain(common.host_of(r["url"])) != page_domain})
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
    }
    if render["likely_client_rendered"]:
        checks["static_weight"]["note"] += " Page is client-rendered, so most weight is not visible here."

    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1

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
