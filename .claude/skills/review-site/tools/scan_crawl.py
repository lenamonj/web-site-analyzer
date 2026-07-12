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


def _star_group_disallows_all(body):
    """True when the 'User-agent: *' group contains a bare 'Disallow: /' and
    no bare 'Allow: /' that re-opens it. Consecutive User-agent lines share
    one group until a directive seals it."""
    agents, sealed = set(), True
    disallow_all = allow_all = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = (p.strip() for p in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if sealed:
                agents, sealed = set(), False
            agents.add(value)
        else:
            sealed = True
            if "*" in agents and value == "/":
                if field == "disallow":
                    disallow_all = True
                elif field == "allow":
                    allow_all = True
    return disallow_all and not allow_all


def check_robots_txt(base):
    res = common.http_fetch(urljoin(base, "/robots.txt"), want_body=True)
    if not res["ok"]:  # fetch did not complete (no response, or a failed redirect)
        return {"present": None, "status": None, "sitemaps": [], "verdict": "info",
                "note": f"robots.txt could not be fetched ({res.get('error')}); presence unknown."}
    body = res.get("body") or ""
    if res["final_status"] == 200 and "user-agent" in body.lower():
        sitemaps = [l.split(":", 1)[1].strip() for l in body.splitlines()
                    if l.lower().startswith("sitemap:")]
        if _star_group_disallows_all(body):
            return {"present": True, "status": res["final_status"], "sitemaps": sitemaps,
                    "disallows_all": True, "verdict": "fail",
                    "note": ("robots.txt disallows the entire site for every crawler "
                             "(User-agent: * with Disallow: /). Search engines are "
                             "blocked site-wide.")}
        return {"present": True, "status": res["final_status"], "sitemaps": sitemaps,
                "disallows_all": False, "verdict": "pass",
                "note": ("robots.txt present with "
                         f"{common.count_noun(len(sitemaps), 'sitemap reference')}."
                         if sitemaps else "robots.txt present; no sitemap reference.")}
    return {"present": False, "status": res["final_status"], "sitemaps": [],
            "verdict": "warn", "note": "No usable robots.txt at /robots.txt."}


def check_sitemap(base, robots_sitemaps):
    candidate = robots_sitemaps[0] if robots_sitemaps else urljoin(base, "/sitemap.xml")
    res = common.http_fetch(candidate, want_body=True)
    if not res["ok"]:  # fetch did not complete (no response, or a failed redirect)
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
    apex = common.registrable_domain(host)
    if host not in (apex, f"www.{apex}"):
        return {"verdict": "info", "host": host,
                "note": f"Host {host} is a subdomain; apex/www canonicalization not applicable."}
    variants = {h: common.http_fetch(f"https://{h}", want_body=False)
                for h in (apex, f"www.{apex}")}
    # A host is reachable only if the fetch reached a terminal response; a redirect
    # loop or over-cap chain has ok=False (though final_status is a 3xx), so it must
    # not count as a live, converged host.
    reachable = {h: r for h, r in variants.items() if r.get("ok")}
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

    tally = common.summarize(checks)

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
    return common.finalize(result, CATEGORY)


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
