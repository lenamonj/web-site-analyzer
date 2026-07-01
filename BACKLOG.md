# BACKLOG.md - Prioritized task list

Statuses: todo, doing, done, blocked. One task per loop iteration. Pick the
highest-priority unblocked `todo`. Keep tasks small enough to finish and verify
in a single run; split anything larger. See PLAN.md for the design each task
serves.

## Phase A - Foundation (registry + contract enforcement)

## Phase B - Self-describing tools

- [ ] **B1 (todo, P2)** Tool-owned category and scope. Give each scanner
  module-level `CATEGORY` and `SCOPE` constants and surface `category` in the
  returned dict. Registry reads these from the module rather than restating
  them. Verify: scorecard categories unchanged; tests updated. Depends on A1.

- [ ] **B2 (todo, P2)** Tool-owned grade. Move the band/score logic into a
  shared `common.grade(verdicts)` helper and have both each tool (emitting its
  own `grade`) and `scan_site.build_scorecard` use it, so no band logic is
  duplicated. Verify: identical scorecard bands before and after on a sample
  run. Depends on A1.

## Phase C - Expansion (new passive dimensions, spec in PLAN.md first)

- [ ] **C1 (todo, P3)** Spec a privacy/tracker scanner in PLAN.md: count
  third-party script and pixel origins and known-tracker hosts from static HTML,
  detect a cookie-consent mechanism, emit per-origin findings. Design only; no
  code this task. Depends on A1, A2 (contract must be enforceable first).

- [ ] **C2 (todo, P3, blocked-by C1)** Implement `scan_privacy.py` to the C1
  spec and the shared contract, register it, add tests and a smoke run.

## Phase D - Reporting automation

- [ ] **D1 (todo, P3)** Spec and prototype generating a first-draft
  `exec_report_data.json` from `<slug>_scan.json` (scorecard + top fails/warns as
  findings), leaving human-authored findings to be layered on top. Design in
  PLAN.md first. Depends on A1.

## Done
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
