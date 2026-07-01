#!/usr/bin/env python3
"""
Passive crawlability scanner: robots.txt and XML sitemap.

robots.txt and the sitemap are host-level facts, so they are checked once per
run here instead of once per page inside the SEO scanner (see PLAN.md section
9). The category stays "seo" because they remain SEO findings; the scorecard
merges them with the page-level SEO verdicts.

Usage:
    python scan_crawl.py <url> [output.json]
"""

import sys
from urllib.parse import urljoin

import common

CATEGORY = "seo"
SCOPE = "host"


def check_robots_txt(base):
    res = common.http_fetch(urljoin(base, "/robots.txt"), want_body=True)
    if res.get("final_status") is None:
        return {"present": None, "status": None, "sitemaps": [], "verdict": "info",
                "note": f"robots.txt could not be fetched ({res.get('error')}); presence unknown."}
    body = res.get("body") or ""
    if res["final_status"] == 200 and "user-agent" in body.lower():
        sitemaps = [l.split(":", 1)[1].strip() for l in body.splitlines()
                    if l.lower().startswith("sitemap:")]
        return {"present": True, "status": res["final_status"], "sitemaps": sitemaps,
                "verdict": "pass",
                "note": f"robots.txt present with {len(sitemaps)} sitemap reference(s)."}
    return {"present": False, "status": res["final_status"], "sitemaps": [],
            "verdict": "warn", "note": "No usable robots.txt at /robots.txt."}


def check_sitemap(base, robots_sitemaps):
    candidate = robots_sitemaps[0] if robots_sitemaps else urljoin(base, "/sitemap.xml")
    res = common.http_fetch(candidate, want_body=True)
    if res.get("final_status") is None:
        return {"url": candidate, "status": None, "verdict": "info",
                "note": f"Sitemap could not be fetched ({res.get('error')}); presence unknown."}
    body = res.get("body") or ""
    if res["final_status"] == 200 and ("<urlset" in body.lower() or "<sitemapindex" in body.lower()):
        return {"url": candidate, "status": res["final_status"], "verdict": "pass",
                "note": "XML sitemap reachable and well-formed at the root level."}
    return {"url": candidate, "status": res["final_status"], "verdict": "warn",
            "note": "No XML sitemap found at the expected location."}


def _scan(target):
    target = common.normalize_url(target)
    host = common.host_of(target)
    # Resolve the served base (scheme/host after redirects) so robots.txt and the
    # sitemap are looked up where the site actually lives, e.g. after www redirect.
    res = common.http_fetch(target, want_body=False)
    base = res["final_url"] if res.get("hops") else target

    robots = check_robots_txt(base)
    checks = {
        "robots_txt": robots,
        "sitemap": check_sitemap(base, robots.get("sitemaps", [])),
    }

    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1

    return {
        "tool": "scan_crawl",
        "target": target,
        "host": host,
        "base": base,
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
        print("Usage: python scan_crawl.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
