# BACKLOG.md - Prioritized task list

Statuses: todo, doing, done, blocked. One task per loop iteration. Pick the
highest-priority unblocked `todo`. Keep tasks small enough to finish and verify
in a single run; split anything larger. See PLAN.md for the design each task
serves.

## Phase A - Foundation (registry + contract enforcement)

## Phase B - Self-describing tools

## Phase C - Expansion (new passive dimensions, spec in PLAN.md first)

- [ ] **C2 (todo, P3)** Implement `scan_privacy.py` to the PLAN.md section 7
  spec and the shared contract (page scope, CATEGORY="privacy", regex-based
  script/iframe/img extraction, reuse `scan_dns_email.registrable_domain`,
  embedded KNOWN_TRACKERS/CMP_HOSTS/CONSENT_MARKERS, the four checks). Register
  one page entry in `registry.py` as label "privacy". Ship offline unit tests
  (first-vs-third-party, tracker match, 1x1 pixel, CMP/marker, consent matrix,
  client-rendered inconclusive). Verify: full suite green (TestToolContract picks
  it up automatically) and a smoke run on example.com. Unblocked by C1.

## Phase D - Reporting automation

- [ ] **D1 (todo, P3)** Spec and prototype generating a first-draft
  `exec_report_data.json` from `<slug>_scan.json` (scorecard + top fails/warns as
  findings), leaving human-authored findings to be layered on top. Design in
  PLAN.md first. Depends on A1.

## Done
- [x] **C1 (done)** Spec a privacy/tracker scanner. Wrote the full `scan_privacy`
  design as PLAN.md section 7: page scope, CATEGORY="privacy", passive static-only
  extraction (regex for script/iframe/img + reuse of `parsed` links/images),
  first-vs-third-party via `scan_dns_email.registrable_domain`, embedded
  KNOWN_TRACKERS/CMP_HOSTS/CONSENT_MARKERS, four checks (third_party_origins,
  known_trackers, tracking_pixels, cookie_consent), client-rendered handling, and
  non-goals. Confirmed data dependencies against htmlmeta and scan_performance
  (no shared-parser change needed). Design only; C2 implements. See JOURNAL.md
  2026-07-01 C1.
- [x] **B2 (done)** Tool-owned grade. Moved the band/score logic and verdict
  extraction into `common.grade(verdicts)` and `common.verdicts_of(result)`
  (verbatim). `scan_site.build_scorecard` and each tool's `scan()` wrapper now
  share them, so no band logic is duplicated; every tool stamps its own `grade`.
  Verified scorecard bands identical before/after on example.com (overall
  Adequate 0.74). Suite 60 tests, all pass. See JOURNAL.md 2026-07-01 B2.
- [x] **B1 (done)** Tool-owned category and scope. Added `CATEGORY`/`SCOPE`
  constants to all 8 scanner modules; each `scan()` is now a thin wrapper over an
  internal `_scan()` that stamps `category` onto every result, so tool output is
  self-describing. `registry.py` reads scope/category from the module via a
  `_entry()` helper. Scorecard categories verified unchanged on example.com; each
  scan's JSON now carries its category. Added 1 registry test and strengthened
  the contract test to assert surfaced category. Suite 60 tests, all pass. See
  JOURNAL.md 2026-07-01 B1.
- [x] **A2 (done)** Contract-conformance test. Added
  `test_review_tools.TestToolContract` (3 tests, each sweeping all 8 registered
  tools): offline success-shape check via stubbed network primitives,
  no-tool-raises-on-network-failure, and `_safe_scan` wrapping. Suite now 59
  tests, all pass. Amended PLAN.md section 4 to record the honest contract (the
  two host check tools omit `ok` on success; success is denoted by a non-empty
  `checks` map). See JOURNAL.md 2026-07-01 A2.
- [x] **A1 (done)** Central tool registry. Added `tools/registry.py` (8 entries:
  3 host, 5 page). Refactored `scan_site.py` to build its host-scan set,
  `PAGE_SCANNERS`, and scorecard categories from the registry; removed the
  hardcoded scanner imports and lists. Behavior-identical (verified JSON keys,
  labels, and scorecard categories unchanged on example.com). Added 5 registry
  tests; suite is 56 tests, all pass. See JOURNAL.md 2026-07-01 A1.
- [x] **A0 (done)** Bootstrap Ralph control files. Created PLAN.md, BACKLOG.md,
  JOURNAL.md seeded from repo state; initialized git; verified 51 unit tests
  pass. See JOURNAL.md 2026-07-01.
