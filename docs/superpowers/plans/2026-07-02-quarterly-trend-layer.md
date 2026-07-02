# Quarterly Trend Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each scan run records numeric metrics in the per-site history ledger and archives its full scan JSON; the executive report gains a "Progress this quarter" section with a quarter-over-quarter posture table, trend charts, and named resolved findings.

**Architecture:** Three touch points in the existing pipeline plus two new modules. `scan_site.py` enriches the ledger and archives scans through one shared write path used by both entry points. New `tools/trends.py` (pure stdlib) reduces the ledger to one point per calendar quarter and emits a report-ready trend block. New `report_charts.py` (matplotlib) renders the trend PNGs. `draft_report_data.py` folds the trend into the draft; `build_exec_report.py` renders the section.

**Tech Stack:** Python 3.13, standard library only under `tools/`, python-docx + matplotlib for the builder side only, `unittest` offline suites.

**Spec:** `docs/superpowers/specs/2026-07-02-quarterly-trend-layer-design.md`

## Global Constraints

- Everything under `.claude/skills/review-site/tools/` stays pure standard library. matplotlib may only be imported by `report_charts.py` at the skill root.
- All tests are offline and fixture-driven. No network, no reading real evidence files.
- Never use em dashes or en dashes in any code, comment, docstring, or report copy. No emojis.
- Null means "not measured". Never substitute 0 for a missing metric; charts show gaps, never interpolations.
- Comments explain non-obvious intent only; match the existing comment density and voice.
- Repo root is `C:\Users\lenam\projects\web-site-analyzer`. All paths below are repo-relative. Run commands with the Bash tool (POSIX syntax).
- Commit after each task and push (`git push`) per the user's standing git workflow. Commit messages end with the Co-Authored-By/Claude-Session trailer used in this session.
- The test suites are invoked as `python -m unittest <module>` from the directory containing the test file.

---

### Task 1: Ledger metrics block (`collect_metrics` in scan_site.py)

**Files:**
- Modify: `.claude/skills/review-site/tools/scan_site.py` (add `_median`, `_check`, `collect_metrics`; extend `history_entry` at line ~270)
- Test: `.claude/skills/review-site/tools/test_review_tools.py` (new class `TestTrendMetrics`)

**Interfaces:**
- Consumes: the scan result dict produced by `scan_site.run()` (keys `scorecard`, `page_scans`).
- Produces: `scan_site.collect_metrics(result) -> dict` with keys `scores` (dict of category name -> float score, plus `overall`), `pages` (dict with keys `median_lcp_ms`, `median_cls`, `median_tbt_ms`, `median_weight_kb`, `max_weight_kb`, `median_reading_ease`, `broken_links`, `links_checked`, `mixed_content`, `third_party_origins`, `known_trackers`; each numeric or None), `vitals_captured` (bool). Every ledger line written by `history_entry` now carries this under the `"metrics"` key. Task 3 reads `entry["metrics"]["scores"]` and `entry["metrics"]["pages"]`.

Source fields (verified against the scanner sources and real scan JSON):
- vitals: `page["vitals"]["captured"]` bool; numeric values at `page["vitals"]["checks"]["lcp"|"cls"|"tbt"]["value"]`
- weight: `page["performance"]["checks"]["static_weight"]["total_floor_kb"]`
- reading ease: `page["readability"]["checks"]["reading_ease"]["flesch_reading_ease"]` (absent on non-prose pages)
- links: `page["links"]["checks"]["link_health"]["checked"]` and `["counts"]["broken"]`; `page["links"]["checks"]["mixed_content"]["count"]`
- privacy: `page["privacy"]["checks"]["third_party_origins"]["domains"]` (list); `page["privacy"]["checks"]["known_trackers"]["trackers"]` (dict)

- [ ] **Step 1: Write the failing tests**

Add to `.claude/skills/review-site/tools/test_review_tools.py` (append near `TestFindingsHistory`; `site` is already imported):

```python
class TestTrendMetrics(unittest.TestCase):
    def _page(self, lcp=2000, weight=1500.0, ease=55.0, broken=1, checked=10,
              mixed=0, domains=("a.example",), trackers=(), captured=True):
        vit = {"captured": captured, "checks": {}}
        if captured:
            vit["checks"] = {"lcp": {"value": lcp, "verdict": "pass"},
                             "cls": {"value": 0.05, "verdict": "pass"},
                             "tbt": {"value": 100, "verdict": "pass"}}
        return {
            "url": "https://acme.example/",
            "vitals": vit,
            "performance": {"ok": True, "checks": {"static_weight": {
                "total_floor_kb": weight, "verdict": "pass"}}},
            "readability": {"ok": True, "checks": {"reading_ease": {
                "flesch_reading_ease": ease, "verdict": "pass"}}},
            "links": {"ok": True, "checks": {
                "link_health": {"checked": checked, "counts": {"broken": broken}},
                "mixed_content": {"count": mixed}}},
            "privacy": {"ok": True, "checks": {
                "third_party_origins": {"domains": list(domains)},
                "known_trackers": {"trackers": {t: 1 for t in trackers}}}},
        }

    def _result(self, pages):
        return {"scorecard": {"overall": {"score": 0.8, "band": "Strong"},
                              "categories": {"seo": {"score": 0.9, "band": "Strong"}}},
                "page_scans": pages}

    def test_metrics_rollup_medians_and_counts(self):
        m = site.collect_metrics(self._result([
            self._page(lcp=1000, weight=100.0, ease=40.0, broken=1, checked=10,
                       domains=("a.example",), trackers=("t.example",)),
            self._page(lcp=3000, weight=300.0, ease=60.0, broken=2, checked=20,
                       domains=("a.example", "b.example")),
            self._page(lcp=2000, weight=200.0, ease=50.0, broken=0, checked=5,
                       mixed=2),
        ]))
        self.assertEqual(m["scores"], {"overall": 0.8, "seo": 0.9})
        self.assertEqual(m["pages"]["median_lcp_ms"], 2000)
        self.assertEqual(m["pages"]["median_weight_kb"], 200.0)
        self.assertEqual(m["pages"]["max_weight_kb"], 300.0)
        self.assertEqual(m["pages"]["median_reading_ease"], 50.0)
        self.assertEqual(m["pages"]["broken_links"], 3)
        self.assertEqual(m["pages"]["links_checked"], 35)
        self.assertEqual(m["pages"]["mixed_content"], 2)
        self.assertEqual(m["pages"]["third_party_origins"], 2)
        self.assertEqual(m["pages"]["known_trackers"], 1)
        self.assertTrue(m["vitals_captured"])

    def test_even_page_count_uses_midpoint_median(self):
        m = site.collect_metrics(self._result(
            [self._page(lcp=1000), self._page(lcp=3000)]))
        self.assertEqual(m["pages"]["median_lcp_ms"], 2000)

    def test_uncaptured_vitals_are_gaps_not_zeros(self):
        m = site.collect_metrics(self._result([self._page(captured=False)]))
        self.assertIsNone(m["pages"]["median_lcp_ms"])
        self.assertIsNone(m["pages"]["median_cls"])
        self.assertFalse(m["vitals_captured"])

    def test_missing_page_scans_yield_all_gaps(self):
        m = site.collect_metrics({"scorecard": {}})
        self.assertIsNone(m["pages"]["median_weight_kb"])
        self.assertIsNone(m["pages"]["broken_links"])
        self.assertIsNone(m["pages"]["third_party_origins"])
        self.assertEqual(m["scores"], {"overall": None})
        self.assertFalse(m["vitals_captured"])

    def test_history_entry_carries_metrics(self):
        e = site.history_entry(TestFindingsHistory.RESULT)
        self.assertIn("metrics", e)
        self.assertEqual(e["metrics"]["scores"]["overall"], 0.7)
        self.assertEqual(e["metrics"]["scores"]["seo"], 0.88)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools.TestTrendMetrics -v`
Expected: FAIL / ERROR with `AttributeError: module 'scan_site' has no attribute 'collect_metrics'` (and the `history_entry` test failing on the missing `metrics` key).

- [ ] **Step 3: Implement `collect_metrics` and extend `history_entry`**

In `.claude/skills/review-site/tools/scan_site.py`, insert directly above `def history_entry(result):`:

```python
def _median(values):
    """Median of the numeric values present; None when none are."""
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    n, mid = len(vals), len(vals) // 2
    if n % 2:
        return vals[mid]
    return round((vals[mid - 1] + vals[mid]) / 2, 3)


def _page_check(ps, tool_key, check_name):
    return ((ps.get(tool_key) or {}).get("checks") or {}).get(check_name) or {}


def collect_metrics(result):
    """Site-level numeric rollups for the trend ledger. Medians for
    continuous metrics so page-set drift between runs cannot masquerade as
    change; sums and unions for counts, with the sample size stored beside
    sampled counts. A metric nobody measured stays None: a gap in the trend,
    never a fabricated zero."""
    sc = result.get("scorecard", {}) or {}
    scores = {"overall": (sc.get("overall") or {}).get("score")}
    for name, g in (sc.get("categories") or {}).items():
        scores[name] = g.get("score")

    lcp, cls_vals, tbt, weight, ease = [], [], [], [], []
    broken_counts, checked_counts, mixed_counts = [], [], []
    third_party, trackers = set(), set()
    tp_seen = trk_seen = vitals_captured = False
    for ps in result.get("page_scans", []) or []:
        if (ps.get("vitals") or {}).get("captured"):
            vitals_captured = True
            for key, acc in (("lcp", lcp), ("cls", cls_vals), ("tbt", tbt)):
                val = _page_check(ps, "vitals", key).get("value")
                if isinstance(val, (int, float)):
                    acc.append(val)
        w = _page_check(ps, "performance", "static_weight").get("total_floor_kb")
        if isinstance(w, (int, float)):
            weight.append(w)
        e = _page_check(ps, "readability", "reading_ease").get("flesch_reading_ease")
        if isinstance(e, (int, float)):
            ease.append(e)
        lh = _page_check(ps, "links", "link_health")
        if isinstance(lh.get("checked"), (int, float)):
            checked_counts.append(lh["checked"])
            broken_counts.append((lh.get("counts") or {}).get("broken") or 0)
        mc = _page_check(ps, "links", "mixed_content")
        if isinstance(mc.get("count"), (int, float)):
            mixed_counts.append(mc["count"])
        tpo = _page_check(ps, "privacy", "third_party_origins")
        if "domains" in tpo:
            tp_seen = True
            third_party.update(tpo.get("domains") or [])
        kt = _page_check(ps, "privacy", "known_trackers")
        if "trackers" in kt:
            trk_seen = True
            trackers.update((kt.get("trackers") or {}).keys())

    return {
        "scores": scores,
        "pages": {
            "median_lcp_ms": _median(lcp),
            "median_cls": _median(cls_vals),
            "median_tbt_ms": _median(tbt),
            "median_weight_kb": _median(weight),
            "max_weight_kb": max(weight) if weight else None,
            "median_reading_ease": _median(ease),
            "broken_links": sum(broken_counts) if checked_counts else None,
            "links_checked": sum(checked_counts) if checked_counts else None,
            "mixed_content": sum(mixed_counts) if mixed_counts else None,
            "third_party_origins": len(third_party) if tp_seen else None,
            "known_trackers": len(trackers) if trk_seen else None,
        },
        "vitals_captured": vitals_captured,
    }
```

Then in `history_entry`, add one line to the returned dict, after `"bands": bands,`:

```python
        "metrics": collect_metrics(result),
```

- [ ] **Step 4: Run tests to verify they pass, plus the whole module for regressions**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools.TestTrendMetrics test_review_tools.TestFindingsHistory -v && python -m unittest test_review_tools`
Expected: all PASS (the full-suite run guards against contract-sweep regressions).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/review-site/tools/scan_site.py .claude/skills/review-site/tools/test_review_tools.py
git commit -m "Record numeric metrics on every history ledger line" && git push
```

---

### Task 2: Scan archive and the shared write path

**Files:**
- Modify: `.claude/skills/review-site/tools/scan_site.py` (add `import re`; add `archive_scan`, `write_run_outputs`; rewrite the write block in `main()` at lines ~411-418)
- Modify: `.claude/skills/review-site/tools/run_review.py` (replace the duplicated write block at lines ~91-99 with a `write_run_outputs` call)
- Test: `.claude/skills/review-site/tools/test_review_tools.py` (new class `TestRunOutputsAndArchive`)

**Interfaces:**
- Consumes: `attach_delta`, `append_history`, `write_digest_md`, `read_history`, `common.write_json` (all existing).
- Produces: `scan_site.archive_scan(result, out_dir) -> Path` writing `<out_dir>/archive/<slug>_scan_<stamp>.json` where stamp is `measured_at_utc` with `-` and `:` removed (e.g. `20260703T100000Z`). `scan_site.write_run_outputs(result, out_dir) -> dict` with keys `json_path`, `digest_path`, `history_path` (Path objects); it performs, in order: attach_delta, write scan JSON, archive copy, append ledger line, write digest. Task 4 consumes the returned `history_path`.

- [ ] **Step 1: Write the failing tests**

Add to `test_review_tools.py`:

```python
class TestRunOutputsAndArchive(unittest.TestCase):
    def _result(self, measured_at):
        r = json.loads(json.dumps(TestFindingsHistory.RESULT))
        r.update({"measured_at_utc": measured_at, "tool": "scan_site",
                  "host": "acme.example", "slug": "acme-example",
                  "page_scans": []})
        r["issues_grouped"] = {"fail": site.group_issues(r["issues"]["fail"]),
                               "warn": site.group_issues(r["issues"]["warn"])}
        return r

    def test_write_run_outputs_writes_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = site.write_run_outputs(self._result("2026-07-03T10:00:00Z"), out)
            self.assertTrue(paths["json_path"].exists())
            self.assertTrue(paths["digest_path"].exists())
            self.assertTrue(paths["history_path"].exists())
            archived = list((out / "archive").glob("*.json"))
            self.assertEqual([p.name for p in archived],
                             ["acme-example_scan_20260703T100000Z.json"])
            # The archive is the complete scan result, not the slim ledger line.
            data = json.loads(archived[0].read_text(encoding="utf-8"))
            self.assertIn("page_scans", data)

    def test_second_run_appends_ledger_and_new_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            site.write_run_outputs(self._result("2026-07-03T10:00:00Z"), out)
            second = self._result("2026-10-01T09:00:00Z")
            site.write_run_outputs(second, out)
            entries = site.read_history(out / "acme-example_history.jsonl")
            self.assertEqual(len(entries), 2)
            self.assertEqual(len(list((out / "archive").glob("*.json"))), 2)
            # The second run's delta compared against the first ledger entry.
            self.assertEqual(second["delta"]["previous_measured_at"],
                             "2026-07-03T10:00:00Z")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools.TestRunOutputsAndArchive -v`
Expected: ERROR with `AttributeError: module 'scan_site' has no attribute 'write_run_outputs'`.

- [ ] **Step 3: Implement archive and the shared write path**

In `scan_site.py`, add `import re` to the imports (after `import json`). Insert below `attach_delta`:

```python
def archive_scan(result, out_dir):
    """Immutable per-run copy of the full scan JSON. The ledger keeps the
    chosen metrics; the archive keeps everything, so a metric not in today's
    ledger schema can still be backfilled into future trends."""
    stamp = re.sub(r"[-:]", "", result.get("measured_at_utc") or "unknown")
    archive_dir = Path(out_dir) / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{result['slug']}_scan_{stamp}.json"
    common.write_json(path, result)
    return path


def write_run_outputs(result, out_dir):
    """Every per-run artifact for a scan result: delta, scan JSON, archive
    copy, ledger line, digest. The one write path shared by scan_site.main
    and run_review so the artifacts can never diverge."""
    out_dir = Path(out_dir)
    slug = result["slug"]
    json_path = out_dir / f"{slug}_scan.json"
    md_path = out_dir / f"{slug}_scan_summary.md"
    history_path = out_dir / f"{slug}_history.jsonl"
    attach_delta(result, json_path, history_path)
    common.write_json(json_path, result)
    archive_scan(result, out_dir)
    append_history(result, history_path)
    write_digest_md(result, md_path, history=read_history(history_path))
    return {"json_path": json_path, "digest_path": md_path,
            "history_path": history_path}
```

In `scan_site.main()`, replace these lines:

```python
    out_dir = common.evidence_dir()
    json_path = out_dir / f"{result['slug']}_scan.json"
    md_path = out_dir / f"{result['slug']}_scan_summary.md"
    history_path = out_dir / f"{result['slug']}_history.jsonl"
    attach_delta(result, json_path, history_path)
    common.write_json(json_path, result)
    append_history(result, history_path)
    write_digest_md(result, md_path, history=read_history(history_path))
```

with:

```python
    out_dir = common.evidence_dir()
    paths = write_run_outputs(result, out_dir)
```

and at the bottom of `main()` replace the two `print(f"\nWrote {json_path}")` / `print(f"Wrote {md_path}")` lines with:

```python
    print(f"\nWrote {paths['json_path']}")
    print(f"Wrote {paths['digest_path']}")
```

In `run_review.py` `pipeline()`, replace:

```python
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

    return {"scan": result, "discovery": disco, "capture": capture_summary,
            "json_path": json_path, "digest_path": md_path, "draft_path": draft_path}
```

with:

```python
    slug = result["slug"]
    paths = scan_site.write_run_outputs(result, out_dir)

    draft_path = out_dir / f"{slug}_exec_report_data.draft.json"
    common.write_json(draft_path, draft_report_data.draft(result))

    return {"scan": result, "discovery": disco, "capture": capture_summary,
            "json_path": paths["json_path"], "digest_path": paths["digest_path"],
            "draft_path": draft_path}
```

(Task 4 adds the trend to the draft call; leave it single-argument here.)

- [ ] **Step 4: Run the full tools suite**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools`
Expected: all PASS (existing pipeline tests exercise `run_review.pipeline`; they must stay green with the shared write path).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/review-site/tools/scan_site.py .claude/skills/review-site/tools/run_review.py .claude/skills/review-site/tools/test_review_tools.py
git commit -m "Archive each scan and share one write path between entry points" && git push
```

---

### Task 3: Trend module (`tools/trends.py`)

**Files:**
- Create: `.claude/skills/review-site/tools/trends.py`
- Test: `.claude/skills/review-site/tools/test_review_tools.py` (new class `TestTrends`; add `import trends as trends_mod` to the import block)

**Interfaces:**
- Consumes: ledger entries as written by `scan_site.history_entry` (keys `measured_at_utc`, `pages_scanned`, `bands`, `issues`, and from Task 1 `metrics`); `scan_site.diff_issues(prev, curr)`; `scan_site.read_history(path)`; `common.evidence_dir()`, `common.print_json`, `common.enable_utf8_stdout`.
- Produces:
  - `trends.quarter_of(ts: str) -> str | None` ("2026-07-02T15:37:23Z" -> "2026-Q3").
  - `trends.quarterly_points(entries) -> list[tuple[str, dict]]` one (quarter, entry) per quarter, oldest first, latest entry in each quarter.
  - `trends.build_trend(entries) -> dict | None` returning `{"quarters": [...], "series": {...}, "latest_delta": {...}}` or None with fewer than two quarterly points. `series` keys: `overall_score`, `<category>_score` per category seen, and each page metric with at least one measured value; every series is a list aligned to `quarters` with None gaps. `latest_delta` keys: `prev_quarter`, `quarter`, `scorecard` (list of `{category, prev_band, band, prev_score, score, direction}` with direction in `improved|held|declined`), `new_findings` (int), `resolved_findings` (int), `resolved_examples` (list of str, full enumeration), `pages_scanned` (`{"prev": int, "current": int}`).
  - `trends.trend_from_ledger(history_path) -> dict | None`.
  - CLI: `python trends.py <slug>` reads `planning/_evidence/<slug>_history.jsonl` and prints the trend JSON.

- [ ] **Step 1: Write the failing tests**

Add `import trends as trends_mod` to the import block of `test_review_tools.py` (alphabetical position, after `import triage as triage_mod`). Add:

```python
class TestTrends(unittest.TestCase):
    def _entry(self, ts, overall=0.7, seo=0.8, lcp=2000, fails=(), pages=5,
               with_metrics=True):
        e = {
            "measured_at_utc": ts,
            "pages_scanned": pages,
            "bands": {"overall": "Adequate", "seo": "Strong"},
            "issues": {"fail": [{"scan": "http_security", "check": c,
                                 "verdict": "fail", "note": f"{c} missing"}
                                for c in fails],
                       "warn": []},
        }
        if with_metrics:
            e["metrics"] = {
                "scores": {"overall": overall, "seo": seo},
                "pages": {"median_lcp_ms": lcp, "median_cls": None,
                          "median_tbt_ms": None, "median_weight_kb": None,
                          "max_weight_kb": None, "median_reading_ease": None,
                          "broken_links": None, "links_checked": None,
                          "mixed_content": None, "third_party_origins": None,
                          "known_trackers": None},
                "vitals_captured": lcp is not None,
            }
        return e

    def test_quarter_of(self):
        self.assertEqual(trends_mod.quarter_of("2026-07-02T15:37:23Z"), "2026-Q3")
        self.assertEqual(trends_mod.quarter_of("2025-12-31T23:59:59Z"), "2025-Q4")
        self.assertEqual(trends_mod.quarter_of("2026-01-01T00:00:00Z"), "2026-Q1")
        self.assertIsNone(trends_mod.quarter_of(None))
        self.assertIsNone(trends_mod.quarter_of("garbage"))

    def test_latest_run_per_quarter_wins(self):
        entries = [self._entry("2026-01-10T10:00:00Z", overall=0.5),
                   self._entry("2026-07-01T10:00:00Z", overall=0.6),
                   self._entry("2026-09-20T10:00:00Z", overall=0.9)]
        points = trends_mod.quarterly_points(entries)
        self.assertEqual([q for q, _ in points], ["2026-Q1", "2026-Q3"])
        self.assertEqual(points[-1][1]["metrics"]["scores"]["overall"], 0.9)

    def test_no_trend_under_two_quarterly_points(self):
        self.assertIsNone(trends_mod.build_trend([]))
        same_quarter = [self._entry("2026-07-01T10:00:00Z"),
                        self._entry("2026-09-01T10:00:00Z")]
        self.assertIsNone(trends_mod.build_trend(same_quarter))

    def test_series_align_to_quarters_with_gaps(self):
        entries = [self._entry("2026-01-10T10:00:00Z", overall=0.6, lcp=3000),
                   self._entry("2026-04-10T10:00:00Z", with_metrics=False),
                   self._entry("2026-07-10T10:00:00Z", overall=0.8, lcp=2000)]
        t = trends_mod.build_trend(entries)
        self.assertEqual(t["quarters"], ["2026-Q1", "2026-Q2", "2026-Q3"])
        self.assertEqual(t["series"]["overall_score"], [0.6, None, 0.8])
        self.assertEqual(t["series"]["median_lcp_ms"], [3000, None, 2000])
        # A metric never measured in any quarter gets no series at all.
        self.assertNotIn("median_weight_kb", t["series"])

    def test_latest_delta_directions_and_named_resolved(self):
        entries = [self._entry("2026-01-10T10:00:00Z", overall=0.6, seo=0.8,
                               fails=("hsts", "csp")),
                   self._entry("2026-04-10T10:00:00Z", overall=0.8, seo=0.9,
                               fails=("csp",), pages=6)]
        d = trends_mod.build_trend(entries)["latest_delta"]
        self.assertEqual(d["prev_quarter"], "2026-Q1")
        self.assertEqual(d["quarter"], "2026-Q2")
        seo_row = next(r for r in d["scorecard"] if r["category"] == "seo")
        self.assertEqual(seo_row["direction"], "improved")
        self.assertEqual(seo_row["prev_score"], 0.8)
        self.assertEqual(seo_row["score"], 0.9)
        self.assertEqual(d["new_findings"], 0)
        self.assertEqual(d["resolved_findings"], 1)
        self.assertEqual(d["resolved_examples"],
                         ["[http_security] hsts: hsts missing"])
        self.assertEqual(d["pages_scanned"], {"prev": 5, "current": 6})

    def test_pre_metrics_entries_hold_direction(self):
        entries = [self._entry("2026-01-10T10:00:00Z", with_metrics=False),
                   self._entry("2026-04-10T10:00:00Z", with_metrics=False)]
        d = trends_mod.build_trend(entries)["latest_delta"]
        self.assertTrue(all(r["direction"] == "held" for r in d["scorecard"]))

    def test_trend_from_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                for e in [self._entry("2026-01-10T10:00:00Z"),
                          self._entry("2026-04-10T10:00:00Z")]:
                    f.write(json.dumps(e) + "\n")
            t = trends_mod.trend_from_ledger(path)
        self.assertEqual(t["quarters"], ["2026-Q1", "2026-Q2"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools.TestTrends -v`
Expected: ERROR at import time, `ModuleNotFoundError: No module named 'trends'`.

- [ ] **Step 3: Create `tools/trends.py`**

```python
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
    """One (quarter, entry) pair per quarter, oldest quarter first. The
    ledger is append-only and chronological, so the last entry seen in a
    quarter is that quarter's data point."""
    by_quarter = {}
    for e in entries:
        q = quarter_of(e.get("measured_at_utc"))
        if q:
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
        if isinstance(p, (int, float)) and isinstance(c, (int, float)) and p != c:
            direction = "improved" if c > p else "declined"
        else:
            direction = "held"
        rows.append({"category": name,
                     "prev_band": prev_bands.get(name),
                     "band": curr_bands.get(name),
                     "prev_score": p, "score": c, "direction": direction})
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools.TestTrends -v && python -m unittest test_review_tools`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/review-site/tools/trends.py .claude/skills/review-site/tools/test_review_tools.py
git commit -m "Add trends module: quarterly points, series, and QoQ delta from the ledger" && git push
```

---

### Task 4: Fold the trend into the draft data

**Files:**
- Modify: `.claude/skills/review-site/tools/draft_report_data.py` (import `trends`; `draft()` gains a `trend=None` kwarg and a `slug` output field; `main()` reads the ledger)
- Modify: `.claude/skills/review-site/tools/run_review.py` (import `trends`; pass the trend into the draft call)
- Test: `.claude/skills/review-site/tools/test_review_tools.py` (new class `TestDraftTrend`)

**Interfaces:**
- Consumes: `trends.trend_from_ledger(history_path)` (Task 3); `write_run_outputs` returned `history_path` (Task 2).
- Produces: draft data dict gains `"slug"` (str) always, and `data["progress"]["trend"]` (the Task 3 trend block) when a trend exists. Task 6's builder reads exactly these two fields.

- [ ] **Step 1: Write the failing tests**

Add to `test_review_tools.py` (the existing `TestDraftReportData` class shows the minimal scan fixture shape; `drpt` is already imported):

```python
class TestDraftTrend(unittest.TestCase):
    SCAN = {
        "slug": "acme-example", "host": "acme.example",
        "target": "https://acme.example/",
        "measured_at_utc": "2026-07-03T10:00:00Z",
        "pages_scanned": ["https://acme.example/"],
        "totals": {"fail": 0, "warn": 0},
        "scorecard": {"overall": {"band": "Strong", "score": 0.9, "pass": 1,
                                  "warn": 0, "fail": 0},
                      "categories": {}},
        "issues": {"fail": [], "warn": []},
        "issues_grouped": {"fail": [], "warn": []},
        "page_scans": [],
    }

    def test_draft_embeds_trend_in_progress(self):
        trend = {"quarters": ["2026-Q2", "2026-Q3"], "series": {},
                 "latest_delta": {"new_findings": 0, "resolved_findings": 0}}
        data = drpt.draft(json.loads(json.dumps(self.SCAN)), trend=trend)
        self.assertEqual(data["slug"], "acme-example")
        self.assertEqual(data["progress"]["trend"]["quarters"],
                         ["2026-Q2", "2026-Q3"])

    def test_draft_without_trend_keeps_progress_shape(self):
        data = drpt.draft(json.loads(json.dumps(self.SCAN)))
        self.assertEqual(data["slug"], "acme-example")
        self.assertIsNone(data["progress"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools.TestDraftTrend -v`
Expected: FAIL with `TypeError: draft() got an unexpected keyword argument 'trend'`.

- [ ] **Step 3: Implement the draft integration**

In `draft_report_data.py`:

1. Add `import trends` after `import common`.
2. Change the signature `def draft(scan):` to `def draft(scan, trend=None):` and update its docstring first line to: `"""Build a first-draft exec_report_data dict from a scan_site result dict. trend is the quarterly block from trends.build_trend, when history has one."""`
3. After the existing `progress = ...` block (the `if delta:` block), add:

```python
    if trend:
        # The quarterly trend lives inside the progress area; the builder
        # renders it as its own report section.
        progress = dict(progress or {})
        progress["trend"] = trend
```

4. In the returned dict, add `"slug": slug,` immediately after `"site": scan.get("host", slug),` (the builder needs it to name chart files).
5. In `main()`, replace `data = draft(scan)` with:

```python
    history_path = in_path.with_name(f"{scan.get('slug', 'site')}_history.jsonl")
    trend = trends.trend_from_ledger(history_path) if history_path.exists() else None
    data = draft(scan, trend=trend)
```

In `run_review.py`:

1. Add `import trends` to the import block (after `import scan_site`).
2. In `pipeline()`, replace `common.write_json(draft_path, draft_report_data.draft(result))` with:

```python
    trend = trends.trend_from_ledger(paths["history_path"])
    common.write_json(draft_path, draft_report_data.draft(result, trend=trend))
```

(The ledger already contains this run's line at this point, so the current run is the latest point in its own quarter, which is exactly what the report should show.)

- [ ] **Step 4: Run the full tools suite**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/review-site/tools/draft_report_data.py .claude/skills/review-site/tools/run_review.py .claude/skills/review-site/tools/test_review_tools.py
git commit -m "Carry the quarterly trend block into the draft report data" && git push
```

---

### Task 5: Chart renderer (`report_charts.py`)

**Files:**
- Create: `.claude/skills/review-site/report_charts.py` (skill root, next to `build_exec_report.py`; NOT under `tools/`)
- Create: `.claude/skills/review-site/test_report_charts.py`

**Interfaces:**
- Consumes: the Task 3 trend block (`quarters`, `series`).
- Produces: `report_charts.HAVE_MPL` (bool); `report_charts.drawable(values) -> bool` (at least two measured points); `report_charts.metric_panels(series) -> list[tuple[key, title, fmt]]`; `report_charts.render_trend_charts(trend, out_dir, prefix) -> list[dict]` where each dict is `{"caption": str, "path": str}`, writing up to three PNGs named `<prefix>_trend_overall.png`, `<prefix>_trend_categories.png`, `<prefix>_trend_metrics.png`. Raises RuntimeError with an install message when matplotlib is missing. Task 6 embeds the returned paths in caption order.

Chart design rules (from the dataviz skill; do not deviate):
- Single-hue navy lines (`#0B1F3A`, the report accent), 2px, round join/cap; markers with a white surface ring; the latest measured point gets a gold (`#C9A227`) marker. No legends: every panel is a single series and its title names it.
- Ten category lines on one plot is an anti-pattern; categories render as small multiples, one panel each, shared 0-1 y-scale.
- Page metrics have different units, so each gets its own panel (never a dual axis).
- Direct-label the endpoint only, in ink color (text never wears the data color). Grid is solid hairline `#D8DEE9`, recessive; y-axis from 0 for magnitudes, 0-1 for scores.
- None values become NaN so matplotlib breaks the line: a visible gap, never an interpolation.
- Sans font (Calibri with DejaVu Sans fallback), never the report's serif display face.

- [ ] **Step 0: Verify matplotlib is installed**

Run: `pip show matplotlib`
If missing: `pip install matplotlib` (it is part of the user's standard stack; installing is expected, not optional).

- [ ] **Step 1: Write the failing tests**

Create `.claude/skills/review-site/test_report_charts.py`:

```python
#!/usr/bin/env python3
"""
Offline tests for report_charts.py.

Rendering tests are skipped when matplotlib is missing; the panel-selection
logic is pure and always tested. Run from this directory:
    python -m unittest test_report_charts
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import report_charts as rc

TREND = {
    "quarters": ["2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"],
    "series": {
        "overall_score": [0.61, 0.68, None, 0.84],
        "security_score": [0.55, 0.7, 0.8, 0.9],
        "seo_score": [0.8, 0.8, 0.85, 0.9],
        "median_lcp_ms": [3400, None, 2600, 2100],
        "median_weight_kb": [3100.0, 2900.0, 2500.0, 2400.0],
        "broken_links": [9, 7, 4, 3],
    },
    "latest_delta": {},
}


class TestPanelSelection(unittest.TestCase):
    def test_drawable_needs_two_measured_points(self):
        self.assertTrue(rc.drawable([1, None, 2]))
        self.assertFalse(rc.drawable([None, None, 5]))
        self.assertFalse(rc.drawable([]))
        self.assertFalse(rc.drawable(None))

    def test_metric_panels_require_two_measured_quarters(self):
        series = {"median_lcp_ms": [None, 2100, None],
                  "broken_links": [3, 2, 1]}
        keys = [key for key, _, _ in rc.metric_panels(series)]
        self.assertEqual(keys, ["broken_links"])


@unittest.skipUnless(rc.HAVE_MPL, "matplotlib not installed")
class TestRenderTrendCharts(unittest.TestCase):
    def test_renders_three_pngs_with_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            charts = rc.render_trend_charts(TREND, tmp, "acme-example")
            self.assertEqual([Path(c["path"]).name for c in charts],
                             ["acme-example_trend_overall.png",
                              "acme-example_trend_categories.png",
                              "acme-example_trend_metrics.png"])
            for c in charts:
                self.assertTrue(c["caption"])
                self.assertGreater(Path(c["path"]).stat().st_size, 5000)

    def test_sparse_series_render_nothing(self):
        trend = {"quarters": ["2026-Q1", "2026-Q2", "2026-Q3"],
                 "series": {"overall_score": [None, None, 0.8],
                            "median_lcp_ms": [None, None, 2100]},
                 "latest_delta": {}}
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rc.render_trend_charts(trend, tmp, "x"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/skills/review-site && python -m unittest test_report_charts -v`
Expected: ERROR at import time, `ModuleNotFoundError: No module named 'report_charts'`.

- [ ] **Step 3: Create `report_charts.py`**

```python
#!/usr/bin/env python3
"""
Trend chart renderer for the executive report.

Draws the quarterly trend PNGs the report embeds: overall score, per-category
score small multiples, and key page metrics. Single-hue navy lines with a
gold current-quarter marker, hairline grid, endpoint-only labels; a None
quarter breaks the line (a gap, never an interpolation). Kept separate from
build_exec_report so matplotlib is only needed when a report actually has a
trend to draw; the scanner suite under tools/ stays stdlib-only.

Dependency:
    pip install matplotlib
"""

import math
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

# The report's design tokens (see build_exec_report.py). Lines carry the
# accent; text stays in ink/muted, never the data color.
NAVY = "#0B1F3A"
GOLD = "#C9A227"
INK = "#262B33"
MUTED = "#5A6672"
HAIRLINE = "#D8DEE9"
SANS = ["Calibri", "DejaVu Sans"]

METRIC_PANELS = [
    ("median_lcp_ms", "Median LCP (ms)", lambda v: f"{v:,.0f}"),
    ("median_weight_kb", "Median page weight (KB)", lambda v: f"{v:,.0f}"),
    ("broken_links", "Broken links", lambda v: f"{v:.0f}"),
]


def drawable(values):
    """A line needs at least two measured points; one point is a dot, not a
    trend, and zero is nothing."""
    return bool(values) and sum(v is not None for v in values) >= 2


def metric_panels(series):
    return [(key, title, fmt) for key, title, fmt in METRIC_PANELS
            if drawable(series.get(key))]


def _last_point(values):
    for i in range(len(values) - 1, -1, -1):
        if values[i] is not None:
            return i, values[i]
    return None


def _plot_series(ax, values, linewidth=2, markersize=7, endpoint_size=9):
    xs = list(range(len(values)))
    ys = [math.nan if v is None else v for v in values]
    ax.plot(xs, ys, color=NAVY, linewidth=linewidth,
            solid_joinstyle="round", solid_capstyle="round",
            marker="o", markersize=markersize, markerfacecolor=NAVY,
            markeredgecolor="white", markeredgewidth=1.5)
    last = _last_point(values)
    if last is not None:
        ax.plot([last[0]], [last[1]], marker="o", markersize=endpoint_size,
                color=GOLD, markeredgecolor="white", markeredgewidth=1.5,
                zorder=5)


def _style_axis(ax):
    ax.tick_params(axis="both", length=0, labelsize=8, labelcolor=MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(HAIRLINE)
    ax.grid(axis="y", color=HAIRLINE, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)


def _quarter_ticks(ax, quarters, full=True, fontsize=8):
    if full:
        ax.set_xticks(range(len(quarters)))
        ax.set_xticklabels(quarters, fontsize=fontsize, color=MUTED)
    else:
        # Narrow panels: first and last quarter only, so labels never collide.
        ax.set_xticks([0, len(quarters) - 1])
        ax.set_xticklabels([quarters[0], quarters[-1]],
                           fontsize=fontsize, color=MUTED)
    ax.set_xlim(-0.35, len(quarters) - 0.65)


def _label_endpoint(ax, values, fmt, fontsize=8.5):
    last = _last_point(values)
    if last is not None:
        ax.annotate(fmt(last[1]), (last[0], last[1]),
                    textcoords="offset points", xytext=(0, 9), ha="center",
                    fontsize=fontsize, color=INK, fontweight="bold")


def _save(fig, path):
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_trend_charts(trend, out_dir, prefix):
    """Render the report's trend PNGs; returns {'caption','path'} dicts in
    embed order. Only series with at least two measured quarters draw."""
    if not HAVE_MPL:
        raise RuntimeError("matplotlib is required to draw the trend charts "
                           "in this report: pip install matplotlib")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = SANS
    quarters = trend["quarters"]
    series = trend.get("series") or {}
    charts = []

    overall = series.get("overall_score")
    if drawable(overall):
        fig, ax = plt.subplots(figsize=(6.8, 2.2))
        _plot_series(ax, overall)
        _style_axis(ax)
        _quarter_ticks(ax, quarters)
        ax.set_ylim(0, 1.08)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        _label_endpoint(ax, overall, lambda v: f"{v:.2f}")
        path = out_dir / f"{prefix}_trend_overall.png"
        _save(fig, path)
        charts.append({"caption": "Overall measured score by quarter "
                                  "(0 to 1; higher is better).",
                       "path": str(path)})

    cats = [k for k in series
            if k.endswith("_score") and k != "overall_score"
            and drawable(series[k])]
    if cats:
        cols = min(4, len(cats))
        rows = -(-len(cats) // cols)
        fig, axes = plt.subplots(rows, cols,
                                 figsize=(6.8, 1.45 * rows + 0.3),
                                 squeeze=False)
        for i, key in enumerate(cats):
            ax = axes[i // cols][i % cols]
            _plot_series(ax, series[key], markersize=4, endpoint_size=6)
            _style_axis(ax)
            ax.set_title(key[:-len("_score")], fontsize=8.5, color=INK, pad=3)
            ax.set_ylim(0, 1.08)
            ax.set_yticks([0, 1])
            if i // cols == rows - 1:
                _quarter_ticks(ax, quarters, full=False, fontsize=6.5)
            else:
                ax.set_xticks([])
                ax.set_xlim(-0.35, len(quarters) - 0.65)
        for j in range(len(cats), rows * cols):
            axes[j // cols][j % cols].axis("off")
        fig.tight_layout()
        path = out_dir / f"{prefix}_trend_categories.png"
        _save(fig, path)
        charts.append({"caption": "Category scores by quarter "
                                  "(shared 0 to 1 scale).",
                       "path": str(path)})

    panels = metric_panels(series)
    if panels:
        fig, axes = plt.subplots(1, len(panels), figsize=(6.8, 2.0),
                                 squeeze=False)
        for ax, (key, title, fmt) in zip(axes[0], panels):
            _plot_series(ax, series[key], markersize=5, endpoint_size=7)
            _style_axis(ax)
            ax.set_title(title, fontsize=8.5, color=INK, pad=3)
            _quarter_ticks(ax, quarters, full=False, fontsize=6.5)
            ax.set_ylim(bottom=0)
            _label_endpoint(ax, series[key], fmt, fontsize=8)
        fig.tight_layout()
        path = out_dir / f"{prefix}_trend_metrics.png"
        _save(fig, path)
        charts.append({"caption": "Key page metrics by quarter (site "
                                  "medians; a gap is a quarter where the "
                                  "metric was not captured).",
                       "path": str(path)})

    return charts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd .claude/skills/review-site && python -m unittest test_report_charts -v`
Expected: all PASS (4 tests; none skipped since matplotlib was verified in Step 0).

- [ ] **Step 5: Eyeball the rendered charts (dataviz final check)**

Render the fixture to the scratchpad and look at all three PNGs with the Read tool:

```bash
cd .claude/skills/review-site && python -c "
import test_report_charts as t, report_charts as rc
print(rc.render_trend_charts(t.TREND, r'C:\Users\lenam\AppData\Local\Temp\claude\C--Users-lenam-projects-web-site-analyzer\3f08e804-c804-4f69-917b-6a412ccfca9c\scratchpad', 'eyeball'))"
```

Read each PNG and confirm: no label collisions, the gap in overall_score is visibly broken (not bridged), endpoint labels clear the plot edge, quarter labels legible. Fix and re-render if not.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/review-site/report_charts.py .claude/skills/review-site/test_report_charts.py
git commit -m "Add matplotlib trend chart renderer for the executive report" && git push
```

---

### Task 6: "Progress this quarter" section in the builder

**Files:**
- Modify: `.claude/skills/review-site/build_exec_report.py` (import `report_charts`; add `add_trend_table`, `add_trend_section`; wire into `build()`; `build()` and `main()` gain `chart_dir`)
- Test: `.claude/skills/review-site/test_exec_report.py` (new class `TestTrendSection`)

**Interfaces:**
- Consumes: `data["progress"]["trend"]` and `data["slug"]` (Task 4); `report_charts.render_trend_charts(trend, chart_dir, prefix)` (Task 5); existing helpers `section_heading`, `add_data_table`, `_chip`, `add_run`, `add_framed_picture`, `BAND_FILL`, `SEVERITY_FILL`, `MUTED_RGB`.
- Produces: `build(data, out_path, chart_dir=None)` (backward compatible; `chart_dir` defaults to the docx's parent directory). `main()` passes `chart_dir=in_path.parent / "rendered"` so chart PNGs land in `planning/_evidence/rendered/` next to the other generated evidence.

Rendering contract (from the approved spec):
- Section title "Progress this quarter", numbered, placed immediately after the Executive summary section, listed on the cover contents.
- Contents in order: QoQ scorecard table, pages-reviewed footer line, charts (only when 3+ quarterly points), findings-movement line plus every resolved finding named as a bullet (no truncation).
- When the trend renders, the old one-line progress strip is suppressed (redundant). Without a trend, the report renders exactly as today.
- No try/except around chart rendering: a missing matplotlib must fail the build loudly, never ship a silently chartless client deliverable.

- [ ] **Step 1: Write the failing tests**

Add to `.claude/skills/review-site/test_exec_report.py`, inside the `if HAVE_DOCX:` guarded region or with the same `@unittest.skipUnless(HAVE_DOCX, ...)` decorator pattern the existing class uses. Follow the existing class's helper conventions for building and reopening a doc (reuse its `_build`-style helper if one exists; otherwise the inline pattern below):

```python
try:
    import report_charts
    HAVE_MPL = report_charts.HAVE_MPL
except ImportError:
    HAVE_MPL = False

TREND_2Q = {
    "quarters": ["2026-Q2", "2026-Q3"],
    "series": {"overall_score": [0.72, 0.84]},
    "latest_delta": {
        "prev_quarter": "2026-Q2", "quarter": "2026-Q3",
        "scorecard": [{"category": "security", "prev_band": "Adequate",
                       "band": "Strong", "prev_score": 0.7, "score": 0.9,
                       "direction": "improved"},
                      {"category": "seo", "prev_band": "Strong",
                       "band": "Strong", "prev_score": 0.9, "score": 0.9,
                       "direction": "held"}],
        "new_findings": 1, "resolved_findings": 2,
        "resolved_examples": [
            "[a11y] link_text: 2 link(s) have no discernible text.",
            "[seo] headings: No H1 on the page."],
        "pages_scanned": {"prev": 12, "current": 12},
    },
}

TREND_3Q = {
    "quarters": ["2026-Q1", "2026-Q2", "2026-Q3"],
    "series": {"overall_score": [0.61, 0.72, 0.84],
               "security_score": [0.5, 0.7, 0.9],
               "median_lcp_ms": [3400, 2600, 2100],
               "median_weight_kb": [3100.0, 2500.0, 2400.0],
               "broken_links": [9, 4, 3]},
    "latest_delta": TREND_2Q["latest_delta"],
}


@unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
class TestTrendSection(unittest.TestCase):
    def _data(self, trend):
        data = {k: v for k, v in SAMPLE.items() if k != "evidence"}
        data["slug"] = "example-com"
        data["progress"] = dict(SAMPLE["progress"], trend=trend)
        return data

    def _doc(self, data, tmp):
        out = Path(tmp) / "r.docx"
        ber.build(data, out, chart_dir=Path(tmp) / "charts")
        return Document(str(out))

    def test_trend_table_and_named_resolved_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        texts = [p.text for p in doc.paragraphs]
        self.assertTrue(any("Progress this quarter" in t for t in texts))
        headers = [t.rows[0].cells[0].text.strip() for t in doc.tables]
        self.assertIn("AREA", headers)
        self.assertTrue(any("No H1 on the page." in t for t in texts))
        self.assertTrue(any(
            "2 finding(s) resolved since 2026-Q2; 1 new." in t for t in texts))
        self.assertTrue(any("Pages reviewed: 12 in 2026-Q2, 12 in 2026-Q3"
                            in t for t in texts))

    def test_progress_strip_suppressed_when_trend_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        texts = [p.text for p in doc.paragraphs]
        self.assertFalse(any("Since the previous review" in t for t in texts))

    def test_two_quarters_embed_no_charts(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        self.assertEqual(len(doc.inline_shapes), 0)

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_three_quarters_embed_charts(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_3Q), tmp)
        # overall + categories (one drawable category) + metrics figure
        self.assertEqual(len(doc.inline_shapes), 3)

    def test_cover_contents_list_includes_progress_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        texts = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("Progress this quarter", texts)
```

Note: `SAMPLE` in this test file may include an `evidence` image entry; `_data` strips it so `inline_shapes` counts only trend charts. If `SAMPLE` has no `evidence` key the dict comprehension is a no-op.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/skills/review-site && python -m unittest test_exec_report.TestTrendSection -v`
Expected: FAIL: no "Progress this quarter" paragraph (build succeeds but the section does not exist), and the strip-suppression test fails.

- [ ] **Step 3: Implement the builder section**

In `build_exec_report.py`:

1. Add `import report_charts` after the `from docx.shared import ...` line (safe without matplotlib; the module guards it).
2. Add below `add_progress_strip`:

```python
DIRECTION_STYLE = {"improved": ("STRONGER", SEVERITY_FILL["Low"]),
                   "held": ("HELD", "8A94A6"),
                   "declined": ("WEAKER", SEVERITY_FILL["High"])}


def _fmt_score(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "n/a"


def add_trend_table(document, delta):
    """Quarter-over-quarter posture: prior band, current band, score
    movement, and a direction chip per category."""
    def trend_row(row):
        def write(cells):
            set_cell_text(cells[0], row.get("category", ""), size=9, bold=True)
            for cell, band in ((cells[1], row.get("prev_band")),
                               (cells[2], row.get("band"))):
                band = band or "Not measured"
                _chip(cell, band, BAND_FILL.get(band, BAND_FILL["Not measured"]))
            p, c = row.get("prev_score"), row.get("score")
            change = (f"{c - p:+.2f}"
                      if isinstance(p, (int, float)) and isinstance(c, (int, float))
                      else "n/a")
            set_cell_text(cells[3], f"{_fmt_score(p)} to {_fmt_score(c)} ({change})",
                          size=8.5, color=MUTED_RGB)
            label, fill = DIRECTION_STYLE.get(row.get("direction"),
                                              DIRECTION_STYLE["held"])
            _chip(cells[4], label, fill)
        return write

    headers = ["Area", delta.get("prev_quarter") or "Prior",
               delta.get("quarter") or "Current", "Score", "Direction"]
    add_data_table(document, headers,
                   [Inches(1.35), Inches(1.1), Inches(1.1),
                    Inches(2.15), Inches(1.3)],
                   [trend_row(r) for r in delta.get("scorecard", [])])


def add_trend_section(document, trend, chart_dir, prefix, number):
    """Progress this quarter: the QoQ posture table, trend charts (three or
    more quarterly points), and every resolved finding named in full. This
    is the retainer's value story, so it leads the report."""
    section_heading(document, "Progress this quarter", number)
    delta = trend.get("latest_delta") or {}
    if delta.get("scorecard"):
        add_trend_table(document, delta)
        ps = delta.get("pages_scanned") or {}
        if ps.get("prev") is not None or ps.get("current") is not None:
            note = document.add_paragraph()
            note.paragraph_format.space_before = Pt(4)
            add_run(note, f"Pages reviewed: {ps.get('prev')} in "
                          f"{delta.get('prev_quarter')}, {ps.get('current')} "
                          f"in {delta.get('quarter')}.",
                    size=8, color=MUTED_RGB, italic=True)

    # Charts start at three quarterly points; a two-point line implies a
    # slope one interval cannot support, so the table carries the QoQ story.
    if len(trend.get("quarters") or []) >= 3:
        charts = report_charts.render_trend_charts(trend, chart_dir, prefix)
        for chart in charts:
            cap = document.add_paragraph()
            cap.paragraph_format.space_before = Pt(10)
            cap.paragraph_format.space_after = Pt(4)
            cap.paragraph_format.keep_with_next = True
            add_run(cap, chart["caption"], size=8.5, color=MUTED_RGB, italic=True)
            add_framed_picture(document, chart["path"])

    movement = document.add_paragraph()
    movement.paragraph_format.space_before = Pt(10)
    add_run(movement,
            f"{delta.get('resolved_findings', 0)} finding(s) resolved since "
            f"{delta.get('prev_quarter', 'the previous quarter')}; "
            f"{delta.get('new_findings', 0)} new.", size=10, bold=True)
    for item in delta.get("resolved_examples") or []:
        p = document.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        add_run(p, item, size=9)
```

3. Change the `build` signature from `def build(data, out_path):` to:

```python
def build(data, out_path, chart_dir=None):
```

and immediately inside, after `document = Document()`, add:

```python
    chart_dir = Path(chart_dir) if chart_dir else Path(out_path).parent
```

4. In the section-titles block, add after the `if bottom_line or assessment:` append:

```python
    progress = data.get("progress") or {}
    trend = progress.get("trend")
    if trend:
        section_titles.append("Progress this quarter")
```

(and delete the later `progress = data.get("progress")` line inside the executive-summary block since `progress` is now defined earlier; keep the strip call but change its guard as below).

5. In the executive-summary block, replace:

```python
    progress = data.get("progress")
    if progress:
        add_progress_strip(document, progress)
```

with:

```python
    if progress and not trend:
        add_progress_strip(document, progress)
```

6. After the executive-summary block (after `if assessment: add_assessment(...)`) and before the scorecard block, add:

```python
    if trend:
        add_trend_section(document, trend, chart_dir,
                          data.get("slug") or "site",
                          number_of.get("Progress this quarter"))
```

7. In `main()`, replace `build(data, out_path)` with:

```python
    build(data, out_path, chart_dir=in_path.parent / "rendered")
```

- [ ] **Step 4: Run both suites**

Run: `cd .claude/skills/review-site && python -m unittest test_exec_report test_report_charts && cd tools && python -m unittest test_review_tools`
Expected: all PASS, including every pre-existing `TestExecReport` test (the no-trend path must be byte-for-byte behaviorally unchanged).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/review-site/build_exec_report.py .claude/skills/review-site/test_exec_report.py
git commit -m "Render Progress this quarter: QoQ table, trend charts, named resolved findings" && git push
```

---

### Task 7: Docs, gitignore, end-to-end verification

**Files:**
- Modify: `.gitignore` (archive rule)
- Modify: `.claude/skills/review-site/SKILL.md` (trend layer paragraph)
- Modify: `CLAUDE.md` (tooling-reality and output-contract mentions)
- Modify: `.claude/skills/review-site/build_exec_report.py` (docstring dependency line only)

**Interfaces:** none; documentation and verification.

- [ ] **Step 1: gitignore the archive**

In `.gitignore`, in the "Generated review outputs" block, add after the `planning/_evidence/*_crawl_state.json` line:

```
planning/_evidence/archive/
```

- [ ] **Step 2: Update the builder docstring**

In `build_exec_report.py`, change the docstring dependency block to:

```
Dependency:
    pip install python-docx matplotlib
    (matplotlib is only exercised when the report data carries a quarterly
    trend with three or more quarters of history)
```

- [ ] **Step 3: Document the trend layer**

In `.claude/skills/review-site/SKILL.md`, find the section describing the deterministic evidence tools / history ledger (grep for "history"). Append this paragraph to that section, adjusting only surrounding whitespace:

```
Quarterly trends: every run appends numeric metrics (category scores and
site-level page-metric rollups) to the history ledger and archives the full
scan JSON under planning/_evidence/archive/ for future backfill. tools/trends.py
reduces the ledger to one point per calendar quarter (the latest run in each
quarter, so ad-hoc runs never pollute the series) and the draft step folds the
result into the report data. With two or more quarterly points the executive
report renders a "Progress this quarter" section: a quarter-over-quarter
posture table, trend charts (from three quarters), and every resolved finding
named. Inspect a site's series any time with: python trends.py <slug>
```

In `CLAUDE.md` (repo root), in the "Tooling reality" section, append to the end of the first bullet (the scanner-suite bullet), before the sentence about the offline unit-test suite:

```
Each run also appends numeric trend metrics to planning/_evidence/<slug>_history.jsonl
and archives the full scan JSON under planning/_evidence/archive/; with two or
more calendar quarters of ledger history the report gains a "Progress this
quarter" trend section (charts from three quarters), built from the latest run
in each quarter.
```

- [ ] **Step 4: Full offline verification**

Run: `cd .claude/skills/review-site/tools && python -m unittest test_review_tools && cd .. && python -m unittest test_exec_report test_report_charts`
Expected: all PASS.

- [ ] **Step 5: End-to-end sample report (the verify pass)**

Build a real docx from a synthetic 4-quarter history in the scratchpad, exercising ledger -> trends -> draft -> builder without any network:

```bash
cd .claude/skills/review-site && python - <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, "tools")
import scan_site, trends, draft_report_data, build_exec_report

scratch = Path(r"C:\Users\lenam\AppData\Local\Temp\claude\C--Users-lenam-projects-web-site-analyzer\3f08e804-c804-4f69-917b-6a412ccfca9c\scratchpad") / "e2e"
scratch.mkdir(parents=True, exist_ok=True)

def result(ts, overall, sec, lcp, fails):
    return {
        "tool": "scan_site", "target": "https://acme.example/",
        "host": "acme.example", "slug": "acme-example",
        "measured_at_utc": ts, "pages_scanned": ["https://acme.example/"] * 5,
        "totals": {"fail": len(fails), "warn": 0,
                   "grouped_fail": len(fails), "grouped_warn": 0},
        "scorecard": {"overall": {"band": "Adequate", "score": overall,
                                  "pass": 8, "warn": 1, "fail": len(fails)},
                      "categories": {"security": {"band": "Adequate", "score": sec,
                                                  "pass": 4, "warn": 1,
                                                  "fail": len(fails)},
                                     "seo": {"band": "Strong", "score": 0.9,
                                             "pass": 4, "warn": 0, "fail": 0}}},
        "cross_page": {}, "host_scans": {},
        "page_scans": [{"url": "https://acme.example/",
                        "vitals": {"captured": True, "checks": {
                            "lcp": {"value": lcp, "verdict": "pass"},
                            "cls": {"value": 0.02, "verdict": "pass"},
                            "tbt": {"value": 150, "verdict": "pass"}}},
                        "performance": {"ok": True, "checks": {"static_weight": {
                            "total_floor_kb": 900.0, "verdict": "pass"}}},
                        "readability": {"ok": True, "checks": {"reading_ease": {
                            "flesch_reading_ease": 52.0, "verdict": "pass"}}},
                        "links": {"ok": True, "checks": {
                            "link_health": {"checked": 20,
                                            "counts": {"broken": len(fails)}},
                            "mixed_content": {"count": 0}}},
                        "privacy": {"ok": True, "checks": {
                            "third_party_origins": {"domains": ["cdn.example"]},
                            "known_trackers": {"trackers": {}}}}}],
        "issues": {"fail": [{"scan": "http_security", "check": c,
                             "verdict": "fail", "note": f"{c} header missing"}
                            for c in fails], "warn": []},
        "issues_grouped": {"fail": [{"scan": "http_security", "check": c,
                                     "verdict": "fail",
                                     "note": f"{c} header missing",
                                     "pages": [], "page_count": 0}
                                    for c in fails], "warn": []},
    }

runs = [("2025-10-15T10:00:00Z", 0.61, 0.50, 3400, ("hsts", "csp", "cookies")),
        ("2026-01-15T10:00:00Z", 0.68, 0.62, 3000, ("hsts", "csp")),
        ("2026-04-15T10:00:00Z", 0.75, 0.74, 2500, ("csp",)),
        ("2026-07-01T10:00:00Z", 0.84, 0.90, 2100, ())]
for ts, overall, sec, lcp, fails in runs:
    scan_site.write_run_outputs(result(ts, overall, sec, lcp, fails), scratch)

trend = trends.trend_from_ledger(scratch / "acme-example_history.jsonl")
last = result(*runs[-1])
data = draft_report_data.draft(last, trend=trend)
data["recommendations"] = []
out = scratch / "acme-example_Executive_Report.docx"
build_exec_report.build(data, out, chart_dir=scratch / "rendered")
print("quarters:", trend["quarters"])
print("wrote:", out)
EOF
```

Expected output: `quarters: ['2025-Q4', '2026-Q1', '2026-Q2', '2026-Q3']` and the docx path. Then:
1. Read the three PNGs under `<scratch>/e2e/rendered/` and eyeball them (label collisions, gap rendering, legibility).
2. Confirm the archive has 4 files: `ls <scratch>/e2e/archive` shows 4 timestamped JSONs.
3. Convert the docx to PDF for a visual pass if Word is available (`soffice`/Word COM); otherwise send the docx to the user with SendUserFile for a look. Per the standing report-quality memory, the rendered result must be visually verified, not assumed.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .claude/skills/review-site/SKILL.md CLAUDE.md .claude/skills/review-site/build_exec_report.py
git commit -m "Document the quarterly trend layer and ignore the scan archive" && git push
```
