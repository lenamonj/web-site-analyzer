#!/usr/bin/env python3
"""
Passive link-health and mixed-content scanner.

Follows only the links and resources the page already declares. It samples the
in-page links and reports which are broken (4xx/5xx or unreachable) or redirect,
and on an HTTPS page it flags insecure http:// resources (mixed content). It
never brute forces paths or requests anything the page did not reference.

Usage:
    python scan_links.py <url> [output.json]
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common
import htmlmeta

MAX_LINKS = 30          # bound total runtime; report when more exist
LINK_TIMEOUT = 8
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")

CATEGORY = "links"
SCOPE = "page"
# Insecure resource or link references on a page: tag plus the http URL.
MIXED_RE = re.compile(r'<(script|img|iframe|link|source|audio|video)\b[^>]*?'
                      r'(?:src|href)\s*=\s*["\'](http://[^"\']+)', re.I)
ACTIVE_TAGS = {"script", "iframe", "link"}


def _candidate_links(anchors, base):
    seen, out = set(), []
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(SKIP_SCHEMES):
            continue
        absolute = urljoin(base, href)
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
    return out


def _classify(status):
    """
    Only a 404/410 or a 5xx is a defensible 'broken' verdict. A 401/403/429 is
    access controlled or rate limited (frequently bot protection on a link that
    works in a real browser), so it is reported as 'restricted', never broken. A
    connection failure is 'unreachable' (ambiguous: could be a block or a real
    outage), also not counted as broken.
    """
    if status is None:
        return "unreachable"
    if status in (404, 410) or status >= 500:
        return "broken"
    if status >= 400:
        return "restricted"
    return "ok"


def _check_one(url, page_host):
    res = common.http_fetch(url, method="HEAD", want_body=False, timeout=LINK_TIMEOUT)
    status = res.get("final_status")
    if status in (405, 501, None):
        # Some servers reject HEAD; fall back to GET without downloading the body.
        res = common.http_fetch(url, method="GET", want_body=False, timeout=LINK_TIMEOUT)
        status = res.get("final_status")
    internal = common.host_of(url) == page_host
    redirected = len(res.get("hops", [])) > 1
    state = _classify(status)
    if state == "ok" and redirected:
        state = "redirect"
    out = {"url": url, "status": status, "internal": internal, "state": state}
    if state == "unreachable":
        out["detail"] = res.get("error")
    if state == "redirect":
        out["final_url"] = res["final_url"]
    return out


def _mixed_content(html, is_https):
    if not is_https or not html:
        return {"count": 0, "items": [], "verdict": "info" if not is_https else "pass",
                "note": ("Page not served over HTTPS; mixed content not applicable."
                         if not is_https else "No insecure http resources referenced.")}
    found, seen = [], set()
    for tag, url in MIXED_RE.findall(html):
        key = (tag.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        found.append({"tag": tag.lower(), "url": url, "active": tag.lower() in ACTIVE_TAGS})
    if not found:
        return {"count": 0, "items": [], "verdict": "pass",
                "note": "No insecure http resources referenced."}
    active = [f for f in found if f["active"]]
    verdict = "fail" if active else "warn"
    note = (f"{len(found)} insecure http reference(s); {len(active)} are active content "
            f"(script/iframe/stylesheet).")
    return {"count": len(found), "items": found[:15], "verdict": verdict, "note": note}


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_links", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    is_https = urlparse(base).scheme == "https"

    candidates = _candidate_links(parsed["anchors"], base)
    truncated = len(candidates) > MAX_LINKS
    checked = [_check_one(u, common.host_of(base)) for u in candidates[:MAX_LINKS]]

    broken = [c for c in checked if c["state"] == "broken"]
    unreachable = [c for c in checked if c["state"] == "unreachable"]
    restricted = [c for c in checked if c["state"] == "restricted"]
    redirects = [c for c in checked if c["state"] == "redirect"]
    counts = {"ok": sum(1 for c in checked if c["state"] == "ok"),
              "redirect": len(redirects), "restricted": len(restricted),
              "unreachable": len(unreachable), "broken": len(broken)}

    if render["likely_client_rendered"]:
        link_check = {"verdict": "info",
                      "note": "Page is client-rendered; most links load via JS and are not in static HTML."}
    elif broken:
        link_check = {"verdict": "fail", "broken_examples": broken[:10],
                      "note": f"{len(broken)} of {len(checked)} sampled links are broken (404/410/5xx)."}
    elif unreachable:
        link_check = {"verdict": "warn", "unreachable_examples": unreachable[:10],
                      "note": (f"{len(unreachable)} of {len(checked)} sampled links did not respond "
                               "(could be an outage or a block, not confirmed broken).")}
    elif restricted:
        link_check = {"verdict": "info", "restricted_examples": restricted[:10],
                      "note": (f"{len(restricted)} of {len(checked)} sampled links returned 401/403/429, "
                               "likely bot protection rather than broken links.")}
    elif redirects:
        link_check = {"verdict": "info", "redirect_examples": redirects[:10],
                      "note": f"{len(redirects)} of {len(checked)} sampled links redirect before resolving."}
    else:
        link_check = {"verdict": "pass",
                      "note": f"All {len(checked)} sampled links resolve directly."}
    link_check["checked"] = len(checked)
    link_check["counts"] = counts
    link_check["total_candidates"] = len(candidates)
    link_check["truncated"] = truncated

    checks = {
        "link_health": link_check,
        "mixed_content": _mixed_content(res["body"], is_https),
    }
    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1

    return {
        "tool": "scan_links",
        "target": url,
        "final_url": base,
        "ok": True,
        "render": render,
        "summary": tally,
        "checks": checks,
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    result["category"] = CATEGORY
    result["grade"] = common.grade(common.verdicts_of(result))
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_links.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
