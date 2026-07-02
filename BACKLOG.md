# BACKLOG.md - Prioritized task list

Statuses: todo, doing, done, blocked. One task per loop iteration. Pick the
highest-priority unblocked `todo`. Keep tasks small enough to finish and verify
in a single run; split anything larger. See PLAN.md for the design each task
serves.

## Phase A - Foundation (registry + contract enforcement)

## Phase B - Self-describing tools

## Phase C - Expansion (new passive dimensions, spec in PLAN.md first)

## Phase D - Reporting automation

## Phase F - World-class pass (2026-07-02 loop)
- [x] **F11 (done)** HTTP/2 detection via ALPN. Spec: PLAN.md section 22.
  common.tls_info offers h2/http1.1 via ALPN on the existing handshake;
  scan_tls's new http2 check passes on h2, warns on HTTP/1.1-only or no ALPN.
  No extra network traffic. Suite +3 tests; wikipedia.org negotiates h2 live.
- [x] **F12 (done)** Parallel DKIM probes. Spec: PLAN.md section 23. The 14
  selector queries fan out through a bounded ThreadPoolExecutor (order
  preserved); a full dns_email scan now completes in under a second live.
- [x] **F9 (done)** Issue aggregation. Spec: PLAN.md section 20. group_issues
  collapses identical (label, check, verdict) findings across pages into one
  group with the affected-page list; JSON gains issues_grouped and grouped
  totals; digest, console, and draft_report_data consume groups (raw issues
  kept for evidence fidelity and old-scan fallback). Fixes the real defect
  where one template-level issue flooded all 15 draft finding slots.
- [x] **F10 (done)** Run-over-run delta. Spec: PLAN.md section 21.
  diff_issues + attach_delta compare against the previous <slug>_scan.json
  before overwriting; JSON, digest, and console report new vs resolved
  issues. Suite 154 -> 161; live double-run on example.com shows the delta.
- [x] **F7 (done)** Email transport posture. Spec: PLAN.md section 18.
  scan_dns_email gains mta_sts (record via DoH plus the well-known policy
  file and its mode; enforce -> pass), tls_rpt, and bimi checks; all three
  report not-applicable when the domain has no MX. Suite +6 tests; live
  smoke on google.com (MTA-STS enforce pass, TLS-RPT pass, BIMI absent info,
  all true).
- [x] **F8 (done)** Robots disallow-all + anchor integrity. Spec: PLAN.md
  section 19. check_robots_txt now parses the User-agent:* group and FAILS on
  a site-wide Disallow: / (presence-only checking passed it before);
  htmlmeta collects element ids (and legacy a-name) so scan_links'
  new anchor_fragments check warns on in-page #links that scroll nowhere.
  Suite +8 tests.
- [x] **F6 (done)** Header analysis depth. Spec: PLAN.md section 17. check_csp
  now parses directives and grades what the policy enforces for scripts:
  Report-Only delivery, missing script-src/default-src, wildcard script
  origins, unsafe-inline/eval scoped to the script-effective directive
  (unsafe-inline in style-src alone no longer warns). check_cookies now warns
  on cookies without SameSite. Suite 138 -> 140; live smoke on github.com
  (strict CSP passes, JS-readable _octo cookie correctly flagged).
- [x] **F5 (done)** Per-run fetch cache. Spec: PLAN.md section 16. Thread-safe
  memo cache inside common.http_fetch keyed by (method, url, want_body,
  extra_headers), successes only, bounded at 512 entries, off by default;
  scan_site.run and run_review.pipeline enable it for their duration (enable
  keeps entries when already on, so the pipeline's discovery warmup carries
  into the scan). Nav links and shared assets are now fetched once per run
  instead of once per page. Suite 126 -> 132 tests; live run_review on
  example.com green end to end.
- [x] **F1 (done)** Executive report redesign. User directive: the report is
  visually weak; make it look professional and board-ready. Redesigned
  `build_exec_report.py` (masthead banner, at-a-glance tiles, callout bottom
  line, hairline chip tables, footer page numbers, numbered exhibits) with the
  data contract unchanged; fixed an OOXML child-order defect Word is strict
  about; added `test_exec_report.py` (9 tests). Both real datasets render and
  reopen cleanly. Automated PDF verification is blocked by the environment
  (Word COM export hangs even on a plain hello-world control), so the docx
  files went to the user for the visual verdict. Spec: PLAN.md section 12.
- [x] **F2 (done)** Security depth. Spec: PLAN.md section 13. Added
  `scan_page_security.py` (page scope, CATEGORY security: SRI coverage on
  cross-origin script/style, http form actions on https pages, inline event
  handlers, target=_blank rel hygiene), `security_txt` check in
  scan_http_security (RFC 9116 well-known URI), and `caa` check in scan_tls
  (DoH CAA lookup). Registered as the 11th tool; suite 90 -> 106 tests, all
  pass; live smoke on example.com and wikipedia.org (security.txt correctly
  detected as published there).
- [x] **F3 (done)** Architecture/caching depth. Spec: PLAN.md section 14.
  `asset_caching` (per-asset Cache-Control captured during the existing HEAD
  fan-out; uncached-majority warns) and `redirect_chain` checks in
  scan_performance; `host_canonicalization` (apex vs www convergence) in
  scan_crawl. Suite 106 -> 116, all pass; live smoke: example.com correctly
  flagged for serving apex and www without converging.
- [x] **F4 (done)** Static design-signal scanner. Spec: PLAN.md section 15.
  New `scan_design.py` (12th tool, new "design" scorecard category): favicon
  (declared link or default /favicon.ico), theme-color, deprecated
  presentational tags, inline-style density, distinct font families from
  inline and linked CSS (bounded passive GETs), image width/height coverage
  (layout shift). Head checks still run on client-rendered pages; body checks
  go inconclusive. htmlmeta now surfaces meta_theme_color. Suite 116 -> 126,
  all pass; live smoke on wikipedia.org extracted its real font stack.

## Done
- [x] **E1 (done)** Architecture review pass. New host-scoped `scan_crawl.py`
  (robots/sitemap out of the page-scoped scan_seo; no more per-page refetch or
  duplicated warnings), scorecard bucketing fixed to merge by category,
  correctness fixes (tracker suffix matching, viewport maximum-scale parse per
  WCAG 1.4.4, title RCDATA buffering + close(), Referrer-Policy unsafe-url
  warn, common.repo_root/read_target_file dedup), bounded ThreadPoolExecutor
  fan-out in scan_links/scan_performance, and `run_review.py` one-command
  pipeline (discover -> scan -> draft). Specs in PLAN.md sections 9-11. Suite
  73 -> 90 tests, all pass; live smoke on example.com verified end to end. See
  JOURNAL.md 2026-07-01 E1.
- [x] **D1 (done)** Report-data generator. Added `tools/draft_report_data.py`:
  `draft(scan)` turns a `<slug>_scan.json` into a first-draft
  exec_report_data.json - measured scorecard rows and findings from fail/warn
  checks (draft severity fail->High, warn->Medium), leaving recommendations,
  quick_wins, and the CEO narrative for a human. Default output is a
  `.draft.json` so it never clobbers hand-authored data. Spec in PLAN.md section
  8. Added 5 unit tests; end-to-end smoke verified scan -> draft -> rendered docx
  (build_exec_report.py consumed it, wrote a valid 38KB Word file). Suite 73
  tests, all pass. See JOURNAL.md 2026-07-01 D1.
- [x] **C2 (done)** Implement `scan_privacy.py`. Built to the PLAN.md section 7
  spec: page scope, CATEGORY="privacy", regex extraction of script/iframe/img,
  reuse of `scan_dns_email.registrable_domain`, embedded KNOWN_TRACKERS/
  CMP_HOSTS/CONSENT_MARKERS, four checks (third_party_origins info; known_trackers
  and tracking_pixels pass/warn; cookie_consent matrix), client-rendered
  inconclusive path. Registered as a page tool (label "privacy"); scorecard now
  has a 9th "privacy" category. Added 8 offline tests; TestToolContract covers it
  automatically. Suite 68 tests, all pass. Smoke-verified standalone and via the
  orchestrator on example.com (grade Strong, no trackers). See JOURNAL.md
  2026-07-01 C2.
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
