#!/usr/bin/env python3
"""
One-command evidence pipeline: discover -> scan -> draft.

Composes the registered tools into a single run (see PLAN.md section 10): it
proposes an in-scope page set with discover_pages, scans the whole set with
scan_site, writes the scan JSON and markdown digest, and drafts
<slug>_exec_report_data.draft.json for the executive report. Judgement steps
(severity review, recommendations, narrative, the final docx) stay
with the reviewer per SKILL.md. This is not a scanner and is not registered.

Usage:
    python run_review.py [url]
    # with no url, reads the first http line from TARGET.txt at the repo root
"""

import sys
from pathlib import Path

import capture_rendered
import common
import crawler
import discover_pages
import draft_report_data
import scan_site


def choose_pages(target, disco):
    """Extra page URLs to scan beyond the target, from a discovery result.

    The target is always scanned first by scan_site, so it (and the resolved
    homepage, which may differ only by a redirect) is excluded here.
    """
    if disco.get("ok") is False:
        return []
    skip = {target, disco.get("homepage")}
    return [u for u in disco.get("proposed_review_set", []) if u not in skip]


def capture_and_rescan(result, target, extra):
    """The automated rendered-evidence step (PLAN.md section 34): capture DOM
    snapshots and browser metrics when a browser is installed, then re-scan so
    the scanners consume them in the same run. Returns the capture summary
    (with the fresh scan under "scan" when a re-scan happened), or an honest
    note when no browser exists or there is nothing to capture."""
    browser = capture_rendered.find_browser()
    if not browser:
        return {"ok": False, "captured": [],
                "note": "no Chrome or Edge found (set REVIEW_BROWSER to override); "
                        "rendered evidence not captured this run"}
    plan = capture_rendered.plan_from_scan(result)
    if not plan["pages"]:
        return {"ok": True, "captured": [], "note": "nothing to capture"}
    summary = capture_rendered.capture_pages(result["slug"], plan, browser=browser)
    if summary.get("captured"):
        summary["scan"] = scan_site.run(target, extra)
        summary["rescanned"] = True
    return summary


def pipeline(target, out_dir=None, crawl_pages=None, fresh_crawl=False, capture="auto"):
    """Run discover (or an opt-in crawl) -> scan -> capture rendered evidence
    (when a browser is installed) -> re-scan -> draft, and write all
    artifacts. Returns the paths. crawl_pages switches page discovery to the
    polite crawler (PLAN.md section 29) with that page budget; capture=False
    skips the browser step (PLAN.md section 34)."""
    target = common.normalize_url(target)
    out_dir = Path(out_dir) if out_dir else common.evidence_dir()

    # Enable the per-run fetch cache for the whole pipeline so discovery's
    # (or the crawl's) page fetches are reused by the scan and the post-capture
    # re-scan (scan_site.run keeps existing entries and this finally clears them).
    common.enable_fetch_cache()
    capture_summary = None
    try:
        if crawl_pages:
            state_path = out_dir / f"{common.slug_of(target)}_crawl_state.json"
            disco = crawler.crawl(target, max_pages=crawl_pages,
                                  state_path=state_path, fresh=fresh_crawl)
            extra = [u for u in disco.get("pages", []) if u != target]
        else:
            disco = discover_pages.discover(target)
            extra = choose_pages(target, disco)
        result = scan_site.run(target, extra)
        if capture:
            capture_summary = capture_and_rescan(result, target, extra)
            if capture_summary.get("rescanned"):
                result = capture_summary.pop("scan")
    finally:
        common.disable_fetch_cache()
    slug = result["slug"]
    paths = scan_site.write_run_outputs(result, out_dir)

    draft_path = out_dir / f"{slug}_exec_report_data.draft.json"
    common.write_json(draft_path, draft_report_data.draft(result))

    return {"scan": result, "discovery": disco, "capture": capture_summary,
            "json_path": paths["json_path"], "digest_path": paths["digest_path"],
            "draft_path": draft_path}


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    crawl_pages, fresh, capture = None, False, "auto"
    if "--fresh" in args:
        fresh = True
        args.remove("--fresh")
    if "--no-browser" in args:
        capture = False
        args.remove("--no-browser")
    if "--crawl" in args:
        idx = args.index("--crawl")
        try:
            crawl_pages = int(args[idx + 1])
            del args[idx:idx + 2]
        except (IndexError, ValueError):
            print("Usage: python run_review.py [url] [--crawl N] [--fresh] [--no-browser]")
            sys.exit(1)
    target = args[0] if args else common.read_target_file()
    if not target:
        print("No target given and no http line found in TARGET.txt")
        sys.exit(1)

    out = pipeline(target, crawl_pages=crawl_pages, fresh_crawl=fresh, capture=capture)
    result = out["scan"]

    cap = out.get("capture")
    if cap is not None:
        if cap.get("captured"):
            print(f"Rendered evidence captured for {len(cap['captured'])} page(s) "
                  "and consumed by a re-scan.")
        if cap.get("note"):
            print(f"Capture: {cap['note']}")
        for url in cap.get("dropped") or []:
            print(f"Capture dropped (over page cap): {url}")
        for url, problems in (cap.get("failed") or {}).items():
            print(f"Capture FAILED {url}: {'; '.join(problems)}")

    print(f"Target: {result['target']}")
    print(f"Pages scanned: {len(result['pages_scanned'])}")
    for u in result["pages_scanned"]:
        print(f"  {u}")
    print(f"Failing checks: {result['totals']['fail']} | Warnings: {result['totals']['warn']}")
    sc = result.get("scorecard", {})
    if sc:
        print(f"\nScorecard (overall: {sc['overall']['band']}):")
        for name, g in sc["categories"].items():
            score = "n/a" if g["score"] is None else f"{g['score']:.2f}"
            print(f"  {name:14s} {g['band']:10s} pass/warn/fail = {g['pass']}/{g['warn']}/{g['fail']}  ({score})")
    print(f"\nWrote {out['json_path']}")
    print(f"Wrote {out['digest_path']}")
    print(f"Wrote {out['draft_path']}")
    print("Draft report data is measured-only; recommendations and the narrative still need authoring.")


if __name__ == "__main__":
    main()
