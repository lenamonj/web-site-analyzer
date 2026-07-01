#!/usr/bin/env python3
"""
Orchestrator for the passive website evaluation tools.

Runs the host-level scans (HTTP security, TLS, DNS email-auth) once against the
primary target, and the page-level scans (SEO, accessibility, links, page
weight, readability) against the target plus any extra in-scope page URLs. Each
page is fetched and parsed once and that snapshot is shared across all page-level
scanners. Every scanner is wrapped so one failure cannot abort the run. Writes a
combined evidence JSON and a markdown digest under planning/_evidence, and prints
a compact console summary of every non-passing check plus a category scorecard.

Usage:
    python scan_site.py [url] [extra_page_url ...]
    # with no url, reads the first http line from TARGET.txt at the repo root
"""

import sys
import time
from pathlib import Path

import common
import htmlmeta
import registry


# Page-level scanners as (key, module, label), discovered from the central
# registry so adding a scanner never requires editing this orchestrator.
PAGE_SCANNERS = [(e.key, e.module, e.label) for e in registry.page_tools()]


def _safe_scan(fn, *args, tool_name="scan", **kwargs):
    """Run one scanner so a single failure cannot abort the whole review."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"tool": tool_name, "ok": False, "error": f"{type(e).__name__}: {e}"}


def _collect_issues(label, checks):
    """Pull every warn/fail from a checks dict into a flat, citable list."""
    issues = []
    for name, c in checks.items():
        verdict = c.get("verdict")
        if verdict in ("warn", "fail"):
            issues.append({"scan": label, "check": name, "verdict": verdict, "note": c.get("note", "")})
    return issues


def _dup_check(mapping, label, n_pages):
    if n_pages < 2:
        return {"verdict": "info", "note": f"Single page; cross-page {label} comparison not applicable."}
    dups = {value: urls for value, urls in mapping.items() if value and len(urls) >= 2}
    if dups:
        return {"verdict": "warn", "duplicates": {v: u for v, u in list(dups.items())[:5]},
                "note": f"{len(dups)} {label} value(s) repeat across pages; each page should have a unique {label}."}
    return {"verdict": "pass", "note": f"Each reviewed page has a distinct {label}."}


def check_cross_page(page_scans):
    """
    Cross-cutting checks no single-page scanner can make: the same title or meta
    description reused across multiple pages, which dilutes search relevance.
    """
    titles, descs = {}, {}
    for ps in page_scans:
        seo = ps.get("seo", {})
        if not seo.get("ok"):
            continue
        checks = seo.get("checks", {})
        t = ((checks.get("title") or {}).get("value") or "").strip()
        d = ((checks.get("meta_description") or {}).get("value") or "").strip()
        titles.setdefault(t, []).append(ps["url"])
        descs.setdefault(d, []).append(ps["url"])
    n = len(page_scans)
    return {
        "duplicate_titles": _dup_check(titles, "title", n),
        "duplicate_descriptions": _dup_check(descs, "meta description", n),
    }


def build_scorecard(host_scans, page_scans):
    """Roll the per-check verdicts up into one band per category plus an overall band.

    Both scopes bucket by the tool's category, and buckets merge, so any number
    of tools can share a scorecard category (scan_crawl and scan_seo both roll
    into "seo"). Host categories always appear (Not measured when empty); a
    page category appears once any page produced verdicts for it.
    """
    cats = {}
    for e in registry.host_tools():
        cats.setdefault(e.category, []).extend(common.verdicts_of(host_scans.get(e.key)))
    for e in registry.page_tools():
        acc = []
        for ps in page_scans:
            sr = ps.get(e.key)
            if sr and sr.get("ok"):
                acc += common.verdicts_of(sr)
        if acc:
            cats.setdefault(e.category, []).extend(acc)
    categories = {name: common.grade(v) for name, v in cats.items()}
    overall = common.grade([v for lst in cats.values() for v in lst])
    return {"overall": overall, "categories": categories}


def run(target, extra_pages):
    target = common.normalize_url(target)
    host = common.host_of(target)
    slug = common.slug_of(target)

    host_scans = {
        e.key: _safe_scan(e.module.scan, target, tool_name=e.tool_id)
        for e in registry.host_tools()
    }

    page_urls = [target] + [common.normalize_url(u) for u in extra_pages]
    page_scans = []
    for url in page_urls:
        # Fetch and parse each page once, then share that snapshot with every
        # page-level scanner instead of each one re-fetching the same URL.
        ctx = _safe_scan(htmlmeta.fetch_page, url, tool_name="fetch_page")
        entry = {"url": url}
        for key, module, _ in PAGE_SCANNERS:
            page_arg = ctx if isinstance(ctx, dict) and "res" in ctx else None
            entry[key] = _safe_scan(module.scan, url, page=page_arg, tool_name=f"scan_{key}")
        page_scans.append(entry)

    issues = []
    for e in registry.host_tools():
        sr = host_scans[e.key]
        if "checks" in sr:
            issues += _collect_issues(e.label, sr["checks"])
        elif sr.get("verdict") in ("warn", "fail"):
            # A host scanner that could not produce checks but still graded itself
            # (for example a failed TLS handshake) contributes one issue.
            issues.append({"scan": e.label, "check": "handshake", "verdict": sr["verdict"],
                           "note": sr.get("note", "")})
    for ps in page_scans:
        for key, _, label in PAGE_SCANNERS:
            if ps[key].get("ok"):
                issues += _collect_issues(f"{label}:{ps['url']}", ps[key].get("checks", {}))

    cross_page = check_cross_page(page_scans)
    for c in cross_page.values():
        if c["verdict"] in ("warn", "fail"):
            issues.append({"scan": "cross_page", "check": "", "verdict": c["verdict"], "note": c["note"]})

    fails = [i for i in issues if i["verdict"] == "fail"]
    warns = [i for i in issues if i["verdict"] == "warn"]

    return {
        "tool": "scan_site",
        "target": target,
        "host": host,
        "slug": slug,
        "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pages_scanned": page_urls,
        "totals": {"fail": len(fails), "warn": len(warns)},
        "scorecard": build_scorecard(host_scans, page_scans),
        "cross_page": cross_page,
        "host_scans": host_scans,
        "page_scans": page_scans,
        "issues": {"fail": fails, "warn": warns},
    }


def write_digest_md(result, path):
    lines = [f"# Passive scan digest: {result['host']}", "",
             f"- Target: {result['target']}",
             f"- Measured (UTC): {result['measured_at_utc']}",
             f"- Pages scanned: {len(result['pages_scanned'])}",
             f"- Failing checks: {result['totals']['fail']}  |  Warnings: {result['totals']['warn']}",
             ""]
    sc = result.get("scorecard", {})
    if sc:
        o = sc["overall"]
        lines.append(f"## Scorecard (overall: {o['band']})")
        lines.append("")
        lines.append("| Category | Band | Checks (pass/warn/fail) |")
        lines.append("| --- | --- | --- |")
        for name, g in sc["categories"].items():
            lines.append(f"| {name} | {g['band']} | {g['pass']}/{g['warn']}/{g['fail']} |")
        lines.append("")
    lines += ["## Failing checks", ""]
    if result["issues"]["fail"]:
        for i in result["issues"]["fail"]:
            lines.append(f"- [{i['scan']}] {i['check']}: {i['note']}")
    else:
        lines.append("- None.")
    lines += ["", "## Warnings", ""]
    if result["issues"]["warn"]:
        for i in result["issues"]["warn"]:
            lines.append(f"- [{i['scan']}] {i['check']}: {i['note']}")
    else:
        lines.append("- None.")
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    if args and ("." in args[0] or args[0].lower().startswith("http")):
        target, extra = args[0], args[1:]
    else:
        target, extra = common.read_target_file(), args
    if not target:
        print("No target given and no http line found in TARGET.txt")
        sys.exit(1)

    result = run(target, extra)

    out_dir = common.evidence_dir()
    json_path = out_dir / f"{result['slug']}_scan.json"
    md_path = out_dir / f"{result['slug']}_scan_summary.md"
    common.write_json(json_path, result)
    write_digest_md(result, md_path)

    print(f"Target: {result['target']}")
    print(f"Pages scanned: {len(result['pages_scanned'])}")
    print(f"Failing checks: {result['totals']['fail']} | Warnings: {result['totals']['warn']}")
    sc = result.get("scorecard", {})
    if sc:
        print(f"\nScorecard (overall: {sc['overall']['band']}):")
        for name, g in sc["categories"].items():
            score = "n/a" if g["score"] is None else f"{g['score']:.2f}"
            print(f"  {name:14s} {g['band']:10s} pass/warn/fail = {g['pass']}/{g['warn']}/{g['fail']}  ({score})")
    if result["issues"]["fail"]:
        print("\nFAIL:")
        for i in result["issues"]["fail"]:
            print(f"  [{i['scan']}] {i['check']}: {i['note']}")
    if result["issues"]["warn"]:
        print("\nWARN:")
        for i in result["issues"]["warn"]:
            print(f"  [{i['scan']}] {i['check']}: {i['note']}")
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
