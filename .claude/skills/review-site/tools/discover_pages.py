#!/usr/bin/env python3
"""
Passive page-discovery and scoping tool.

Helps decide which pages a review should cover. It reads the sitemap (following
one level of a sitemap index) and the homepage navigation, groups every URL it
finds by top-level section (skipping a leading locale segment like /en-us/), and
proposes a representative in-scope set: the homepage, each section landing, a
couple of deeper pages per section, and footer or legal pages. It fetches only
the homepage and the sitemaps, never the whole site, and proposes URLs rather
than crawling them.

Usage:
    python discover_pages.py [url] [output.json]
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common
import htmlmeta
import scan_dns_email as dns

MAX_CHILD_SITEMAPS = 5
MAX_URLS = 500
MAX_SECTIONS = 8
PER_SECTION = 3
MAX_PROPOSED = 15
LOCALE_RE = re.compile(r"^[a-z]{2}([-_][a-z]{2})?$", re.I)
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)
LEGAL_KEYWORDS = ("legal", "privacy", "terms", "cookie", "contact", "about",
                  "career", "imprint", "disclaimer", "accessibility", "gdpr")


def _section_of(url):
    segs = [s for s in urlparse(url).path.split("/") if s]
    if segs and LOCALE_RE.match(segs[0]):
        segs = segs[1:]
    return segs[0].lower() if segs else "(root)"


def _is_legal(url):
    path = urlparse(url).path.lower()
    return any(k in path for k in LEGAL_KEYWORDS)


def _collect_sitemap_urls(base, robots_sitemaps):
    start = robots_sitemaps[0] if robots_sitemaps else urljoin(base, "/sitemap.xml")
    res = common.http_fetch(start, want_body=True)
    if res["final_status"] != 200 or not res["body"]:
        return {"found": False, "urls": [], "sitemaps_read": []}
    body = res["body"]
    locs = LOC_RE.findall(body)
    if "<sitemapindex" in body.lower():
        page_urls, read = [], [start]
        for child in locs[:MAX_CHILD_SITEMAPS]:
            r = common.http_fetch(child, want_body=True)
            if r["final_status"] == 200 and r["body"]:
                page_urls.extend(LOC_RE.findall(r["body"]))
                read.append(child)
            if len(page_urls) >= MAX_URLS:
                break
        return {"found": True, "urls": page_urls[:MAX_URLS], "sitemaps_read": read}
    return {"found": True, "urls": locs[:MAX_URLS], "sitemaps_read": [start]}


def _internal_nav_links(anchors, base, domain):
    out, seen = [], set()
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        absolute = urljoin(base, href).split("#")[0]
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        if dns.registrable_domain(common.host_of(absolute)) != domain:
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def _propose(homepage, sections_map, legal_urls):
    """Homepage, then a landing plus a couple of deep pages for each major section, then legal."""
    proposed, seen = [], set()

    def add(u):
        if u and u not in seen:
            seen.add(u)
            proposed.append(u)

    add(homepage)
    ranked = sorted(sections_map.items(), key=lambda kv: len(kv[1]), reverse=True)
    for section, urls in ranked[:MAX_SECTIONS]:
        if section == "(root)":
            continue
        for u in sorted(urls, key=lambda x: len(urlparse(x).path))[:PER_SECTION]:
            add(u)
        if len(proposed) >= MAX_PROPOSED:
            break
    for u in legal_urls[:4]:
        add(u)
    return proposed[:MAX_PROPOSED]


def discover(url):
    url = common.normalize_url(url)
    home = common.http_fetch(url, want_body=True)
    if not home["ok"] and not home["body"]:
        return {"tool": "discover_pages", "target": url, "ok": False, "error": home["error"]}

    base = home["final_url"]
    domain = dns.registrable_domain(common.host_of(base))
    parsed = htmlmeta.parse_html(home["body"])
    render = htmlmeta.render_assessment(parsed, home["body"] or "")

    robots = common.http_fetch(urljoin(base, "/robots.txt"), want_body=True)
    robots_sitemaps = []
    if robots["final_status"] == 200 and robots.get("body"):
        robots_sitemaps = [l.split(":", 1)[1].strip() for l in robots["body"].splitlines()
                           if l.lower().startswith("sitemap:")]

    sm = _collect_sitemap_urls(base, robots_sitemaps)
    nav = _internal_nav_links(parsed["anchors"], base, domain)

    all_urls, seen = [], set()
    for u in [base] + sm["urls"] + nav:
        if dns.registrable_domain(common.host_of(u)) == domain and u not in seen:
            seen.add(u)
            all_urls.append(u)

    sections_map = {}
    for u in all_urls:
        sections_map.setdefault(_section_of(u), []).append(u)
    legal_urls = [u for u in all_urls if _is_legal(u)]
    proposed = _propose(base, sections_map, legal_urls)

    notes = []
    if render["likely_client_rendered"]:
        notes.append("Homepage is client-rendered; nav links may be sparse. The sitemap is the "
                     "primary source here.")
    if not sm["found"]:
        notes.append("No sitemap found; the proposed set is derived from homepage navigation only.")

    return {
        "tool": "discover_pages",
        "target": url,
        "homepage": base,
        "domain": domain,
        "sitemap": {"found": sm["found"], "sitemaps_read": sm["sitemaps_read"],
                    "url_count": len(sm["urls"])},
        "nav_links_found": len(nav),
        "total_internal_urls": len(all_urls),
        "sections": {s: len(u) for s, u in sorted(sections_map.items(),
                     key=lambda kv: len(kv[1]), reverse=True)},
        "legal_pages_found": legal_urls[:8],
        "proposed_review_set": proposed,
        "notes": " ".join(notes) or "Homepage plus representative section and legal pages.",
    }


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    if args and ("." in args[0] or args[0].lower().startswith("http")):
        target, out = args[0], (args[1] if len(args) > 1 else None)
    else:
        target, out = None, (args[0] if args else None)
    if not target:
        target = common.read_target_file()
    if not target:
        print("No target given and no http line found in TARGET.txt")
        sys.exit(1)

    result = discover(target)
    if out:
        common.write_json(out, result)
        print(f"Wrote {out}")
    else:
        print(f"Homepage: {result.get('homepage')}")
        print(f"Sitemap found: {result.get('sitemap', {}).get('found')} "
              f"({result.get('sitemap', {}).get('url_count')} urls)  |  "
              f"nav links: {result.get('nav_links_found')}")
        print("\nProposed review set:")
        for u in result.get("proposed_review_set", []):
            print(f"  {u}")
        if result.get("notes"):
            print(f"\nNote: {result['notes']}")


if __name__ == "__main__":
    main()
