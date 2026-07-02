#!/usr/bin/env python3
"""
Quarterly trend series from a findings-history ledger.

Reads the per-site history ledger (one JSON line per scan run, written by
scan_site.py), reduces it to one data point per calendar quarter (the latest
run in each quarter, so ad-hoc mid-quarter runs never pollute the trend),
and emits the report-ready trend block: per-quarter series for every ledger
metric plus a quarter-over-quarter delta with named resolved findings. Pure
standard library. Design: docs/superpowers/specs/
2026-07-02-quarterly-trend-layer-design.md.

Usage:
    python trends.py <slug>
    # reads planning/_evidence/<slug>_history.jsonl and prints the trend JSON
"""

import sys

import common
import scan_site

PAGE_METRICS = ["median_lcp_ms", "median_cls", "median_tbt_ms",
                "median_weight_kb", "max_weight_kb", "median_reading_ease",
                "broken_links", "links_checked", "mixed_content",
                "third_party_origins", "known_trackers"]

# Posture bands in improving order, for direction when a score is missing.
BAND_RANK = {"Poor": 0, "Weak": 1, "Adequate": 2, "Strong": 3}


def quarter_of(ts):
    """'2026-07-02T15:37:23Z' -> '2026-Q3'; None when unparseable."""
    try:
        year, month = int(ts[0:4]), int(ts[5:7])
    except (TypeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None
    return f"{year}-Q{(month - 1) // 3 + 1}"


def quarterly_points(entries):
    """One (quarter, entry) pair per quarter, oldest quarter first. Within a
    quarter the entry with the greatest measured_at_utc wins (ISO 8601
    timestamps compare lexicographically; a missing stamp sorts as ""), so a
    backfilled ledger line appended out of chronological order can never
    shadow a later run just by coming after it in the file."""
    by_quarter = {}
    for e in entries:
        q = quarter_of(e.get("measured_at_utc"))
        if not q:
            continue
        ts = e.get("measured_at_utc") or ""
        winner = by_quarter.get(q)
        if winner is None or ts >= (winner.get("measured_at_utc") or ""):
            by_quarter[q] = e
    return sorted(by_quarter.items())


def _score(entry, name):
    return ((entry.get("metrics") or {}).get("scores") or {}).get(name)


def _page_metric(entry, name):
    return ((entry.get("metrics") or {}).get("pages") or {}).get(name)


def _series(points):
    """Aligned per-quarter value lists. Score series always ship (they are
    the headline); a page metric ships only if some quarter measured it."""
    cats = []
    for _, e in points:
        for name in ((e.get("metrics") or {}).get("scores") or {}):
            if name != "overall" and name not in cats:
                cats.append(name)
    series = {"overall_score": [_score(e, "overall") for _, e in points]}
    for name in cats:
        series[f"{name}_score"] = [_score(e, name) for _, e in points]
    for m in PAGE_METRICS:
        vals = [_page_metric(e, m) for _, e in points]
        if any(v is not None for v in vals):
            series[m] = vals
    return series


def _issue_name(issue):
    check = issue.get("check") or ""
    note = (issue.get("note") or "").strip()
    body = f"{check}: {note}" if check and note else (check or note)
    return f"[{issue.get('scan', '')}] {body}".strip()


def _delta_rows(prev, curr):
    prev_bands = prev.get("bands") or {}
    curr_bands = curr.get("bands") or {}
    rows = []
    for name in curr_bands:
        if name == "overall":
            continue
        p, c = _score(prev, name), _score(curr, name)
        prev_band, band = prev_bands.get(name), curr_bands.get(name)
        if isinstance(p, (int, float)) and isinstance(c, (int, float)) and p != c:
            direction = "improved" if c > p else "declined"
        else:
            prev_rank, rank = BAND_RANK.get(prev_band), BAND_RANK.get(band)
            if prev_rank is not None and rank is not None and prev_rank != rank:
                direction = "improved" if rank > prev_rank else "declined"
            else:
                direction = "held"
        rows.append({"category": name,
                     "prev_band": prev_band,
                     "band": band,
                     "prev_score": p, "score": c, "direction": direction})
    # A category scored last quarter but absent this quarter (retired check,
    # or simply not yet measured) still belongs in the scorecard rather than
    # silently disappearing; it reads as held with no current band.
    for name in prev_bands:
        if name == "overall" or name in curr_bands:
            continue
        rows.append({"category": name,
                     "prev_band": prev_bands.get(name),
                     "band": None,
                     "prev_score": _score(prev, name), "score": _score(curr, name),
                     "direction": "held"})
    return rows


def build_trend(entries):
    """The report-ready trend block, or None with fewer than two quarterly
    points (a single point has no trend to show)."""
    points = quarterly_points(entries)
    if len(points) < 2:
        return None
    quarters = [q for q, _ in points]
    prev, curr = points[-2][1], points[-1][1]
    diff = scan_site.diff_issues(prev, curr)
    return {
        "quarters": quarters,
        "series": _series(points),
        "latest_delta": {
            "prev_quarter": quarters[-2],
            "quarter": quarters[-1],
            "scorecard": _delta_rows(prev, curr),
            "new_findings": len(diff["new"]),
            "resolved_findings": len(diff["resolved"]),
            "resolved_examples": [_issue_name(i) for i in diff["resolved"]],
            "pages_scanned": {"prev": prev.get("pages_scanned"),
                              "current": curr.get("pages_scanned")},
        },
    }


def trend_from_ledger(history_path):
    return build_trend(scan_site.read_history(history_path))


def main():
    common.enable_utf8_stdout()
    if len(sys.argv) != 2:
        print("Usage: python trends.py <slug>")
        sys.exit(1)
    path = common.evidence_dir() / f"{sys.argv[1]}_history.jsonl"
    if not path.exists():
        print(f"No ledger at {path}")
        sys.exit(1)
    trend = trend_from_ledger(path)
    if trend is None:
        print("Fewer than two quarterly data points; no trend yet.")
        sys.exit(0)
    common.print_json(trend)


if __name__ == "__main__":
    main()
