#!/usr/bin/env python3
"""
Prospect triage: rank many company sites by how much they need a review.

The full pipeline produces one deep, browser-driven report per site. Outreach
is the inverse job: sweep many sites fast and find the few worth a full review
and a pitch. This utility runs a static, homepage-only pass over a domain list
(reusing the same scoring engine the deep report uses, so nothing here is a
second opinion), ranks the sites worst-first (a worse measured posture is a
stronger prospect), and hands the salesperson one measured door-opener per
site. See PLAN.md section 36.

Strictly passive and external, like every scanner: one homepage visit per
domain, serial, with a polite delay between domains. Prospect data is business
material, so input and output live under the git-ignored sales/ directory.

Usage:
    python triage.py                       # reads sales/prospects.txt (or PROSPECTS.txt)
    python triage.py acme.com globex.com   # score the domains given on the CLI
    python triage.py --file path/to/list.txt
    python triage.py --delay 2.0           # seconds between domains (default 1.0)
"""

import csv
import sys
import time
from pathlib import Path

import common
import scan_site

INTER_DOMAIN_DELAY = 1.0
CSV_COLUMNS = ["rank", "domain", "band", "score", "worst_area", "fails", "warns", "hook"]

# Human labels for the scorecard category keys, for the hook and worst-area text.
AREA_LABEL = {
    "security": "security headers", "tls": "TLS/certificate",
    "dns_email": "email authentication", "seo": "SEO", "performance": "performance",
    "accessibility": "accessibility", "links": "link health",
    "readability": "readability", "privacy": "privacy/tracking", "design": "design",
}


def read_domains(source=None, cli_domains=None):
    """Domains to score: the CLI list if given, else the file `source`, else the
    default prospect file. Blank lines and # comments are ignored."""
    if cli_domains:
        return [common.normalize_url(d) for d in cli_domains]
    path = Path(source) if source else default_prospects_path()
    if not path or not path.is_file():
        return []
    domains = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.append(common.normalize_url(line))
    return domains


def default_prospects_path():
    """sales/prospects.txt if present, else PROSPECTS.txt at the repo root."""
    root = common.repo_root()
    for candidate in (root / "sales" / "prospects.txt", root / "PROSPECTS.txt"):
        if candidate.is_file():
            return candidate
    return None


def _check(result, scope_key, check_name, where):
    """A single check dict from a scan result, or {} if absent. `where` is
    'host' for host_scans or 'page' for the first page scan."""
    if where == "host":
        scan = (result.get("host_scans") or {}).get(scope_key) or {}
    else:
        pages = result.get("page_scans") or []
        scan = (pages[0].get(scope_key) if pages else {}) or {}
    return (scan.get("checks") or {}).get(check_name) or {}


def _band(result, category):
    cats = (result.get("scorecard") or {}).get("categories") or {}
    return (cats.get(category) or {}).get("band")


def worst_category(result):
    """The lowest-scoring measured category and its band, or (None, None)."""
    cats = (result.get("scorecard") or {}).get("categories") or {}
    scored = [(name, g) for name, g in cats.items() if g.get("score") is not None]
    if not scored:
        return None, None
    name, g = min(scored, key=lambda kv: (kv[1]["score"], kv[0]))
    return name, g.get("band")


def pick_hook(result):
    """The single most compelling measured door-opener, by a fixed priority so
    the cold open is both specific and true. Returns a short phrase."""
    https_redirect = _check(result, "http_security", "https_redirect", "host")
    if https_redirect.get("verdict") == "fail":
        return "Homepage served over plain HTTP with no redirect to HTTPS"

    expiry = _check(result, "tls", "expiry", "host")
    if expiry.get("verdict") in ("warn", "fail"):
        return f"TLS certificate issue: {expiry.get('note', 'see certificate')}"

    trackers = _check(result, "privacy", "known_trackers", "page")
    consent = _check(result, "privacy", "cookie_consent", "page")
    if trackers.get("verdict") == "warn" and consent.get("verdict") == "warn":
        return "Analytics/trackers fire with no consent mechanism (GDPR/CCPA exposure)"

    for check in ("hsts", "content_security_policy", "clickjacking"):
        if _check(result, "http_security", check, "host").get("verdict") == "fail":
            return "Missing baseline security headers (HSTS/CSP/clickjacking)"

    if _band(result, "performance") in ("Poor", "Weak"):
        weight = _check(result, "performance", "static_weight", "page").get("note", "")
        return "Slow homepage" + (f": {weight}" if weight else "")

    if _band(result, "accessibility") in ("Poor", "Weak"):
        return "Accessibility gaps on the homepage (legal/ADA exposure)"

    if _check(result, "seo", "headings", "page").get("verdict") == "fail":
        return "Homepage has no H1 heading (SEO gap)"
    if _check(result, "seo", "meta_description", "page").get("verdict") == "fail":
        return "Homepage has no meta description (SEO gap)"

    name, band = worst_category(result)
    if name:
        return f"Weakest measured area: {AREA_LABEL.get(name, name)} ({band})"
    return "No clear single hook; run a full review"


def score_site(url, run=None):
    """Reduce a homepage scan to one triage row. An unreachable or crashing
    domain yields a reachable=False row (itself a prospect signal) instead of
    aborting the batch. `run` is injectable for tests."""
    run = run or (lambda target: scan_site.run(target, []))
    domain = common.host_of(url)
    try:
        result = run(url)
    except Exception as e:  # a dead site must not kill the sweep
        return {"domain": domain, "reachable": False, "band": "Unreachable",
                "score": None, "worst_area": "", "fails": None, "warns": None,
                "hook": f"Site did not respond ({type(e).__name__})"}
    overall = (result.get("scorecard") or {}).get("overall") or {}
    totals = result.get("totals") or {}
    worst_name, worst_band = worst_category(result)
    worst_area = ""
    if worst_name:
        worst_area = f"{AREA_LABEL.get(worst_name, worst_name)} ({worst_band})"
    return {
        "domain": domain,
        "reachable": True,
        "band": overall.get("band", "Not measured"),
        "score": overall.get("score"),
        "worst_area": worst_area,
        "fails": totals.get("fail", 0),
        "warns": totals.get("warn", 0),
        "hook": pick_hook(result),
    }


def rank(rows):
    """Reachable sites worst-first (lowest score = hottest prospect); a missing
    score sorts as worst. Unreachable sites sink to the bottom. Deterministic
    tie-break by domain."""
    def key(r):
        reachable = 0 if r["reachable"] else 1
        score = r["score"] if r["score"] is not None else -1.0
        return (reachable, score, r["domain"])
    ordered = sorted(rows, key=key)
    for i, r in enumerate(ordered, start=1):
        r["rank"] = i
    return ordered


def _row_for_output(r):
    return {
        "rank": r["rank"], "domain": r["domain"], "band": r["band"],
        "score": "" if r["score"] is None else f"{r['score']:.2f}",
        "worst_area": r["worst_area"],
        "fails": "" if r["fails"] is None else r["fails"],
        "warns": "" if r["warns"] is None else r["warns"],
        "hook": r["hook"],
    }


def write_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(_row_for_output(r))
    return path


def write_markdown(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Prospect triage (worst posture first = hottest prospect)", "",
             "| # | Domain | Posture | Score | Weakest area | Fails | Warns | Door-opener |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        o = _row_for_output(r)
        lines.append(f"| {o['rank']} | {o['domain']} | {o['band']} | {o['score']} "
                     f"| {o['worst_area']} | {o['fails']} | {o['warns']} | {o['hook']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def triage(domains, delay=INTER_DOMAIN_DELAY, run=None, progress=None):
    """Score every domain serially with a polite delay, then rank."""
    rows = []
    for i, url in enumerate(domains):
        if i:
            time.sleep(delay)
        row = score_site(url, run=run)
        rows.append(row)
        if progress:
            progress(row)
    return rank(rows)


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    delay = INTER_DOMAIN_DELAY
    source = None
    if "--delay" in args:
        idx = args.index("--delay")
        try:
            delay = float(args[idx + 1])
            del args[idx:idx + 2]
        except (IndexError, ValueError):
            print("Usage: python triage.py [domains...] [--file list.txt] [--delay S]")
            sys.exit(1)
    if "--file" in args:
        idx = args.index("--file")
        try:
            source = args[idx + 1]
            del args[idx:idx + 2]
        except IndexError:
            print("Usage: python triage.py [domains...] [--file list.txt] [--delay S]")
            sys.exit(1)

    domains = read_domains(source=source, cli_domains=args or None)
    if not domains:
        print("No domains to score. Put one URL per line in sales/prospects.txt, "
              "pass a --file, or list domains on the command line.")
        sys.exit(1)

    print(f"Triaging {len(domains)} site(s), homepage-only, serial "
          f"({delay}s between sites)...\n")

    def show(row):
        mark = row["band"] if row["reachable"] else "unreachable"
        print(f"  scored {row['domain']:32s} {mark}")

    rows = triage(domains, delay=delay, progress=show)

    out_dir = common.repo_root() / "sales"
    csv_path = write_csv(rows, out_dir / "triage_results.csv")
    md_path = write_markdown(rows, out_dir / "triage_results.md")

    print("\nRanked prospects (worst posture first = hottest lead):\n")
    print(f"  {'#':>2}  {'Domain':32s} {'Posture':12s} {'Score':>5s}  Door-opener")
    for r in rows:
        score = "  -  " if r["score"] is None else f"{r['score']:.2f}"
        print(f"  {r['rank']:>2}  {r['domain']:32s} {r['band']:12s} {score:>5s}  {r['hook']}")
    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
