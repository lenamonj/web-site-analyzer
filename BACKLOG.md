# BACKLOG.md - Prioritized task list

Statuses: todo, doing, done, blocked. One task per loop iteration. Pick the
highest-priority unblocked `todo`. Keep tasks small enough to finish and verify
in a single run; split anything larger. See PLAN.md for the design each task
serves.

## Phase J - Automation of the rendered tier (user request 2026-07-02)
- [x] **J1 (done, L)** Automated rendered capture. Spec: PLAN.md section 34.
  New tools/capture_rendered.py drives headless Chrome/Edge over the
  DevTools protocol with a stdlib-only RFC 6455 WebSocket client: rendered
  DOM snapshots for every client-rendered page (refreshed each run) plus
  the CAPTURE.md vitals and contrast measurements for every scanned page
  (capped, dropped pages named), written to the existing section 26/27
  handoff files (merged, never clobbering a manual capture). run_review
  captures and re-scans automatically when a browser is present
  (--no-browser opts out); honest console note when not. scan_site page
  entries now record likely_client_rendered so the plan derives from scan
  JSON. Suite 208 -> 222, all offline (fake CDP session, crafted WS bytes,
  RFC accept-key vector). Live proof both ways: example.com pipeline
  captured real vitals (LCP 64ms, CLS 0, TBT 0, 3 contrast samples) and
  re-scanned in one command; a local SPA fixture went from inconclusive to
  measured rendered_dom verdicts with the planted alt-less image caught as
  a fail and LCP 36ms. Live testing also surfaced and fixed a stale-DOM
  defect: snapshots are now refreshed every run instead of frozen at first
  capture (the page is loaded for metrics anyway, so refresh is free).

## Phase A - Foundation (registry + contract enforcement)

## Phase B - Self-describing tools

## Phase C - Expansion (new passive dimensions, spec in PLAN.md first)

## Phase D - Reporting automation

## Phase I - Live proof of the rendered-evidence tier (user request 2026-07-03)
- [x] **I1 (done, M)** Live round trip of the rendered-evidence tier. Served
  a client-rendered SPA fixture locally; static scan correctly flagged it
  inconclusive; captured the rendered DOM with headless Chrome (--dump-dom,
  the Chrome extension was not connected) and ran the CAPTURE.md vitals and
  contrast snippets in-page (real Chrome measurements: the planted
  gray-on-white violation measured 2.81:1); wrote the manifest/metrics
  handoff; re-scan flipped all six structural scanners to
  evidence_source: rendered_dom (planted alt-less image caught as fail,
  placeholder-only form control warned, JS-injected googletagmanager found
  by privacy - invisible to any static scan, contrast fail graded by
  scan_vitals). The round trip exposed and fixed two real defects in
  anchor_fragments: path-form same-page anchors (/#x) were invisible to the
  bare-# check, and a slashless page URL (http://host) failed the same-page
  comparison against http://host/#x. Suite 188 -> 189; test evidence cleaned
  up. CrUX field data remains out of scope without an API key; crawl ceiling
  and no-JS-execution are charter choices.

## Phase I continued - real-site shakedown (user request 2026-07-03)
- [x] **I2 (done, M)** Real-site shakedown. Ran the full pipeline against
  client-a.example (12 pages; delta correctly identified 17 new-check issues
  vs the July 1 baseline with 0 false resolutions; new checks caught real
  issues the manual review missed: zero asset caching site-wide, CSP
  Report-Only, apex/www non-convergence), python.org (13 pages, no crashes;
  the one "broken link" is genuinely 503), and excalidraw.com (correctly
  flagged client-rendered; headless-Chrome DOM capture produced measured
  rendered_dom verdicts on a real production SPA including its Simple
  Analytics origin). Fixed the three defects the shakedown confirmed, each
  with regression tests: (1) logo-link false positive - anchors wrapping an
  image with alt text now carry that accessible name (was flagged on all 12
  arch pages and 15 python.org pages, and had to be hand-corrected in the
  July 1 report); (2) prose metrics on listing pages - readability now
  reports info when sentences are absurd (wps > 50) or when over half the
  visible words are link text (python.org events pages scored Flesch -13.6);
  (3) covered by I1 (anchor forms). Suite 189 -> 192. Also added .env to
  .gitignore before any key could be committed.

- [x] **I3 (done, M)** CrUX field data. Spec: PLAN.md section 30. The user
  supplied a .env with GOOGLE_API_KEY. Added common.env_value (env then
  .env, never logged) and common.http_post_json (stubbed suite-wide so
  offline tests can never reach the real API or read real keys); new 15th
  tool scan_crux (host scope, performance category) grades origin p75
  LCP/CLS/INP from the Chrome UX Report against published CWV thresholds,
  with honest info paths for no key, origin absent from the dataset (404),
  and unauthorized API (403, with an actionable note). Suite 192 -> 196.
  Live: the key currently returns 403 - the Chrome UX Report API needs to be
  enabled in the key's Google Cloud project; the tool degrades exactly as
  designed until then.

## Phase H - Report communication upgrade (user request 2026-07-03)
- [x] **H4 (done, S)** World-class review pass on the day's work, driven by
  the live client-a.example output. Fixed four accuracy defects in the
  self-writing summary: strengths/weaknesses now sorted by score so
  "strongest area" is true (was registry order - the bottom line claimed
  security posture at 0.97 while three areas measured 1.00); "Worst:"
  softened to the honest "Example:"; the action plan orders by measured
  breadth with an explicit compliance/security tie-break so the site-wide
  consent exposure no longer falls off the capped list behind heading
  cosmetics; cross-page findings map to a clean imperative instead of a raw
  note; 17 more checks in the ACTION map. Suite 203 -> 205. Shipped the full
  client-a.example executive report with today's measurements, authored
  recommendations, and evidence re-verified live (GA4 G-XXXXXXXXXX still
  firing, no consent).
- [x] **H3 (done, M)** Self-writing executive summary and action plan. Spec:
  PLAN.md section 32. draft_report_data now auto-derives, from measured data
  alone: an assessment (strengths = Strong bands + all-Good vitals;
  weaknesses = Weak/Poor bands with counts and the worst finding, via a
  label->category map that fixed a real mismatch where http_security/a11y
  labels never matched security/accessibility categories); an action_plan
  (findings mapped to standard remediation imperatives, fail-first, capped);
  and a real bottom_line naming band, strongest area, and top priority. The
  builder renders an "Executive summary" section (callout + Strengths/
  Priorities two-column table) and a "Recommended plan of action" table when
  no hand-authored recommendations exist. A raw run now ships a useful
  summary and plan with zero hand-editing. Builder suite 13 -> 16, scanner
  199 -> 203. Verified end to end on python.org (5 strengths, readability
  weakness with worst finding, 10-step prioritized plan, all auto-filled).
- [x] **H2 (done, M)** Report Core Web Vitals panel. Spec: PLAN.md section 31.
  New optional web_vitals report field, auto-filled by draft_report_data
  (prefers CrUX real-user field data over lab capture, only measured
  metrics, none when neither exists). Builder add_vitals_panel renders a
  bordered metric strip (value large, label, Good/Needs work/Poor chip) with
  a source line under the scorecard. Surfaces the actual numbers the tool now
  measures instead of burying them in the performance band. Builder suite
  12 -> 13, scanner suite 196 -> 199. Verified end to end: a live python.org
  run auto-filled the panel with real CrUX data (LCP 0.9s, CLS 0.04, INP
  23ms, all Good).
- [x] **H1 (done, M)** Executive report review pass. Spec: PLAN.md section 12
  amendment. Added: optional scope line (pages reviewed, method) under the
  masthead; optional progress strip (resolved vs new since the previous
  review) that draft_report_data auto-fills from the scan delta with an
  honest method string (rendered-DOM capture named only when actually used);
  PAGES REVIEWED tile when scope is present; keep-with-next on section
  headings and exhibit captions; hairline frames around exhibit images. All
  optional and backward compatible; approved design preserved. Builder suite
  9 -> 12, scanner suite 186 -> 188, all green; both previews re-rendered
  and sent to the user.

## Phase G - Path from 680 to 900 (queued 2026-07-02, start 2026-07-03)
Derived one-for-one from the honest capability assessment recorded in
JOURNAL.md. Order: two quick wins first, then the rendering tier (target
~800), then scale and history (target ~900). Spec in PLAN.md before building,
per the standing rule.

- [x] **G1 (done, S)** DKIM selector families. Spec: PLAN.md section 24.
  DKIM_SELECTORS grew 14 -> 26 with documented published names only (Google
  20230601/20161025/20120113, Yahoo s1024/s2048, Fastmail fm1-3, Proton
  protonmail/2/3, Zoho); absence note names the probed families and keeps the
  honest caveat. Suite 164 -> 167; live: gmail.com now found on 20230601 and
  20161025 (previously reported not found), full scan 0.7s.
- [x] **G2 (done, S)** Tracker list depth. Spec: PLAN.md section 25.
  KNOWN_TRACKERS 25 -> 154 documented tracker domains grouped by function
  (analytics, ad-tech incl. SSP/DSP/identity/verification, social, session
  replay, marketing/attribution, A/B testing); CMP_HOSTS 11 -> 20 (Didomi,
  Sourcepoint, consensu.org, and peers); CONSENT_MARKERS +6. Count-floor
  test guards against truncation. Suite 167 -> 170; live: cnn.com static
  HTML now names 7 trackers (4 only findable with the expanded list) and
  detects its consent platform.
- [x] **G3 (done, L)** Rendered-evidence pipeline, part 1. Spec: PLAN.md
  section 26. Tool side built and tested: htmlmeta.page_from_snapshot builds
  a measured context from a captured DOM (network facts stay from the live
  fetch), scan_site.load_rendered_snapshots reads the
  planning/_evidence/rendered/<slug>/manifest.json handoff, and the per-page
  loop runs every structural scanner against the snapshot for
  client-rendered pages (results stamped evidence_source: rendered_dom;
  performance keeps static transfer facts; no snapshot -> inconclusive
  stands). Capture side documented in SKILL.md for the agent's browser pass;
  live capture was not performed this iteration (no browser step in the
  loop), so live verification of the capture step remains with the next
  full site review. Suite 170 -> 174.
- [x] **G4 (done, L)** Rendered-evidence pipeline, part 2. Spec: PLAN.md
  section 27. New 13th tool scan_vitals (category performance, merges into
  the performance bucket) consumes browser-captured metrics from
  rendered/<slug>/metrics.json and grades LCP/CLS/TBT against the published
  Core Web Vitals and Lighthouse thresholds plus WCAG 1.4.3 contrast from a
  computed-style walk (the axe-core approach, chosen over pixel sampling for
  accuracy). tools/CAPTURE.md carries the exact capture snippets and both
  handoff schemas. No capture -> all checks info, grade Not measured,
  nothing estimated. Suite 174 -> 178; live scan confirms an uncaptured
  page leaves the performance grade untouched. Live capture remains the
  agent's browser-pass step at the next full site review (no browser in
  this loop), recorded as pending, not simulated.
- [x] **G5 (done, M)** Findings history ledger. Spec: PLAN.md section 28.
  Append-only planning/_evidence/<slug>_history.jsonl (one line per run:
  measured_at, totals, scorecard bands, slimmed issues); attach_delta now
  prefers the ledger's last entry (scan-JSON fallback for pre-ledger
  evidence dirs); digest gains a Trend section over the last 5 runs naming
  overall-band moves. Suite 178 -> 183; live double-run on example.com shows
  the ledger, the trend section, and the ledger-sourced delta.
- [x] **G6 (done, L)** Polite scale crawling. Spec: PLAN.md section 29. New
  tools/crawler.py (not a scanner): breadth-first same-domain discovery,
  robots.txt compliant via stdlib robotparser (disallows counted, never
  fetched; Crawl-delay raises the 1.0s serial delay), hard 500-page ceiling,
  binary/off-domain/scheme filtering, resumable state file written after
  every page. run_review gains --crawl N / --fresh, replacing sampled
  discovery when the user opts in; the pipeline fetch cache means the scan
  reuses crawl fetches. Docs updated (README, SKILL, CLAUDE scope note).
  Suite 183 -> 186; live capped crawl of example.com behaved exactly
  (1 page, external link excluded, clean stop).

_Phase G complete: G1 through G6 all done, suite green._

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
