#!/usr/bin/env python3
"""
One-command evidence pipeline: discover -> scan -> draft.

Composes the registered tools into a single run (see PLAN.md section 10): it
proposes an in-scope page set with discover_pages, scans the whole set with
scan_site, writes the scan JSON and markdown digest, and drafts
<slug>_exec_report_data.draft.json for the executive report. Judgement steps
(gameplan authoring, severity review, recommendations, the final docx) stay
with the reviewer per SKILL.md. This is not a scanner and is not registered.

Usage:
    python run_review.py [url]
    # with no url, reads the first http line from TARGET.txt at the repo root
"""

import sys
from pathlib import Path

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


def pipeline(target, out_dir=None, crawl_pages=None, fresh_crawl=False):
    """Run discover (or an opt-in crawl) -> scan -> draft and write all
    artifacts. Returns the paths. crawl_pages switches page discovery to the
    polite crawler (PLAN.md section 29) with that page budget."""
    target = common.normalize_url(target)
    out_dir = Path(out_dir) if out_dir else common.evidence_dir()

    # Enable the per-run fetch cache for the whole pipeline so discovery's
    # (or the crawl's) page fetches are reused by the scan (scan_site.run
    # keeps existing entries and disables the cache when it finishes).
    common.enable_fetch_cache()
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
    finally:
        common.disable_fetch_cache()
    slug = result["slug"]
    json_path = out_dir / f"{slug}_scan.json"
    md_path = out_dir / f"{slug}_scan_summary.md"
    history_path = out_dir / f"{slug}_history.jsonl"
    scan_site.attach_delta(result, json_path, history_path)
    common.write_json(json_path, result)
    scan_site.append_history(result, history_path)
    scan_site.write_digest_md(result, md_path,
                              history=scan_site.read_history(history_path))

    draft_path = out_dir / f"{slug}_exec_report_data.draft.json"
    common.write_json(draft_path, draft_report_data.draft(result))

    return {"scan": result, "discovery": disco,
            "json_path": json_path, "digest_path": md_path, "draft_path": draft_path}


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    crawl_pages, fresh = None, False
    if "--fresh" in args:
        fresh = True
        args.remove("--fresh")
    if "--crawl" in args:
        idx = args.index("--crawl")
        try:
            crawl_pages = int(args[idx + 1])
            del args[idx:idx + 2]
        except (IndexError, ValueError):
            print("Usage: python run_review.py [url] [--crawl N] [--fresh]")
            sys.exit(1)
    target = args[0] if args else common.read_target_file()
    if not target:
        print("No target given and no http line found in TARGET.txt")
        sys.exit(1)

    out = pipeline(target, crawl_pages=crawl_pages, fresh_crawl=fresh)
    result = out["scan"]

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
