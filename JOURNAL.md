# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-01 - A0: Bootstrap Ralph control files

**Task:** A0 (bootstrap). PLAN.md, BACKLOG.md, and JOURNAL.md were all missing,
so per the loop procedure the sole unit of work was to create them.

**What I did:**
- Reoriented from disk: read CLAUDE.md, SKILL.md, and the scanner suite
  (`common.py`, `htmlmeta.py`, `scan_site.py`, `scan_seo.py`, the test file).
  Mapped the as-built architecture and the implicit tool contract.
- Wrote PLAN.md: standing goal, design principles, as-built architecture, the
  normative shared tool contract, the target central-registry design, a phased
  roadmap, and open questions.
- Wrote BACKLOG.md: granular prioritized tasks. Top priority is Phase A
  (central registry A1, then contract-conformance test A2), which closes the one
  explicit gap against the standing-goal contract (scanners are hardcoded in
  `scan_site.py` rather than discovered through a registry).
- Initialized a git repository (none existed). Branch `master`, no remote.

**What I verified:**
- Ran the offline unit suite:
  `python -m unittest test_review_tools` -> `Ran 51 tests ... OK`.
- Confirmed all 8 scanners expose a `scan(...)` returning the checks/verdict
  shape documented in PLAN.md section 4.

**Notes / decisions:**
- Git has no remote, so the loop's `git push` cannot run. Committing locally and
  recording this; no iteration should assume a push succeeded until a remote is
  configured. Logged as an open question in PLAN.md.
- Did not add a NextJS frontend or any app scaffold. This project is a Python
  passive-scanner + docx-report system per its own CLAUDE.md and codebase;
  introducing a frontend would contradict the actual design.

**Next step:** Implement A1 (central tool registry `tools/registry.py`) and
refactor `scan_site.py` to source its scanner set from it with no change to
measured output, then A2 (contract-conformance test).

---

## 2026-07-01 - A1: Central tool registry

**Task:** A1. Remove the hardcoded scanner wiring in `scan_site.py` and make the
orchestrator discover tools through a central registry, per PLAN.md section 5.

**What I did:**
- Added `tools/registry.py`: a declarative `REGISTRY` of 8 `ToolEntry`
  namedtuples (3 host: http_security, tls, dns_email; 5 page: seo, accessibility,
  links, performance, readability), each with `tool_id`, `key`, `module`,
  `scope`, `category`, `label`. Helpers `host_tools()`, `page_tools()`, `by_id()`.
- Refactored `scan_site.py`: dropped the 8 direct scanner imports and the
  hardcoded `PAGE_SCANNERS`/host-scans dict. `PAGE_SCANNERS`, the host-scan set,
  the scorecard categories, and the host-issue collection now derive from
  `registry`. Generalized the host-issue loop (previously per-scanner special
  cases) into one loop that is provably equivalent (see below).
- Added 5 tests (`TestRegistry`) asserting the registry lists all 8 scanners,
  every entry exposes a callable `scan`, `scan_site.PAGE_SCANNERS` equals the
  registry projection, scorecard categories come from the registry, and `by_id`
  round-trips.

**Why the generalized host loop is safe:** I traced every `scan()` return shape.
`http_security` and `dns_email` always return a `checks` map (or, on a
`_safe_scan` exception, `{ok:false, error}` with no verdict); only `scan_tls`
emits a bare top-level `verdict` (on handshake failure). So the new
`if "checks" in sr ... elif verdict in (warn,fail)` loop reproduces the old
behavior exactly for all three.

**What I verified:**
- `python -m unittest test_review_tools` -> `Ran 56 tests ... OK` (was 51).
- Smoke run `scan_site.py https://example.com`: completed, all 8 categories
  present. Confirmed the combined JSON is shape-identical to before: `host_scans`
  keys = {http_security, tls, dns_email}, page-scan keys unchanged, scorecard
  categories unchanged (security correctly mapped from http_security), issue
  labels unchanged (accessibility still tagged `a11y`).

**Notes:** No design shift; the registry was already the planned design. Marked
PLAN.md gap #1 closed and updated section 5 to "implemented". Git still has no
remote, so commit is local only.

**Next step:** Implement A2 (contract-conformance test) using `registry.REGISTRY`
to enforce the section-4 contract for every current and future tool.

---

## 2026-07-01 - A2: Contract-conformance test

**Task:** A2. Enforce the PLAN.md section-4 contract for every registered tool
with an offline test, so a new or edited scanner that breaks the shape fails
locally instead of silently.

**What I did:**
- Added `TestToolContract` to `test_review_tools.py` with canned network stubs
  (`_canned_fetch`/`_canned_tls`/`_canned_doh` and `_down_*` variants). All
  scanners reach the network only via `common.http_fetch`/`common.tls_info`/
  `common.doh_query` (plus `scan_tls._probe_legacy`, a raw socket), so patching
  those four in setUp/tearDown makes the whole suite run with zero real requests.
- Three tests, each iterating `registry.REGISTRY` (all 8 tools):
  1. success shape - stubbed-healthy target, asserts dict, `tool == tool_id`,
     every check has a verdict in {pass,warn,fail,info} and a string note, and a
     non-empty `checks` map.
  2. no tool raises on network failure - stubbed-down primitives, asserts each
     tool returns a conformant dict without raising.
  3. `_safe_scan` wraps a raising tool as `ok:false` + error, for all 8 ids.

**Design correction recorded:** the test surfaced that PLAN.md section 4
overstated the contract. `scan_http_security` and `scan_dns_email` do NOT emit a
top-level `ok` on success; they always return a `checks` map and degrade to
warn/fail verdicts rather than failing hard. Amended section 4 so the universal
success invariant is "non-empty `checks`", not "`ok:true`". No scanner code
changed - the contract now matches the implementation instead of the reverse.

**What I verified:**
- `python -m unittest test_review_tools` -> `Ran 59 tests ... OK` (was 56).
- Negative check (throwaway, not committed): confirmed `_assert_conformant`
  rejects an invalid verdict, an `ok:false` without an error, and a mismatched
  tool id. The test is not vacuous.

**Notes:** Phase A (registry + contract enforcement) is now complete (A0, A1,
A2 done). Git still local-only (no remote).

**Next step:** B1 - make each scanner declare its own `CATEGORY` and `SCOPE`
module constants and surface `category` in its return, with the registry reading
that metadata from the module instead of restating it.

---

## 2026-07-01 - B1: Tool-owned category and scope

**Task:** B1. Move category/scope from the registry into the scanner modules and
surface `category` in each tool's output, so tools are self-describing (closes
PLAN.md section 4 gap #2 for category; the contract requires a category in the
output).

**What I did:**
- Added `CATEGORY` and `SCOPE` module constants to all 8 scanners
  (security/tls/dns_email = host; seo/accessibility/links/performance/
  readability = page).
- Made each scanner self-describing without editing its many return sites:
  renamed the existing `scan(...)` to `_scan(...)` and added a uniform thin
  public wrapper `scan(*args, **kwargs)` that calls `_scan` and stamps
  `result["category"] = CATEGORY`. One wrapper per module stamps every return
  path (for example scan_readability's three returns) with no per-return edits.
- Refactored `registry.py`: a `_entry(tool_id, key, module, label)` helper builds
  each `ToolEntry` reading `module.SCOPE` and `module.CATEGORY`, so the registry
  no longer restates scope/category.
- Tests: strengthened `TestToolContract.test_success_shape...` to assert the
  surfaced `category` matches the registry, and added
  `TestRegistry.test_scope_and_category_are_read_from_the_module`.

**Why the wrapper (not editing each return):** returns vary in shape (single-line
failures, multiline successes, the 12-space inline readability case). A single
wrapper is lower-risk than ~16 return edits and guarantees uniform stamping. The
wrapper does not catch exceptions - that stays the orchestrator's `_safe_scan`
job - so a raising `_scan` still surfaces as ok:false via the existing path.

**What I verified:**
- `python -m unittest test_review_tools` -> `Ran 60 tests ... OK` (was 59).
- Smoke run `scan_site.py https://example.com`: scorecard categories unchanged
  (8, identical set), and every tool's JSON now carries `category`
  (http_security->security, tls->tls, dns_email->dns_email, page tools direct).

**Notes:** Grade is still computed centrally in `scan_site.build_scorecard`;
moving it to a shared helper the tools also emit is B2. Git still local-only.

**Next step:** B2 - extract the band/score logic into `common.grade(verdicts)`,
have each tool emit its own `grade`, and have `scan_site.build_scorecard` reuse
the same helper so no band logic is duplicated. Verify identical bands before and
after on a sample run.

---

## 2026-07-01 - B2: Tool-owned grade

**Task:** B2. Put the band/score logic in one place and have every tool emit its
own grade, so a tool's output is fully self-describing (category + grade +
findings + evidence) and no band logic is duplicated. Closes the rest of PLAN
section 4 gap #2.

**What I did:**
- Moved `_grade` and `_verdicts_of` from `scan_site.py` into `common.py` verbatim
  as `common.grade(verdicts)` and `common.verdicts_of(scan_result)`.
- Updated `scan_site.build_scorecard` to call `common.grade`/`common.verdicts_of`
  and deleted the local copies.
- Extended each scanner's `scan()` wrapper (from B1) to also stamp
  `result["grade"] = common.grade(common.verdicts_of(result))`. One line per
  wrapper; every tool now carries its own grade on every return path.
- Tests: repointed `test_grade_bands` and `test_verdicts_of...` from
  `site._grade`/`site._verdicts_of` to the `common.*` functions, and
  strengthened the contract test to assert each tool surfaces a `grade` dict with
  a band in {Strong, Adequate, Weak, Poor, Not measured}.

**What I verified:**
- `python -m unittest test_review_tools` -> `Ran 60 tests ... OK`.
- Smoke run `scan_site.py https://example.com`: scorecard bands byte-identical to
  the B1 run (overall Adequate 0.74; security Poor, tls/dns_email/links/
  performance Strong, seo Adequate, accessibility Strong, readability Not
  measured). Each tool's JSON now carries a matching `grade` (single-page run, so
  per-tool grade equals its category grade, e.g. http_security Poor 0.07).

**Notes:** Phase B (self-describing tools) is complete (B1, B2 done). The band
logic now lives once in `common.grade`; the scorecard and the per-tool grades
grade different verdict sets but share that single function. Git still
local-only.

**Next step:** Phase C. Start with C1 - spec a privacy/tracker scanner in
PLAN.md (third-party script/pixel origins and known-tracker hosts from static
HTML, cookie-consent detection, per-origin findings). Design only; the
implementation is C2. Keep it within the passive, stdlib-only constraints.

---

## 2026-07-01 - C1: Spec scan_privacy (design only)

**Task:** C1. Design the first Phase C dimension - a passive privacy/tracker
scanner - in PLAN.md before any code, per the loop's design-precedes-build rule.

**What I did (design only, no scanner code):**
- Confirmed data dependencies against the real code first (no fabrication):
  `htmlmeta.parse_html` exposes `links` (rel/href) and `images` (src, no
  dimensions) but not `<script>`/`<iframe>` srcs; `scan_performance` already
  extracts scripts by regex over the raw body and reuses
  `scan_dns_email.registrable_domain` for first-vs-third-party. So `scan_privacy`
  can own small regex extractors (script/iframe/img dimensions) and reuse
  `registrable_domain`, with no change to the shared parser.
- Wrote PLAN.md section 7: full `scan_privacy` spec - page scope,
  CATEGORY="privacy", contract-conformant returns, passive static-only
  extraction, curated KNOWN_TRACKERS/CMP_HOSTS/CONSENT_MARKERS constants (matches
  reported as observations, not benchmarks), four checks (third_party_origins
  info; known_trackers pass/warn; tracking_pixels pass/warn; cookie_consent
  pass/warn/info matrix), client-rendered inconclusive handling, grade via the
  shared wrapper, the C2 test list, and explicit non-goals.
- Renumbered "Open design questions" to section 8 and refreshed the stale A2 note
  in section 5.

**What I verified:**
- Design task, so no scanner behavior to run. Ran `python -m unittest
  test_review_tools` -> `Ran 60 tests ... OK` to confirm the docs-only change
  broke nothing.
- Cross-checked every data source the spec relies on exists (htmlmeta fields,
  scan_performance regex pattern, `registrable_domain`).

**Notes:** C2 is now unblocked. Git still local-only.

**Next step:** C2 - implement `scan_privacy.py` to the section 7 spec and the
shared contract, register it as a page tool (label "privacy"), and ship the
offline unit tests plus a smoke run on example.com.

---

## 2026-07-01 - C2: Implement scan_privacy

**Task:** C2. Build the privacy/tracker scanner designed in PLAN.md section 7.

**What I did:**
- Added `tools/scan_privacy.py` (page scope, CATEGORY="privacy"), following the
  spec and the B1/B2 wrapper pattern. Pure, passive, stdlib-only: regex extractors
  for `<script>`/`<iframe>`/`<img>` over the raw body (dimensions for pixels),
  reuse of `parsed` links/images, `scan_dns_email.registrable_domain` for
  first-vs-third-party, and embedded KNOWN_TRACKERS/CMP_HOSTS/CONSENT_MARKERS
  constants. Four checks: `third_party_origins` (info), `known_trackers`
  (pass/warn), `tracking_pixels` (pass/warn), `cookie_consent` (pass/warn/info
  matrix). Client-rendered pages mark the resource checks inconclusive.
- Registered it in `registry.py` as a page tool (import + one `_entry`, label
  "privacy"). No orchestrator edit needed - the registry seam from A1 did its job.
- Tests: added `TestPrivacy` (8 tests) covering first-vs-third-party, tracker
  match, 1x1 pixel detection, CMP/marker detection, the consent matrix, a full
  flagged scan, a clean scan, and the client-rendered path. Renamed the registry
  count test and updated it to 9 tools / 6 page tools.

**What I verified:**
- `python -m unittest test_review_tools` -> `Ran 68 tests ... OK` (was 60).
  `TestToolContract` now sweeps 9 tools and scan_privacy conforms.
- Smoke: standalone `scan_privacy.py https://example.com` -> ok, category privacy,
  grade Strong, checks {third_party_origins info, known_trackers pass,
  tracking_pixels pass, cookie_consent info} (correct for a resource-free page).
  Via `scan_site.py`: scorecard now lists a 9th "privacy" category and the
  page_scan carries the privacy result with grade Strong.

**Notes:** Phase C's first dimension is complete (C1 spec, C2 build). Adding this
dimension touched exactly one new file plus one registry line plus tests - the
orchestrator was untouched, confirming the Phase A/B design goals. Git still
local-only.

**Next step:** D1 (Phase D) - spec and prototype generating a first-draft
`exec_report_data.json` from `<slug>_scan.json` (scorecard + top fails/warns as
findings), leaving human-authored findings to layer on top. Design in PLAN.md
first, then a minimal generator with tests.

---

## 2026-07-01 - D1: Report-data generator (spec + build)

**Task:** D1. Spec and build a generator that drafts `exec_report_data.json` from
a scan result, filling the mechanical parts and leaving judgement to a human.
Small and well-bounded (smaller than C2), so spec + build fit one iteration; not
split.

**What I did:**
- Read `build_exec_report.py` first to pin the exact consumed schema: it uses
  `data.get(...)` with defaults and skips empty sections, and `scorecard.overall`
  must be a band STRING (not the scan's nested dict). That drove the design.
- Wrote PLAN.md section 8 (spec) and added `tools/draft_report_data.py`:
  `draft(scan)` maps scan `host`/`target`/`measured_at_utc` to site/target/date,
  the scorecard categories to `{category, band, detail}` rows with the overall
  band as a string, and `issues.fail`+`issues.warn` (fails first, capped at
  MAX_FINDINGS=15) to findings with a transparent draft severity
  (fail->High, warn->Medium) and evidence split from the issue's `scan` label.
  `recommendations` and `quick_wins` are left `[]` for a human. `bottom_line` is a
  measured one-liner explicitly marked DRAFT. Default output is a `.draft.json`
  so it never clobbers hand-authored data.
- Added `TestDraftReportData` (5 tests): top-level fields, overall-band-as-string,
  findings severity/ordering/evidence, schema completeness, and the findings cap.

**What I verified:**
- `python -m unittest test_review_tools` -> `Ran 73 tests ... OK` (was 68).
- End-to-end smoke (in scratchpad): `scan_site.py` -> `draft_report_data.py` ->
  `build_exec_report.py` produced a valid 38 KB .docx from the draft (12 findings,
  9 scorecard rows including privacy, overall Adequate). The builder consumed the
  draft with no missing keys, which is the real schema-conformance proof.

**Notes:** D1 was the last backlog item. Git still local-only.

---

## 2026-07-01 - LOOP COMPLETE

BACKLOG.md has no unblocked `todo` items remaining, so per the stop condition I am
not inventing busywork. Summary for the human reviewer:

**Delivered this loop (A0 -> D1), each verified and committed atomically:**
- A0 bootstrap: PLAN.md / BACKLOG.md / JOURNAL.md seeded; git initialized.
- A1: central tool registry; the orchestrator discovers scanners instead of
  hardcoding them.
- A2: offline contract-conformance test across the whole registry.
- B1: tools declare their own `CATEGORY`/`SCOPE`; a `scan()` wrapper makes output
  self-describing.
- B2: single band logic in `common.grade`; every tool emits its own grade.
- C1/C2: designed and built `scan_privacy`, a new passive dimension, added with
  one new file plus one registry line (orchestrator untouched) - proof the
  Phase A/B design met its goal.
- D1: `draft_report_data.py`, drafting the executive-report JSON from the scan.

**State:** 73 offline tests pass; a full scan -> draft -> docx pipeline is smoke-
verified; the working tree is clean; the build is green.

**No blocked items.**

**Open design questions (PLAN.md section 9), for a human to decide:**
- Whether to unify the host vs page `scan` signatures (currently kept split).
- Configuring a git remote so the loop can push (commits are local-only today).

**Candidate future work (NOT added as tasks; a human should prioritize):**
- More passive dimensions noted in Phase C: content/IA structural checks,
  robots/sitemap depth.
- Wire `draft_report_data.py` into the `review-site` SKILL.md process so a run
  auto-drafts the report data before the human refines it.

RALPH: NOTHING TO DO

## 2026-07-01 - E1: Architecture review pass (crawl extraction, scorecard merge, correctness fixes, concurrency, pipeline)

**Task:** Full design/architecture review of the analyzer, fixing the defects
found and closing the biggest capability gaps. Specs added to PLAN.md sections
9-11 before implementation, per convention.

**What I did:**
- `scan_crawl.py` (new, host-scoped, CATEGORY "seo"): robots.txt and sitemap
  checks moved out of the page-scoped `scan_seo`, which had been refetching both
  files once per page, duplicating identical warnings per page, and skewing the
  seo grade by page count. Registered as the 4th host tool.
- `scan_site.build_scorecard`: buckets both scopes by `category` and merges,
  fixing the latent key-vs-category inconsistency where a page bucket silently
  overwrote a host bucket with the same name. crawl + seo now share "seo".
- Correctness fixes: `scan_privacy` tracker matching is exact/suffix host match
  (a substring test also matched lookalikes like notfacebook.com);
  `scan_accessibility` viewport check parses maximum-scale and warns below 2
  per WCAG 1.4.4 (the substring test false-positived on maximum-scale=10);
  `htmlmeta` buffers <title> text, calls close() so an unclosed title is
  flushed, and bounds the malformed case; `scan_http_security` warns on
  Referrer-Policy: unsafe-url; `common.repo_root()`/`read_target_file()`
  deduplicate target resolution (discover_pages no longer mkdirs the evidence
  dir as a side effect of finding the repo root).
- Concurrency: `scan_links` and `scan_performance` run their fan-out through a
  bounded ThreadPoolExecutor (8 workers, executor.map preserves order), so a
  page of slow links no longer takes minutes serially.
- `run_review.py` (new): one-command pipeline discover -> scan -> digest ->
  draft exec_report_data. Not a scanner; composes registered tools only.

**What I verified:**
- Suite grew 73 -> 90 tests, all pass, still offline and <0.1s.
- Live smoke: `python run_review.py https://example.com` wrote scan JSON,
  digest, and draft; draft rendered through build_exec_report.py (38KB docx).
- Two-page live scan shows crawl issues once per run (not once per page) and a
  merged seo bucket.

**Next:** the docs (README, CLAUDE.md, SKILL.md) were stale before this pass
(no privacy, registry, or draft generator mentions); updated in the same
commit. Remaining candidate: per-run resource cache so shared assets are not
re-measured on every page.

---

## 2026-07-02 - F1: Executive report redesign (user directive)

**Task:** F1. Mid-loop the user directed: the executive report "is weak and
should look a lot better and more professional". Redesigned the document
system in `build_exec_report.py` with the JSON data contract unchanged. Spec
recorded as PLAN.md section 12.

**What I did:**
- Rebuilt the document design: navy masthead banner with kicker and meta line,
  thin gold rule, an at-a-glance tile strip (overall posture, findings count
  with severity breakdown, recommendations count, areas measured - every value
  counted from the data), bottom line as a shaded callout with a navy left
  bar, hairline-ruled tables (navy header row, no full grid, roomy tblCellMar
  padding, vertical centering, header repeat, rows kept whole), posture and
  severity color chips in a muted print-safe palette, footer with a real PAGE
  field, and an evidence appendix with numbered exhibits.
- Fixed a real OOXML defect the redesign introduced and the tests could not
  see: manually built elements (tcBorders, tblCellMar, pBdr, rPr spacing) were
  appended at the end of their parent property elements, but ECMA-376 requires
  a strict child order. python-docx tolerates any order, Word does not. All
  manual inserts now go through insert_element_before with the correct
  successor lists.
- Added `test_exec_report.py` (9 tests, skips when python-docx is absent):
  masthead, tile counts, callout, chip fills, severity and rank ordering,
  footer PAGE field, exhibit numbering, minimal-data build.

**What I verified:**
- 9/9 builder tests pass; the 90-test scanner suite is unaffected.
- Both real datasets (client-a hand-authored with images and code
  exhibits; client-b machine draft) render without error and reopen cleanly.
- Visual PDF verification was attempted via Word COM and is blocked by the
  environment, not the documents: a plain hello-world docx built with pure
  python-docx defaults also hangs Word's ExportAsFixedFormat here (bisected
  across 11 feature-knockout variants plus the control; switching
  ActivePrinter to Microsoft Print to PDF did not unstick it). The docx files
  were handed to the user for the visual check instead.

**Notes:** feedback recorded in auto-memory (exec-report-design-bar) so the
bar persists across sessions.

---

## 2026-07-02 - F2: Security depth (security.txt, SRI, CAA, page hygiene)

**Task:** F2 per PLAN.md section 13, written and built this iteration while
the F1 render check ran in the background.

**What I did:**
- New `scan_page_security.py` (page scope, CATEGORY security - merges with the
  host header checks in the scorecard): subresource_integrity (cross-origin
  script/style without integrity -> warn), insecure_form_action (http action
  on an https page -> fail), inline_event_handlers (info; they block a strict
  CSP), target_blank_rel (info; modern browsers imply noopener). Client-
  rendered pages mark markup checks info. Registered as the 11th tool.
- `scan_http_security.check_security_txt`: RFC 9116 well-known URI; pass only
  on 200 with a Contact line (a SPA catch-all 200 is not counted); absence is
  info, never graded down.
- `scan_tls.check_caa`: one DoH CAA lookup on the registrable domain; present
  -> pass listing issuers, absent or failed -> info.

**What I verified:**
- Suite 90 -> 106 tests, all pass, still offline and fast.
- Live smoke: example.com (clean page: SRI info, handlers pass, CAA info) and
  wikipedia.org (security.txt correctly detected as published; 1 of 3
  target=_blank links flagged; form action pass).

**Next step:** F3 (architecture/caching depth) and F4 (static design-signal
scanner) per BACKLOG; get the user's visual verdict on the redesigned report.

---

## 2026-07-02 - F3 + F4: architecture/caching depth and the design dimension

**Task:** F3 and F4 per PLAN.md sections 14 and 15 (both spec'd before build).

**What I did (F3, no new tool):**
- `scan_performance`: `_measure` now captures each asset's Cache-Control
  during the existing HEAD fan-out; new `asset_caching` check warns when the
  majority of measured 200 assets have no usable caching lifetime (no
  max-age, not immutable, or no-store/no-cache); new `redirect_chain` check
  warns at two or more redirects before the final URL.
- `scan_crawl`: new `host_canonicalization` check fetches https on the apex
  and www variants (only when the target IS apex or www; subdomain sites are
  not applicable) and warns when both serve 200 without converging on one
  canonical host.

**What I did (F4):**
- New `scan_design.py`, the 12th registered tool and a new "design" scorecard
  category: favicon (declared icon link, falling back to one passive check of
  /favicon.ico), theme-color, deprecated presentational tags, inline-style
  density (over 30 warns), distinct non-generic font families from inline
  style blocks plus up to 5 linked stylesheets (bounded passive GETs), and
  image width/height coverage (layout-shift risk when the majority lack
  dimensions). Head-level checks run even on client-rendered pages (the
  shipped head is static); body-derived checks go inconclusive there.
- `htmlmeta.parse_html` now surfaces `meta_theme_color` (shared-parser job).

**What I verified:**
- Suite 106 -> 126 tests, all pass, offline, <0.1s.
- Live smokes: example.com apex/www correctly flagged as non-converging (a
  true finding); wikipedia.org design scan extracted its real font stack
  (linux libertine, source serif pro, montserrat) from linked CSS and graded
  Strong; full `scan_site.py` run shows a 10-category scorecard with design
  present and page_security merged into security.

**Next step:** all Phase F backlog items are done. Remaining candidates: the
user's visual verdict on the F1 report design, wiring the new dimensions into
SKILL.md/README wording, and the deferred per-run resource cache.

---

## 2026-07-02 - F5: per-run fetch cache + docs sync + review pass

**Task:** F5 (PLAN.md section 16, spec'd first), plus the docs sync committed
separately and an adversarial review of the F2-F4 code by a reviewer agent.

**What I did:**
- `common.http_fetch` gained an explicit per-run memo cache: thread safe
  (fan-outs run in ThreadPoolExecutor), keyed by (method, url, want_body,
  extra_headers), caches complete successes only (a transient failure never
  poisons the run), bounded at 512 entries, off by default. `scan_site.run`
  and `run_review.pipeline` enable it for their duration; enable keeps
  existing entries when already on so the pipeline's discovery fetches
  (homepage, robots.txt) are reused by the scan. Cached responses are treated
  as read-only by scanners.
- Why: nav links repeat on every page and scan_links re-probed them per page;
  shared stylesheets were re-HEADed by scan_performance and re-read by
  scan_design per page. One observation per URL per run is both faster and
  politer to the target.
- Docs sync: README (tool table, category list, 126-test count, structure,
  builder test suite), SKILL.md check list, and CLAUDE.md scanner summary now
  match the 12-tool reality.

**What I verified:**
- Suite 126 -> 132 tests (cache hit, HEAD/GET separation, failure-not-cached,
  idempotent enable, run disables afterward), all green. Caught and fixed a
  test that passed for the wrong reason (missing urllib import made the fake
  opener raise NameError, which http_fetch also treats as failure).
- Live `run_review.py https://example.com` end to end with the cache on:
  scan, digest, and draft all written; scorecard unchanged.

---

## 2026-07-02 - Review pass: dedup integration proof + favicon fallback fix

**Task:** close the loop with verification work: an orchestrator-level
integration test for the fetch cache, plus both a hand review and a reviewer
agent pass over the F2-F4 code (regex robustness on messy HTML, crash paths,
wrong verdicts, contract violations).

**What I did:**
- `TestRunLevelDedup`: runs the real `http_fetch` over a fake counting opener
  (TLS and DoH stubbed) through a full two-page `scan_site.run` and asserts
  no HEAD request is ever repeated within the run, and that the cache is
  disabled afterward. This is the orchestrator-level proof the unit tests
  could not give (they stub above the cached layer).
- Fixed the one real defect the review found: `scan_design.check_favicon`
  would falsely warn "no favicon" on servers that reject HEAD (405/501) when
  no icon link is declared; it now falls back to GET, the same pattern
  scan_links uses. Test added.
- Reviewed the remaining flagged spots: quoted-attribute regexes miss
  unquoted attributes (false negatives only, acceptable for a passive
  scanner), list-valued headers are handled, DoH CAA/NXDOMAIN paths degrade
  to info, IP-literal hosts degrade to info in canonicalization, and
  scheme-relative and data: URLs resolve or are skipped correctly. No crash
  paths or false-positive verdicts found.

**Reviewer-confirmed defect, fixed (the important one):** every regex-based
scanner anchored attribute names with `\b`, which also matches after a
hyphen, so `data-action` / `data-src` / `data-width` satisfied the regex for
`action` / `src` / `width`. Concrete impact: a Stimulus-style
`<form data-action="submit->x" action="http://...">` reported a false PASS
on a form posting over plain HTTP (the `data-action` match shadowed the real
action), and consent-gated `<script type="text/plain" data-src=...>` tags
(the standard Cookiebot/OneTrust pattern) were counted as live cross-origin
scripts. Fixing it exposed a second layer the suggestion missed: tag-capture
regexes used `[^>]*`, so a `>` inside a quoted attribute value truncated the
attribute region entirely. Both fixed everywhere: attribute names are now
anchored `(?<![-\w])`, and all tag-attribute captures go through the new
quote-aware `common.tag_attrs_re` (page_security, privacy, design,
performance) including the mixed-content regex in scan_links (which had both
defects: `data-src="http://..."` lazy-loads flagged as mixed content).
Five regression tests reproduce the reviewer's exact failing inputs.

**What I verified:** suite 132 -> 138 tests, all pass; builder suite 9/9;
working tree clean after commit.

---

## 2026-07-02 - F6: header analysis depth (CSP directives, SameSite)

**Task:** F6 per PLAN.md section 17. The CSP check graded only presence and
unsafe-inline/eval anywhere in the header; the cookie check ignored SameSite.

**What I did:** `_parse_csp` parses the policy into directives (first
occurrence wins, list-valued headers combine). `check_csp` now warns on
Report-Only-only delivery, on a policy with no script-src and no default-src
fallback, on wildcard script origins (*, http:, https:), and on
unsafe-inline/eval in the directive that actually governs scripts - so
unsafe-inline confined to style-src no longer produces a script warning, and
an explicit safe script-src overrides a weak default-src. `check_cookies`
adds a SameSite finding: Secure/HttpOnly gaps stay the stronger warn,
otherwise undeclared SameSite warns with the cookie names.

**What I verified:** suite 138 -> 140 tests, all pass. Live smoke on
github.com: its strict CSP passes the deeper analysis; its intentionally
JS-readable _octo cookie is flagged for missing HttpOnly (a true
observation).

---

## 2026-07-02 - F7 + F8: email transport posture; robots disallow-all and anchor integrity

**Task:** F7 and F8 per PLAN.md sections 18 and 19 (spec'd first). User
directed: visual report verdict deferred, keep improving other areas.

**F7 (scan_dns_email):** mta_sts (DoH TXT on _mta-sts.<domain>, then the
well-known policy file; enforce mode -> pass, testing/unreachable/absent ->
info with the specific gap), tls_rpt (_smtp._tls TXT), bimi (default._bimi
TXT). All three not-applicable when the domain has no MX. Absence is an
observation, not a downgrade, consistent with security.txt/CAA.

**F8:** `check_robots_txt` parses the User-agent:* group (consecutive UA
lines share a group; a bare Allow: / reopens) and now FAILS on a site-wide
Disallow: / - the presence-only check literally passed a robots.txt that
blocks every search engine. htmlmeta collects element ids plus legacy
<a name> targets; scan_links' new `anchor_fragments` check warns when
in-page #links point at ids that do not exist ('#' and '#top' excluded).

**What I verified:** suite 140 -> 154 tests, all pass. Live smoke on
google.com: MTA-STS enforce pass, TLS-RPT pass, BIMI absent info - all
verified true observations. README and SKILL.md check lists updated in the
same commits.

---

## 2026-07-02 - F9 + F10: issue aggregation and run-over-run delta

**Task:** F9 and F10 per PLAN.md sections 20 and 21. Both target the
analyst-facing output rather than new measurements.

**F9 (aggregation):** page-scoped checks emitted one identical issue per
affected page, so a single template defect repeated through the digest and,
because draft_report_data caps findings at 15, flooded every slot of the
executive draft. `scan_site.group_issues` collapses identical (label, check,
verdict) findings into one group carrying the affected pages; the JSON gains
`issues_grouped` plus grouped totals (raw issues kept for evidence fidelity),
the digest and console print one line per distinct defect with page
attribution, and the draft consumes groups (falling back to raw issues for
older scan files).

**F10 (delta):** `diff_issues` compares (scan, check, verdict) key sets
between the previous `<slug>_scan.json` and the current run;
`attach_delta` loads the old file before overwriting. JSON, digest, and
console now state what is new and what was resolved since the prior scan,
matching the tool's actual usage loop (scan, fix, re-scan).

**What I verified:** suite 154 -> 161 tests, all pass. Live: two consecutive
scans of example.com produce grouped issue lines with page counts and a
correct "0 new, 0 resolved" delta citing the previous run's timestamp.

---

## 2026-07-02 - F11 + F12: HTTP/2 via ALPN, parallel DKIM probes

**F11:** `common.tls_info` now offers h2/http1.1 through ALPN on the one
handshake the analyzer already performs and reports the negotiated protocol;
`scan_tls` gains an `http2` check (h2 -> pass; HTTP/1.1-only or no ALPN ->
warn, requests serialize without multiplexing). Zero additional network
traffic. Guarded for OpenSSL builds without ALPN.

**F12:** the 14 DKIM selector queries fan out through a bounded
ThreadPoolExecutor (order preserved via executor.map), the same pattern as
the link/resource fan-outs. A full dns_email scan (8 checks, 14 selector
probes plus the transport checks) measured 0.4s live against google.com.

**Verified:** suite 161 -> 164 tests, all pass; wikipedia.org negotiates h2
live; README/SKILL check lists updated.

---

## 2026-07-03 - G1: DKIM selector families

**Task:** G1 per PLAN.md section 24 (spec'd first). Phase G loop, iteration 1.

**What I did:** extended DKIM_SELECTORS from 14 to 26 with documented,
published selector names only: Google's date rotation (20230601, 20161025,
20120113), Yahoo key-size selectors (s1024, s2048), Fastmail (fm1-fm3),
Proton Mail (protonmail, protonmail2, protonmail3), and Zoho. No invented
date generation; random per-account selectors (Amazon SES tokens) are
unguessable by design and the absence note says so, now naming the probed
families. The F12 parallel fan-out keeps wall-clock flat.

**What I verified:** suite 164 -> 167 tests, all pass. Live: gmail.com now
reports DKIM pass with selectors 20230601 and 20161025 found; the previous
list reported "not found on probed selectors" for the same domain. Full
dns_email scan measured 0.7s.

---

## 2026-07-03 - G2: tracker list depth

**Task:** G2 per PLAN.md section 25 (spec'd first). Phase G loop, iteration 2.

**What I did:** expanded the embedded privacy reference lists to the level of
the public tracker datasets while staying offline-only: KNOWN_TRACKERS grew
from 25 to 154 documented tracker registrable domains, grouped and commented
by function (analytics including Adobe's omtrdc/demdex/2o7 family;
advertising ad-tech including SSPs, DSPs, identity and data brokers, and
verification vendors; social widgets; session replay; marketing automation
and attribution; A/B testing). CMP_HOSTS grew to 20 (Didomi, Sourcepoint,
consentmanager, the IAB consensu.org domain, CookieHub, CookieFirst,
Cookie-Script, Civic) and CONSENT_MARKERS gained the matching DOM markers.
Matching stays exact-or-subdomain; a match remains an observation.

**What I verified:** suite 167 -> 170 (count-floor test guards truncation,
subdomain-vs-lookalike matching, expanded CMP/marker detection). Live:
cnn.com's static homepage now names 7 trackers across four categories, four
of which only the expanded list can identify, and its consent platform is
detected.

---

## 2026-07-03 - G3: rendered-evidence pipeline, part 1 (tool side)

**Task:** G3 per PLAN.md section 26 (spec'd first). Phase G loop, iteration 3.

**What I did:**
- Handoff contract: the agent's browser pass writes one HTML file per
  client-rendered page plus `planning/_evidence/rendered/<slug>/manifest.json`
  (captured_with, viewport, url -> file + captured_at_utc). Documented in
  SKILL.md with the exact schema; the scanners never launch a browser.
- `htmlmeta.page_from_snapshot(url, html, network_res)`: a page context whose
  body is the rendered DOM while status, headers, and final_url stay from
  the live fetch; the render assessment is stamped source =
  rendered_dom_snapshot.
- `scan_site`: `load_rendered_snapshots(slug)` reads the manifest (absence is
  the normal case); the per-page loop hands the snapshot context to every
  page scanner except performance when the page is client-rendered and a
  capture exists. Results carry `evidence_source: rendered_dom`, the page
  entry records `rendered_snapshot_used`, and the digest header counts
  rendered-evidence pages. Without a capture the inconclusive verdicts stand
  untouched - nothing is inferred.

**What I verified:** suite 170 -> 174, all pass, including an orchestrated
run where a canned SPA shell plus a snapshot yields measured seo and
accessibility verdicts stamped rendered_dom while performance keeps the
static transfer context, and the no-snapshot path stays inconclusive. The
live capture step is the agent's browser pass and was not exercised in this
iteration; it is recorded as pending for the next full site review rather
than simulated.

---

## 2026-07-03 - G4: rendered-evidence pipeline, part 2 (web vitals + contrast)

**Task:** G4 per PLAN.md section 27 (spec'd first). Phase G loop, iteration 4.

**What I did:**
- Handoff: `planning/_evidence/rendered/<slug>/metrics.json` carries
  browser-measured lcp_ms, cls, tbt_ms, and a contrast sample per page.
  `tools/CAPTURE.md` (new) holds the exact JS snippets: buffered
  PerformanceObserver for largest-contentful-paint, layout-shift excluding
  hadRecentInput, longtask with the 50 ms TBT subtraction, and a
  computed-style WCAG 1.4.3 contrast walk (the axe-core approach; chosen
  over screenshot pixel sampling because gradients and antialiasing make
  pixel methods unreliable and PIL is not stdlib).
- Tool: `scan_vitals.py`, 13th registered tool, category performance so its
  verdicts merge into the performance bucket. Grades against the published
  thresholds (web.dev CWV: LCP 2.5s/4s, CLS 0.1/0.25; Lighthouse TBT
  200/600 ms); contrast violations are WCAG failures with capped examples.
  Notes state "lab measurement, one load". No capture -> every check info,
  grade Not measured; the tool never estimates.

**What I verified:** suite 174 -> 178 (threshold matrix, contrast pass/fail,
not-captured path, registry census now 9 page tools; TestToolContract sweeps
the 13th tool automatically). Live scan of example.com confirms an
uncaptured page adds only info verdicts and leaves the performance grade
unchanged. The live capture step needs the agent's browser pass and is
pending the next full site review, per the honest-evidence rule.

---

## 2026-07-03 - G5: findings history ledger

**Task:** G5 per PLAN.md section 28 (spec'd first). Phase G loop, iteration 5.

**What I did:** append-only `<slug>_history.jsonl` in the evidence dir, one
line per run (measured_at, target, page count, totals, scorecard bands, and
the issues slimmed to identity plus a 160-char note). `attach_delta` now
prefers the ledger's last entry over the soon-overwritten scan JSON (which
remains the fallback so pre-ledger evidence dirs keep working), and the
digest gains a Trend section over the last five runs that names any
overall-band movement. Both writers (scan_site.main, run_review.pipeline)
append after writing the scan JSON.

**What I verified:** suite 178 -> 183 (entry fields and note truncation,
append/read roundtrip skipping a malformed line, ledger-preferred delta,
JSON fallback, trend rendering including the band-move line). Live: two
consecutive example.com scans created the ledger and rendered the trend
section with the ledger-sourced delta. One test fixture initially carried
band-only scorecard dicts and broke the digest's scorecard table; fixed the
fixture to carry full grade dicts as real runs do.

---

## 2026-07-03 - G6: polite scale crawling (PHASE G COMPLETE)

**Task:** G6 per PLAN.md section 29 (spec'd first). Phase G loop, iteration
6 - the final Phase G task.

**What I did:** `tools/crawler.py`, a discovery tool (not a registered
scanner): breadth-first, same-registrable-domain crawl that is strictly
serial with a 1.0s per-request delay (raised by robots.txt Crawl-delay),
robots.txt compliant via the stdlib robotparser (disallowed URLs counted,
never fetched), bounded by the caller's budget under a hard 500-page
ceiling, filters binary extensions, off-domain hosts, and non-http schemes,
and persists resumable state after every page
(`<slug>_crawl_state.json`). `run_review.py` gains `--crawl N` and
`--fresh`: the crawl replaces sampled discovery only when the user
explicitly opts in, and the pipeline's fetch cache means the scan reuses the
crawl's page fetches instead of refetching. CLAUDE.md scope, SKILL.md, and
README updated; authorization language unchanged.

**What I verified:** suite 183 -> 186 (BFS order with robots/extension/
domain filtering and Crawl-delay raising the wait, page cap, resume without
refetching visited pages), all pass. Live: a capped crawl of example.com
collected exactly its one page, excluded the external link, and stopped
with an empty frontier.

**Phase G ledger:** G1 DKIM selector families, G2 tracker list depth
(25 -> 154), G3 rendered-DOM snapshot pipeline, G4 scan_vitals (browser
LCP/CLS/TBT + WCAG contrast), G5 findings history ledger with digest
trends, G6 polite opt-in crawling. Suite went 164 -> 186 scanner tests plus
9 builder tests over the phase; every task spec'd in PLAN.md before build,
verified live where a passive check allowed, committed atomically.

---

## 2026-07-03 - LOOP COMPLETE

BACKLOG.md has no unblocked `todo` items (27 tasks done across phases A
through G), so per the stop condition this run records completion instead of
inventing work.

**Delivered across the loops (each spec'd in PLAN.md, tested, verified,
committed atomically):**
- Foundation: central registry, contract-conformance tests, self-describing
  tools with tool-owned grades.
- Measurement surface: 13 scanners across 10 scorecard categories - HTTP
  security with CSP directive analysis and security.txt, page-level security
  hygiene (SRI, form actions, inline handlers), TLS with CAA and HTTP/2 via
  ALPN, email auth and transport (SPF, DMARC, DKIM incl. date selectors,
  DNSSEC, MTA-STS, TLS-RPT, BIMI), crawlability with disallow-all and
  apex/www canonicalization, SEO, structural accessibility, link health with
  anchor integrity, performance with per-asset caching and redirect chains,
  readability, privacy with 154 documented trackers and CMP detection,
  design signals, and browser-vitals consumption (LCP/CLS/TBT, contrast).
- Analyst output: issue aggregation across pages, run deltas, findings
  history ledger with digest trends, machine-drafted report data, and the
  user-approved executive report design (test-covered builder).
- Infrastructure: per-run fetch cache, quote-aware hyphen-safe HTML
  extraction, rendered-DOM snapshot pipeline, polite opt-in crawler,
  .gitattributes hygiene. 186 scanner tests plus 9 builder tests, offline,
  green.

**No blocked items.** Open follow-ups for a human:
- Exercise the browser capture steps (rendered snapshots, metrics.json) in a
  real site review; the tool side is built and tested.
- The open design questions in PLAN.md (host vs page scan signatures; git
  has no remote so the loop commits locally and cannot push).

RALPH: NOTHING TO DO

---

## 2026-07-03 - H1: executive report review pass (user request)

**Task:** H1. The user asked for a review of the final report to make it
better. Reviewed it as a communication artifact and fixed the gaps: no scope
statement, no progress story on re-reviews, headings could strand at page
bottoms, screenshots floated borderless, and the weakest tile spoke
analyst-language.

**What I did (all optional fields, backward compatible, approved design
preserved):** scope line under the masthead ("N page(s) reviewed | method"),
progress strip under the bottom line ("Since the previous review (date): N
resolved, M new" with semantic colors), PAGES REVIEWED tile when scope is
present, keep-with-next on section headings and exhibit captions, and
exhibit images framed in a hairline cell. `draft_report_data` fills scope
(page count plus an honest method string that names rendered-DOM capture
only when the scan actually used snapshots) and progress (from the scan
delta) automatically.

**What I verified:** builder suite 9 -> 12 tests including a real 1x1 PNG
framed-exhibit render; scanner suite 186 -> 188 (draft scope/progress and
first-run None); all green. Re-rendered both previews (client-a with factual
scope added to its hand-authored data; a fresh machine draft from the
example.com scan showing the auto-filled progress strip) and sent them to
the user.

---

## 2026-07-03 - I1: live round trip of the rendered-evidence tier

**Task:** I1 (user: "fix all these"). Prove the G3/G4 pipeline with a real
browser, not just unit tests, and fix what the live run reveals.

**How:** a deliberately faulty client-rendered SPA served on localhost
(everything injected by JS: single H1, one alt-less image, a
placeholder-only email input, a googletagmanager script tag, a 2.81:1
gray-on-white paragraph, and a /#missing-anchor nav link). The Chrome
extension was not connected, so capture used headless Chrome --dump-dom
with the CAPTURE.md vitals/contrast snippets self-run in the page - real
Chrome rendering and real computed-style measurements either way. LCP came
back null under virtual time and stayed an honest null.

**Proof:** the static scan flagged the page client-rendered with structural
checks inconclusive; after the capture handoff, all six structural scanners
ran on the rendered DOM (evidence_source: rendered_dom): headings measured
pass, image_alt fail on the planted image, form_labels warn, privacy warned
on the JS-injected tracker no static scan can see, and scan_vitals graded
the contrast violation fail at exactly 2.81:1.

**Defects found live and fixed (the point of the exercise):**
1. anchor_fragments only recognized bare '#x' hrefs; SPA navs write
   same-page anchors as '/#x', which passed unchecked. Now path-form
   same-page fragments resolve against the page URL.
2. Even then, a slashless page URL (http://host) failed string comparison
   against the resolved http://host/#x; same-page comparison now normalizes
   the empty path. Note wording also fixed ('page markup', not 'static
   HTML', since the check runs on rendered evidence too).

**Verified:** suite 188 -> 189, all pass; the live SPA re-scan now warns on
the planted broken anchor. Test server stopped, localhost evidence removed.
Out of scope, stated: CrUX field data needs an API key; the crawl ceiling
and no-JS-execution rules are charter choices.

**State at loop end:** 12 registered scanners across 10 scorecard categories
(security host+page, tls, dns_email, seo+crawl, accessibility, links,
performance+delivery, readability, privacy, design), a per-run fetch cache,
a professionally designed executive report with its own test suite, 149
total offline tests (140 scanner + 9 builder), and docs in sync. Open: the
user's visual verdict on
the redesigned report docx files.
