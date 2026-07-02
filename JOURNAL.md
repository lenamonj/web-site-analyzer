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
