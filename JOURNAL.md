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
