# Quarterly Trend Layer - Design

Date: 2026-07-02
Status: Approved design, pending implementation plan

## Purpose

Turn the one-off website review into a recurring quarterly deliverable. A
retained client receives the same Executive Report four times a year, and
when history exists the report opens with a "Progress This Quarter" section
showing how every measured data point has moved over time. The layer is
thin: it enriches artifacts the pipeline already produces and adds one
section to the report the builder already owns.

## Decisions made during brainstorming

- Deliverable: the existing `planning/<slug>_Executive_Report.docx` gains a
  trend section. No second document.
- Data points: per-category numeric scores plus site-level rollups of page
  metrics (LCP, CLS, TBT, page weight, reading ease, broken links, mixed
  content, third-party origins, known trackers).
- Visuals: matplotlib chart PNGs embedded via the builder's existing image
  pipeline, plus a quarter-over-quarter scorecard table and a named
  new/resolved findings summary.
- History home: stays at `planning/_evidence/<slug>_history.jsonl`,
  gitignored. Known risk, accepted: this file is irreplaceable business
  data that exists only on local disk. Backup is an operational habit
  (sync the folder), not code.
- Run hygiene: every run appends to the ledger; the trend layer uses the
  latest run in each calendar quarter as that quarter's data point, so
  ad-hoc runs never pollute the chart.
- Cadence: manual. The operator runs `/review-site` per client when a
  quarter closes. No scheduler.
- Approach: enrich the ledger, add a trend module, extend the builder, and
  archive each run's full scan JSON as backfill insurance.

## Architecture

Three touch points in the existing pipeline plus one new module. The
pipeline's grain is preserved: scanners measure, the draft step distills,
the builder owns formatting.

```
scan_site.py        history_entry() gains a metrics block; run also
                    archives the scan JSON
trends.py (new)     ledger -> quarterly points -> trend block
draft_report_data.py  folds the trend block into the draft data
build_exec_report.py  renders "Progress This Quarter" (table, charts,
                    findings movement)
```

## Component 1: Ledger metrics block (scan_site.py)

`history_entry()` adds a `metrics` object to every ledger line:

```json
"metrics": {
  "scores": {"overall": 0.88, "security": 0.92, "tls": 1.0},
  "pages": {
    "median_lcp_ms": 2100, "median_cls": 0.02, "median_tbt_ms": 180,
    "median_weight_kb": 2410, "max_weight_kb": 4139,
    "median_reading_ease": 27.3,
    "broken_links": 3, "links_checked": 62,
    "mixed_content": 0, "third_party_origins": 14, "known_trackers": 2
  },
  "vitals_captured": true
}
```

- `scores` copies the numeric category scores and overall score from the
  scorecard the scan already computes.
- `pages` rolls page-level measurements up to site level. Medians for
  continuous metrics because the reviewed page set can drift between
  quarters; a median holds steady when one page is added or removed.
  Counts (broken links, trackers, mixed content) are site-level sums.
  Sampled metrics store their denominator (`links_checked`) alongside the
  count so a bigger sample is never read as a regression.
- Metrics that were not captured that run (for example vitals with no
  browser installed) are `null`, and `vitals_captured` is `false`. Null
  means gap, never zero.
- Exact source fields per metric (`lcp_ms`, `cls`, `tbt_ms`, static weight
  KB, `flesch_reading_ease`, links `broken`/`checked`,
  `third_party_count`, `known_trackers`) are pinned during implementation
  from the scanner sources.
- Ledger lines from before this change remain valid; readers treat a
  missing `metrics` key as all-gaps.

## Component 2: Scan archive (scan_site.py)

After writing `<slug>_scan.json`, the run copies it to
`planning/_evidence/archive/<slug>_scan_<YYYYMMDD>T<HHMMSS>Z.json`.
Gitignored via a new `planning/_evidence/archive/` rule. The archive is
never read by the trend layer; it exists so a metric not captured in the
ledger schema today can be backfilled later. Same-second collisions are
not a concern at quarterly cadence; the timestamp comes from
`measured_at_utc`.

## Component 3: Trend module (tools/trends.py, new)

Pure stdlib, like the rest of the scanner suite. One job: ledger in,
report-ready trend block out.

- **Quarter selection.** Group ledger entries by calendar quarter of
  `measured_at_utc` (UTC). Keep the latest entry per quarter. That entry
  is the quarter's data point.
- **Output.** A `trend` block:

```json
"trend": {
  "quarters": ["2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"],
  "series": {
    "overall_score": [0.71, 0.78, 0.84, 0.88],
    "security_score": [0.75, 0.79, 0.9, 0.92],
    "median_lcp_ms": [3400, null, 2600, 2100],
    "median_weight_kb": [3100, 2900, 2500, 2410],
    "broken_links": [9, 7, 4, 3]
  },
  "latest_delta": {
    "scorecard": [
      {"category": "security", "prev_band": "Adequate", "band": "Strong",
       "prev_score": 0.79, "score": 0.92, "direction": "improved"}
    ],
    "new_findings": 2, "resolved_findings": 5,
    "resolved_examples": ["..."],
    "pages_scanned": {"prev": 15, "current": 15}
  }
}
```

- `latest_delta` compares the current quarter's point against the previous
  quarter's point (not the last ad-hoc run), reusing the existing
  `diff_issues()` machinery for new/resolved findings.
- With fewer than two quarterly points the block is omitted entirely.
- Standalone CLI: `python trends.py <slug>` prints the series for a client
  without running a scan.

## Component 4: Draft integration (draft_report_data.py)

The draft step calls `trends.py` and writes the trend block into the draft
data's existing `progress` area. `run_review.py` gains no new steps; the
layer rides the pipeline as-is.

## Component 5: Report section (build_exec_report.py)

A "Progress This Quarter" section rendered from the trend block, placed
immediately after the executive summary. Three elements in order:

1. **QoQ scorecard table.** One row per category: prior band, current
   band, score change, direction (improved / held / declined). Table
   footer states pages reviewed per quarter so a median shift from
   page-set drift is never mistaken for a site change.
2. **Trend charts.** Matplotlib PNGs written to
   `planning/_evidence/rendered/` and embedded via the existing image
   pipeline. Few and CEO-legible: overall score by quarter, category
   scores as a compact multi-series, and up to three page-metric charts
   (LCP, page weight, broken links) only where data exists. Charts use
   the report's design system (palette, typography) so the section reads
   as one document. Null quarters render as visible line gaps, never
   interpolated. The dataviz skill governs chart construction at
   implementation time.
3. **Findings movement.** "N resolved this quarter, M new" with resolved
   items named in full. No truncation: resolved findings are the value
   story of the retainer.

matplotlib is a documented dependency of the builder only; the scanner
suite stays pure stdlib. If matplotlib is not importable the build fails
with an explicit message rather than shipping a chartless client
deliverable.

## Suppression ladder

The product degrades by withholding, never by guessing:

| History | Rendered |
|---|---|
| 1 quarter | No trend section; report identical to today |
| 2 quarters | Table and findings movement; no charts |
| 3+ quarters | Full section |
| Metric null in some quarters | Gap in that chart |
| Metric null in all quarters | That chart skipped |

A two-point line chart implies a slope one interval cannot support, hence
charts start at three points; the delta table carries the QoQ story until
then.

## Error handling

- Malformed ledger lines are already skipped by `read_history()`;
  unchanged.
- Missing `metrics` on old lines: contribute bands to the table, gaps to
  score charts.
- Missing matplotlib: explicit build failure with an install message.
- Archive write failure: fail the run loudly (the archive is business
  data, not best-effort).

## Testing

Extends both existing offline suites; all fixture-driven, no network.

- `tools/test_review_tools.py`: metrics extraction from a fixture scan
  result including null vitals; latest-per-quarter selection including two
  runs in one quarter; series gap handling; pre-metrics ledger line
  compatibility; archive file naming.
- `test_exec_report.py`: trend section renders expected headings, table
  rows, and images from a fixture trend block; suppression at zero, one,
  and two quarters; chart PNGs exist and are non-trivially sized.

## Documentation

Brief updates to SKILL.md and the project CLAUDE.md describing the trend
section, the archive directory, and the latest-per-quarter rule. The
gitignore gains `planning/_evidence/archive/`.

## Out of scope

- Scheduling or reminders (manual quarterly runs).
- A separate trend document.
- Per-check trend matrices.
- Any change to scanner measurement behavior.
