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
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urldefrag, urljoin, urlparse

import common
import htmlmeta

MAX_LINKS = 30          # bound total runtime; report when more exist
LINK_TIMEOUT = 8
# Bounded fan-out. Eight concurrent requests is comparable to a browser's
# per-host connection pool, so the probe stays polite to the target while a
# page full of slow or dead links no longer takes minutes serially.
MAX_WORKERS = 8
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")

CATEGORY = "links"
SCOPE = "page"
# Insecure resource or link references on a page: tag plus the http URL.
# The attribute region tolerates '>' inside quoted values, and the attribute
# name is anchored so data-src / data-href lazy-load attributes (which the
# browser does not fetch) are not reported as mixed content.
# <link> is handled separately (below) because whether an http href is mixed
# content depends on its rel: only a subresource-loading rel counts.
# (?![-\w]) not \b after the tag name: \b matches at the name->hyphen boundary, so a
# custom element like <video-player src="http://..."> would false-match "video" and be
# graded as (fabricated) mixed content. Require the tag name to end here.
MIXED_RE = re.compile(r"<(script|img|iframe|source|audio|video)(?![-\w])"
                      r"(?:[^>\"']|\"[^\"]*\"|'[^']*')*?"
                      r"(?<![-\w])(?:src|href)\s*=\s*[\"'](http://[^\"']+)", re.I)
ACTIVE_TAGS = {"script", "iframe"}

LINK_TAG_RE = common.tag_attrs_re("link")
ATTR_HTTP_HREF_RE = re.compile(r"""(?<![-\w])href\s*=\s*["'](http://[^"']+)""", re.I)
ATTR_REL_RE = re.compile(r"""(?<![-\w])rel\s*=\s*["']([^"']*)""", re.I)
ATTR_AS_RE = re.compile(r"""(?<![-\w])as\s*=\s*["']([^"']*)""", re.I)
# <link> rels that actually fetch a subresource over the wire. A non-loading rel
# (canonical, alternate, preconnect, dns-prefetch, prev/next, me, ...) is a URL
# reference or a connection hint, never mixed content.
SUBRESOURCE_LINK_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon",
                         "mask-icon", "preload", "modulepreload", "prefetch"}
# A preload/prefetch is active mixed content only when it loads executable or
# render-blocking content; stylesheet is always active.
ACTIVE_LINK_AS = {"script", "style", "worker", "font"}


def _candidate_links(anchors, base):
    seen, out = set(), []
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(SKIP_SCHEMES):
            continue
        absolute = common.safe_urljoin(base, href)
        if absolute is None or urlparse(absolute).scheme not in ("http", "https"):
            continue  # skip a malformed href, do not abort the whole scan
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
    return out


def _classify(status):
    """
    Only a 404/410 or a real 5xx server error is a defensible 'broken' verdict. A
    401/403/429, or a non-standard high code like LinkedIn's 999, is access
    controlled or bot protection on a link that works in a real browser, so it is
    reported as 'restricted', never broken. A connection failure is 'unreachable'
    (ambiguous: could be a block or a real outage), also not counted as broken.
    """
    if status is None:
        return "unreachable"
    if status in (404, 410) or (500 <= status < 600):
        return "broken"
    if status >= 400:
        return "restricted"
    return "ok"


def _check_one(url, page_host):
    res = common.http_fetch(url, method="HEAD", want_body=False, timeout=LINK_TIMEOUT)
    status = res.get("final_status")
    if status is None or status == 405 or (500 <= status < 600):
        # Some servers reject or error on HEAD (405 Method Not Allowed, or any 5xx
        # from a backend that throws on an unimplemented HEAD) yet serve the same
        # URL fine on GET. Fall back to GET without downloading the body before
        # calling a link broken, so a HEAD-only defect is not a fabricated 5xx.
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


def _strip_comments(html):
    """Remove HTML comments before matching so a resource referenced only inside
    <!-- ... --> (which no browser fetches) is not miscounted as mixed content. A
    linear string scan, not a lazy <!--.*?--> regex, which backtracks
    catastrophically on many unclosed '<!--' (ReDoS; cf. the N6 sitemap fix)."""
    if "<!--" not in html:
        return html
    out, i = [], 0
    while True:
        start = html.find("<!--", i)
        if start == -1:
            out.append(html[i:])
            break
        out.append(html[i:start])
        end = html.find("-->", start + 4)
        if end == -1:
            break  # an unclosed comment runs to end of document; a browser ignores it
        i = end + 3
    return "".join(out)


def _mixed_content(html, is_https):
    if not is_https or not html:
        return {"count": 0, "items": [], "verdict": "info" if not is_https else "pass",
                "note": ("Page not served over HTTPS; mixed content not applicable."
                         if not is_https else "No insecure http resources referenced.")}
    html = _strip_comments(html)
    found, seen = [], set()
    for tag, url in MIXED_RE.findall(html):
        key = (tag.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        found.append({"tag": tag.lower(), "url": url, "active": tag.lower() in ACTIVE_TAGS})
    for attrs in LINK_TAG_RE.findall(html):
        href = ATTR_HTTP_HREF_RE.search(attrs)
        if not href:
            continue
        rel_m = ATTR_REL_RE.search(attrs)
        rels = set(rel_m.group(1).lower().split()) if rel_m else set()
        if not rels & SUBRESOURCE_LINK_RELS:
            continue  # canonical/alternate/preconnect/dns-prefetch: not a fetch
        url = href.group(1)
        key = ("link", url)
        if key in seen:
            continue
        seen.add(key)
        as_m = ATTR_AS_RE.search(attrs)
        as_val = as_m.group(1).lower() if as_m else ""
        active = "stylesheet" in rels or (
            rels & {"preload", "modulepreload", "prefetch"} and as_val in ACTIVE_LINK_AS)
        found.append({"tag": "link", "url": url, "active": active})
    if not found:
        return {"count": 0, "items": [], "verdict": "pass",
                "note": "No insecure http resources referenced."}
    active = [f for f in found if f["active"]]
    verdict = "fail" if active else "warn"
    note = (f"{common.count_noun(len(found), 'insecure http reference')}, of which "
            f"{len(active)} active content (script/iframe/stylesheet).")
    return {"count": len(found), "items": found[:15], "verdict": verdict, "note": note}


def _fragment_check(anchors, ids, base, inconclusive):
    """In-page anchors that point at no element id scroll nowhere. Both bare
    '#fragment' hrefs and path-form same-page hrefs ('/#fragment' from the
    page at '/') count; fragments aimed at other pages cannot be verified
    without their ids and are skipped. '#top' is a browser built-in and a
    bare '#' is a JS-link pattern, so both are excluded."""
    if inconclusive:
        return {"verdict": "info",
                "note": "Page is client-rendered; in-page anchors are not assessable statically."}
    def _same_page(u1, u2):
        # An empty path and "/" are the same resource (http://host vs http://host/).
        p1, p2 = urlparse(u1), urlparse(u2)
        return ((p1.scheme, p1.netloc, p1.path or "/", p1.query)
                == (p2.scheme, p2.netloc, p2.path or "/", p2.query))

    page_base = urldefrag(base)[0]
    targets = []
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("#"):
            frag = href[1:]
        else:
            joined = common.safe_urljoin(page_base, href)
            if joined is None:
                continue
            absolute, frag = urldefrag(joined)
            if not _same_page(absolute, page_base):
                continue
        if frag:
            targets.append(frag)
    if not targets:
        return {"verdict": "info", "count": 0, "note": "No in-page fragment links in the page markup."}
    id_set = set(ids)
    missing = sorted({t for t in targets if t not in id_set and t.lower() != "top"})
    if missing:
        examples = ", ".join("#" + m for m in missing[:5])
        return {"verdict": "warn", "count": len(targets), "missing": missing[:10],
                "note": (f"{common.count_noun(len(missing), 'in-page anchor target')} "
                         f"missing from the page ({examples}); those links scroll nowhere.")}
    return {"verdict": "pass", "count": len(targets),
            "note": f"{common.count_noun(len(targets), 'in-page fragment link')} "
                    "checked; all resolve to an element id."}


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
    sample = candidates[:MAX_LINKS]
    page_host = common.host_of(base)
    checked = []
    if sample:
        # executor.map preserves input order, so results stay deterministic.
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(sample))) as pool:
            checked = list(pool.map(lambda u: _check_one(u, page_host), sample))

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
        "anchor_fragments": _fragment_check(parsed["anchors"], parsed["ids"], base,
                                            render["likely_client_rendered"]),
    }
    tally = common.summarize(checks)

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
    return common.finalize(result, CATEGORY)


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
