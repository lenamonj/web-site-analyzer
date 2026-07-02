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
import scan_dns_email as dns

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


def check_host_canonicalization(host):
    """Apex vs www duplicate-site risk. Two live versions of the same site
    that never converge split link equity and confuse crawlers. Applies only
    when the target is the apex or www.<apex>; a real subdomain site has no
    www twin to canonicalize."""
    apex = dns.registrable_domain(host)
    if host not in (apex, f"www.{apex}"):
        return {"verdict": "info", "host": host,
                "note": f"Host {host} is a subdomain; apex/www canonicalization not applicable."}
    variants = {h: common.http_fetch(f"https://{h}", want_body=False)
                for h in (apex, f"www.{apex}")}
    reachable = {h: r for h, r in variants.items() if r.get("final_status") is not None}
    if len(reachable) < 2:
        missing = [h for h in variants if h not in reachable][0]
        return {"verdict": "info", "unreachable": missing,
                "note": f"https://{missing} does not answer; only one live host variant."}
    final_hosts = {h: common.host_of(r["final_url"]) for h, r in reachable.items()}
    if len(set(final_hosts.values())) == 1:
        canonical = next(iter(set(final_hosts.values())))
        return {"verdict": "pass", "canonical_host": canonical, "final_hosts": final_hosts,
                "note": f"apex and www converge on {canonical}."}
    statuses = {h: r["final_status"] for h, r in reachable.items()}
    if all(s == 200 for s in statuses.values()):
        return {"verdict": "warn", "final_hosts": final_hosts,
                "note": ("Both the apex and www hosts serve the site without converging on one "
                         "canonical host; two live versions split link equity.")}
    return {"verdict": "info", "final_hosts": final_hosts, "statuses": statuses,
            "note": "apex and www do not converge and return mixed statuses."}


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
        "host_canonicalization": check_host_canonicalization(host),
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
