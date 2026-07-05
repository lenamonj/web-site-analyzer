# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-05 - JOURNAL rotation

Rotated at >500 lines: moved the oldest 5 entries (2026-07-05 - Q9: a clear message, not a raw traceback, on invalid JSON input through 2026-07-05 - Phase R: second full convergence audit (NOT converged - 1 High, 6 Medium)) to JOURNAL-archive.md, kept the last 10 in JOURNAL.md. History is preserved, not rewritten. Standing after the Phase S audit: 1 High (S1), 4 Medium (S2-S5), 4 Low (S6-S9) open; NOT converged.

## Iteration 15 - S1: kill the fabricated verdict at the shared tag_attrs_re factory (High)

**Task:** S1, the only High from the Phase S audit and the last iteration in the budget. The shared
`tag_attrs_re` factory (common.py:42) ended the tag name with `\b`, which matches at the
name->hyphen joint, so every consumer parsed a hyphenated custom element as its bare-tag prefix and
fabricated a verdict for a tag that was not present.

**Files changed:** common.py (tag_attrs_re: `r"<%s\b%s>"` -> `r"<%s(?![-\w])%s>"`, with a docstring
naming the class and the sibling leaf regexes it mirrors). test_review_tools.py (added
test_shared_tag_attrs_re_ignores_hyphenated_custom_elements). README.md (count resync 381->382).
BACKLOG.md (S1 done), JOURNAL.md (this entry).

**Verification:** factory returns [] for <form-field>, <img-comparison-slider>, <script-loader>,
<a-scene>, <link-preview>, <iframe-embed>; still matches <form>, <form >, <form\n>, <form attr=x>.
Consumer level: check_form_actions on a <form-field>-only page -> "info" (honest "no forms", not the
fabricated "fail"); a real insecure <form> still -> "fail"; check_image_dimensions on
<img-comparison-slider>*3 -> "info" (no images, not the fabricated "warn"); a real dimensionless
<img> still -> "warn" with the right count. New test is a FACTORY-level guard so no present-or-future
consumer reinherits the class; mutation check: reverting to `\b` fails it. Full battery: scanner 382
(was 381), builder 40, charts 8 all green; README guard exit 0 at 422; py_compile clean.

**Learnings:** the fix that closes a leaf-by-leaf defect class for good is to fix the SHARED FACTORY
and test AT the factory, not at one consumer - a consumer-level test would have protected only
scan_page_security or scan_design while the other four consumers stayed exposed. This is the
counterpart to the Phase S finding: the class stayed open for seven audits because it was fixed at
the leaves and tested at the leaves, so the factory was never in any test's blast radius. Now it is.

**Next:** BUDGET EXHAUSTED - this was iteration 15 of 15, the hard stop. S1 (the one High) is fixed
and verified. Open at budget end: 4 Medium (S2 HEAD-5xx broken-link, S3 bare-string-to-list-field
per-char corruption, S4 non-dict-container traceback, S5 NaN/Inf-score traceback) and 4 Low
(S6-S9), all filed with reproductions and acceptance checks in BACKLOG Phase S ready for the next
run. NOT converged: the Definition of done requires a full audit pass finding zero High AND zero
Medium, and four reproduced Medium remain. No promise. To finish the job, a future run should clear
S2-S5, then re-run the certifying full audit; and per the S1 learning, when it fixes the next class
it should fix the shared helper and test there, not leaf by leaf.

## Manual pass (not jeffy) - clear Phase S S2-S9 (2026-07-05)

**Task:** the user asked to clear the remaining Phase S findings directly, outside the jeffy loop
(which had ended at its budget), and to leave the changes uncommitted for their review. Fixed all
four Medium (S2-S5) and four Low (S6-S9) in one pass, each with a regression test.

**Files changed:**
- scan_links.py (S2): GET-retry guard widened from `status in (405, 501, None)` to `status is None
  or status == 405 or (500 <= status < 600)`, so a HEAD-5xx/GET-ok link is not a fabricated break.
- build_exec_report.py (S3/S4/S5): added `import math`; a `_as_str_list` helper and a bare-string
  guard IN `_as_rows` (S3 was broader than filed - `_as_rows` iterated a bare-string field per
  character, so findings/recommendations/action_plan/evidence shared the corruption); a container
  coercion loop that turns a non-dict scorecard/web_vitals/key_dates/assessment/progress into {}
  (S4); a `_finite_number` helper gating both score checks so NaN/Inf render "not measured" (S5).
- scan_dns_email.py (S6): check_mta_sts/check_tls_rpt/check_bimi now read the ok flag and say
  "presence could not be determined" on a failed lookup instead of asserting absence.
- scan_http_security.py (S7): added `_csp_policies`; check_clickjacking now treats framing as
  protected if ANY separately-enforced CSP policy restricts frame-ancestors (the browser
  intersection), not first-header-wins.
- test_review_tools.py (S8): the stdlib-only charter guard globs every non-test tools/*.py now,
  with a coverage assertion naming the eight orchestration files it previously skipped.
- draft_report_data.py (S9): DECISION - the "name every subject" rule is absolute; dropped
  LIST_ALL_PAGES and the "+N more" branch, `_page_list` enumerates every page.
- Regression tests added: S2 (link fallback), S3/S4/S5 (builder), S6 (dns lookup failure), S7
  (clickjacking intersection); S8 coverage assertion in the guard test; S9 test rewritten to assert
  full enumeration. README.md count resync. BACKLOG.md, JOURNAL.md.

**Verification:** every fix reproduced-then-fixed with a direct call before the test, then the full
battery: scanner 382 -> 385, builder 40 -> 43, charts 8, all green; README guard in sync at 428
(exit 0); py_compile clean; no em/en dashes. The one pre-existing test that codified the S9
truncation was updated (behavior changed by the rule decision, not a silent break).

**Learnings:** S3 is the clearest repeat of the project's signature lesson - the finding named
quick_wins/strengths/weaknesses, but the SAME per-character bug lived in the shared `_as_rows`
helper feeding four other fields; fixing only the named spots would have left the helper as a latent
corruptor. The rule holds across data-shape bugs, not just regex bugs: find the shared helper and
fix it there. Also, S9 shows a "Low" filed as a decision is cheap to resolve when the user has a
standing rule - the memory ("findings name every subject") settled it without a round trip.

**Next:** all Phase S findings (S1-S9) are closed and the backlog is empty. Changes are UNCOMMITTED
for the user's review (they will commit and push). Convergence is not yet FORMALLY established: a
fresh certifying full audit has not run since these fixes landed, and the DoD requires that single
clean pass. The honest next step, whenever the user wants it, is one more full convergence audit -
if it comes back zero High / zero Medium, the promise holds.

## Iteration 1 (jeffy N=1) - Phase T: eighth FULL convergence audit (backlog empty)

**Task:** backlog empty after S1-S9, so this /jeffy 1 iteration is the certifying full convergence
audit. It did NOT converge.

**Method / fresh evidence:** fresh battery first - scanner 385, builder 43, charts 8 all OK on
py3.13; README guard in sync; py_compile clean (31 files); a static scan found no 3.11+ features.
Then four independent adversarial auditors (A scanners, B report pipeline, C orchestration/trend,
D tests/docs/deps/compat/security), each told to scrutinize the just-landed S1-S9 fix code hardest
because new code is where new defects hide. I reproduced every High/Medium candidate myself.

**Files changed:** BACKLOG.md (new Phase T section, T1-T4), JOURNAL.md. No source changed - an
empty-backlog iteration audits and files, it does not fix.

**Findings (all reproduced by me):**
- T1 HIGH - _as_rows: the S3 fix closed only the bare-STRING field case. A scalar field
  (findings=123) is not iterable -> TypeError kills the build; a single dict field (one finding
  object without the [ ]) iterates its KEYS -> renders four bogus "severity/area/finding/evidence"
  rows and DROPS the real finding. My repro: both, exit-0 silent drop for the dict case.
- T2 MEDIUM - add_trend_section: the S4 coercion covered the five top-level containers but not the
  nested progress.trend. My repro: {"progress":{"trend":"oops"}} -> AttributeError, exit 1.
- T3 MEDIUM - trends.quarter_of: `except (TypeError, ValueError)` misses KeyError, so a dict-valued
  measured_at_utc in a corrupt ledger line crashes the trend layer (orchestrator mid-pipeline +
  the trends CLI raw traceback). My repro: quarter_of({"x":1}) -> KeyError slice(0,4,None).
  Pre-existing, not from an S-fix.
- T4 MEDIUM(borderline) - README:152 lists findings as a capped list, contradicting the S9 fix,
  README:98/44, and the test. My repro: the three README lines are mutually contradictory.

**Audit scores (rescored this pass, highest finding severity per dimension):**
- Correctness / UX of the deliverable: HIGH (T1 silent drop + fabricated content in the report).
- Error handling: MEDIUM (T2, T3 raw tracebacks where a clean skip/None is the contract).
- Documentation: MEDIUM (T4 doc contradicts code and its own siblings).
- Testing: NONE - Slice D neuter-proved ALL NINE new S-tests genuinely fail when their target is
  reverted (zero vacuous), and found no tautologies; the T1/T2 gaps are missing COVERAGE captured
  by those findings, not unsound tests.
- Security: NONE (no eval/exec/pickle/shell; slug scrub blocks traversal; redirects bounded; CrUX
  key never reaches output - re-reproduced).
- Dependency hygiene: NONE (stdlib-only by full AST scan; pins sane; 3.10.19 ran all suites green).
- Performance / Architecture / Developer experience / Observability: NONE found this pass.
- Overall: HIGH. NOT CONVERGED (1 High, 3 Medium).

**Learnings:** the class-completeness trap sprang an eighth time, and this pass makes its shape
undeniable - THREE of the four findings are my own Phase S fixes left one sibling short: S3 fixed
`str` but not the dict/scalar it implied; S4 coerced top-level containers but not the nested one
they implied; S9 fixed the code and ONE doc line but not the second that describes the same thing.
The durable rule, now proven across regex, data-shape, and doc classes alike: when you fix a case,
enumerate its siblings (every input type, every nesting level, every doc line that states the
behavior) and close them in the same change, or the audit will find the one you skipped. This is
also exactly why the DoD forbids self-certification: I fixed S1-S9 and believed them complete, and
an independent fresh-eyes audit falsified that within one iteration.

**Next:** /jeffy 1 budget is exhausted (this was the single iteration). T1-T4 are filed with
reproductions and acceptance checks. NOT converged: 1 High (T1), 3 Medium (T2-T4) open. No promise.
To finish: clear T1-T4 (all small, well-scoped), then re-run the certifying full audit; and fix
each as a CLASS (all sibling input types / nesting levels / doc lines at once), not the one case
the repro happened to hit.

## Iteration 1 (jeffy N=10) - T1: _as_rows whole-field coercion for any non-list type (High)

**Task:** T1, the only High from the Phase T audit - _as_rows crashed on a scalar field and silently
dropped + fabricated on a single-dict field, because the S3 fix closed only the bare-string case.

**Files changed:** build_exec_report.py (_as_rows: `if items is None: return []` then `if not
isinstance(items, (list, tuple)): items = [items]`, replacing the str-only guard). test_exec_report.py
(test_as_rows_handles_a_whole_field_of_any_non_list_type). README.md (builder count 43->44 resync).
BACKLOG.md, JOURNAL.md.

**Verification:** _as_rows over None->[], scalar/bool->[{}] (no crash), single dict->one row with all
content preserved (never key-iterated), string->{text_key}, list/mixed/tuple unchanged. End to end a
single-dict findings field renders "No CSP on homepage" (real finding kept), and a scalar findings
field builds instead of crashing. Fixed AS A CLASS per the Phase T lesson: every non-list input type
at once, not just the dict case the repro hit. Mutation check: reverting to the S3 str-only guard
fails the new test. Full battery green - builder 43 -> 44, scanner 385, charts 8; README guard exit 0
at 429.

**Learnings:** the class-complete form was simpler than the S3 patch it replaced - one `not
isinstance(..., (list, tuple))` covers str, dict, and every scalar, versus the special-cased `str`
guard that looked complete but left three input types exposed. Narrow fixes are often more code than
the general one; enumerating the class up front is both safer and smaller.

**Next:** T2 (add_trend_section crash on a non-dict nested progress.trend, Medium). Zero High now; 3
Medium remain (T2, T3, T4). Not converged. No promise.

## 2026-07-05 - JOURNAL rotation

Rotated at >500 lines: moved the oldest 5 entries (2026-07-05 - Q12: complete _as_rows across every builder-consumed list field through 2026-07-05 - Q16: gate on is_file and catch OSError in the two JSON mains) to JOURNAL-archive.md, kept the last 10. History preserved, not rewritten. Standing after Phase T iteration 1: T1 (High) done; 3 Medium (T2-T4) open; NOT converged.

## Iteration 2 (jeffy N=10) - T2: coerce a non-dict nested progress.trend (Medium)

**Task:** T2. The S4 container coercion covered the five top-level containers but not the nested
progress.trend, which add_trend_section reads with .get(); a non-dict trend raw-tracebacked.

**Files changed:** build_exec_report.py (`if not isinstance(trend, dict): trend = None` right after
`trend = progress.get("trend")`). test_exec_report.py (test_non_dict_nested_progress_trend_skips_
section_not_crash). README.md (builder 44->45 resync). BACKLOG.md, JOURNAL.md.

**Verification:** all four non-dict trend variants (string, list, number, bool) build clean with the
Progress section skipped; a valid trend dict still renders "Progress this quarter" with its resolved-
findings content; has_exec_summary now correctly treats a bad trend as absent so a real progress
strip still shows. Mutation check: removing the coercion fails the new test. Full battery green -
builder 44 -> 45, scanner 385, charts 8; README guard exit 0 at 430.

**Learnings:** class-completeness is bounded by REALISM, not by syntax. T1's class was every non-list
input TYPE at one level, all equally plausible hand-author slips. T2's realistic class is every non-
dict TYPE of progress.trend at one level - also handled at once by the isinstance guard. I explicitly
did NOT harden the deeper add_trend_section reads (latest_delta/pages_scanned), because those only
fire from a hand-authored partial trend dict, which is not a realistic input (trend is machine-
generated); the rubric's "no speculative findings / no unnecessary defensive programming" says stop
at the realistic boundary. Over-fixing is its own failure mode.

**Next:** T3 (trends.quarter_of raises KeyError on a dict-valued ledger timestamp, Medium). Zero High;
2 Medium remain (T3, T4). Not converged. No promise.

## Iteration 3 (jeffy N=10) - T3: gate quarter_of on str; replenishment finds T5 (Medium)

**Task:** T3. trends.quarter_of caught only (TypeError, ValueError), so a dict-valued measured_at_utc
in a corrupted ledger line raised an uncaught KeyError (ts[0:4] is a slice-key lookup), crashing
trend_from_ledger and the trends CLI.

**Files changed:** trends.py (quarter_of: `if not isinstance(ts, str): return None` up front, then
except narrowed to ValueError since the str gate makes TypeError dead). test_review_tools.py
(test_dict_timestamp_ledger_line_does_not_crash_the_trend_layer). README.md (scanner 385->386
resync). BACKLOG.md (T3 done, T5 filed), JOURNAL.md.

**Verification:** quarter_of returns None for dict/list/int/None/float/bool and every malformed
string, the right quarter for a valid stamp; a ledger with a dict-ts middle line skips it and still
builds a two-quarter trend; the trends CLI on such a ledger exits 0 with no traceback (probe cleaned
up). Mutation check: reverting to the except-only guard fails the new test. Full battery green -
scanner 385 -> 386, builder 45, charts 8; README guard exit 0 at 431.

**Replenishment (partial audit of the least-recently-scored surface - my new T1-T3 code) - ONE new
finding (T5, filed):** swept the builder's field-iteration sites for T1-class siblings: every top-
level hand-authorable list field is normalized (findings/recs/action_plan/evidence + nested rows/
metrics/items via _as_rows now class-complete; quick_wins/strengths/weaknesses via _as_str_list;
containers coerced to {}; progress.trend to None), and the only remaining bare-field loops (451/493)
are on machine-generated trend delta - the unrealistic deep-nesting I bounded out of T2. Clean there.
But probing the T3 THREAT MODEL (external ledger corruption) beyond the timestamp found that a
corrupted entry with a non-dict metrics, bands, OR issues crashes build_trend (the `or {}` idiom
guards None, not a truthy non-dict) - the exact class-completeness sibling T3 left open. Reproduced
all three; filed T5 (Medium, same threat model and severity as T3) ahead of T4 (a crash outranks a
doc line).

**Learnings:** the replenishment did its actual job this time - it caught the T3 class one field wide
before the next full audit could. T3 as filed named the timestamp; the class is "any wrong-typed
sub-field of a corrupt-but-valid-dict ledger entry crashes the trend layer." The lesson holds: a
finding scoped to one field implies its siblings under the same threat model. I filed rather than
batched (one task per iteration), so T5 fixes the metrics/bands/issues trio class-complete next.

**Next:** T5 (build_trend crash on a non-dict metrics/bands/issues, Medium) - the top open item now.
Zero High; 2 Medium remain (T5, T4). Not converged. No promise.

## Iteration 4 (jeffy N=10) - T5: class-complete coercion of ledger-entry sub-dicts (Medium)

**Task:** T5 (found by iteration 3's replenishment). A corrupt-but-valid-dict ledger entry with a
non-dict metrics/bands/issues crashed build_trend - the `or {}` idiom guarded None but not a truthy
non-dict like a list.

**Files changed:** trends.py (added a `_dict(x)` helper = x if isinstance(x, dict) else {}; applied
at both nesting levels of _score/_page_metric/_series - metrics then scores/pages - and at
_delta_rows bands). scan_site.py (diff_issues coerces a non-dict issues to {}). test_review_tools.py
(test_non_dict_entry_subfield_does_not_crash_the_trend_layer). README.md (scanner 386->387 resync).
BACKLOG.md (T5 done), JOURNAL.md.

**Verification:** every non-dict metrics/bands/issues (str/list/int) and the deeper metrics.scores/
pages non-dict all build a trend; a well-formed ledger still yields the real overall series
[0.4, 0.7]. Mutation check: reverting the coercions to `or {}` fails the new test. Full battery
green - scanner 386 -> 387, builder 45, charts 8; README guard exit 0 at 432.

**Replenishment (partial audit - the trend layer I just touched) - clean, no new finding:** fuzzed
build_trend against every entry field (measured_at_utc/bands/metrics/issues/pages_scanned/target/an
unknown key) crossed with every bad type (str/list/int/float/bool/None/dict) - ZERO crashes. The
only remaining `or {}` token in trends.py is inside the _dict docstring, not a live idiom.
pages_scanned is stored, never dereferenced, so any type is safe. The T3/T5 ledger-corruption class
is now complete at the realistic (entry-sub-field) level; the deeper item-level corruption (a dict
issues whose fail-list holds a non-dict) is beyond the realistic boundary, consistent with the T2
decision, so I did not add speculative guards.

**Learnings:** the fix was smaller for being class-complete - one `_dict` helper replaced five
scattered `or {}` half-guards and closed metrics/bands/issues plus their inner scores/pages in one
pass, and a type-x-field fuzz proved completeness in seconds rather than trusting a hand list. Fuzz-
to-confirm is the cheap complement to fix-the-class: enumerate the inputs, assert no crash, done.

**Next:** T4 (README:152 lists findings as a capped list, contradicting the S9 fix - XS doc fix),
the last Phase T item. When it clears the backlog empties and the certifying full audit re-runs.
Zero High; 1 Medium (T4) remains. Not converged. No promise.

## Iteration 5 (jeffy N=10) - T4: README no longer lists findings as a capped list (Medium/doc)

**Task:** T4. README:152 listed findings among "capped lists", stale after the S9 fix made findings
enumerate every affected page - it contradicted README:98/44 and the S9 test.

**Files changed:** README.md (line 152 rewritten to "The one capped list, the capture page set,
names every page it dropped; findings are never capped and enumerate every affected page.").
BACKLOG.md (T4 done), JOURNAL.md.

**Verification:** grepped every doc (README/SKILL/CLAUDE/CAPTURE) for finding+cap/truncation - 152
was the only stale line; the other "capped" mentions (README:111/249, SKILL:49) are the capture page
set and the 500-page crawl cap, both genuinely capped, so the class was one line. check_readme_
counts.py exit 0; README dash-clean; full battery green (scanner 387, builder 45, charts 8).

**Replenishment (integration audit of the cumulative T1-S5 builder robustness) - clean, no new
finding:** built ONE maximally-hostile-but-plausible hand-authored report exercising every builder
hazard at once - findings as a single dict (T1), recommendations/evidence as bare strings (T1),
quick_wins as a string (S3), web_vitals as a list and key_dates as a scalar (S4), progress.trend as
a string (T2), and a NaN score (S5). It built with exit 0, the real finding "No CSP on homepage" was
preserved (not dropped), the quick win and recommendation rendered as single items, and the NaN row
showed "not measured". No single unit test covers all hazards together, so this integration check is
the meaningful "did the five fixes compose" evidence. They do.

**Learnings:** an integration replenishment (all hazards in one input) is a stronger convergence
signal than the sum of unit tests, because robustness fixes can interact - e.g. the S4 container
coercion runs before the T1 _as_rows normalization, and only an all-at-once input proves the order
is right. Worth doing once a class of fixes is complete, before the certifying audit.

**Next:** BACKLOG.md now has ZERO open tasks - every Phase T finding (T1-T5) is closed. The next
iteration runs the certifying FULL convergence audit per the Method: a single fresh-evidence pass
that rescores every dimension. Only if it finds zero High and zero Medium does the DoD hold and the
promise fire. Standing: zero High, zero Medium, zero Low open. Not yet converged - the certifying
audit has not run since T1-T5 landed. No promise this turn.

## 2026-07-05 - JOURNAL rotation

Rotated at >500 lines: moved the oldest 5 entries (2026-07-05 - JOURNAL rotation through Iteration 14 - Phase S: seventh FULL convergence audit (backlog was empty)) to JOURNAL-archive.md, kept the last 10. History preserved, not rewritten. Standing after Phase T iteration 5: T1-T5 all done, backlog empty; the certifying full convergence audit runs next. NOT converged yet.

## Iteration 6 (jeffy N=10) - Phase U: ninth FULL convergence audit (backlog empty)

**Task:** backlog empty after T1-T5, so this iteration is the certifying full convergence audit. It
did NOT converge.

**Method / fresh evidence:** fresh battery green (scanner 387, builder 45, charts 8; README guard in
sync; py_compile clean 31 files; no 3.11+ features). Four adversarial auditors, each told to
scrutinize the T1-T5 fix code hardest. Slice D (tests/docs/deps/security) was interrupted mid-run
when the user stopped an accidental second /jeffy launch; its checks are covered by this run's per-
task mutation checks (T1/T2/T3/T5 tests were each neuter-verified when written) plus the battery, so
the gap is low-risk. I reproduced every High/Medium candidate myself.

**Files changed:** BACKLOG.md (Phase U, U1-U4), JOURNAL.md. No source changed - an empty-backlog
iteration audits and files, it does not fix.

**Findings (all reproduced by me):**
- U1 HIGH - the S4 container-coercion loop covers 5 top-level containers but OMITS scope, the 6th.
  My repro: {"scope":"Homepage and top nav"} -> AttributeError at _scope_text, no deliverable. AST-
  enumerated that scope is the ONLY omitted container (the class is now closed by adding one key).
- U2 MEDIUM - the T5 issues coercion stopped at the `issues` field; issues.fail/warn as a non-list
  crashes diff_issues, and it runs on EVERY fresh run via attach_delta (Slice C), so one corrupt
  append-only line poisons all future runs. My repro: issues.fail None/str/dict all crash.
- U3 MEDIUM - a list/dict value used as a dict-lookup key (band/severity/rating/priority) raises
  TypeError unhashable. My repro: list-valued band/severity/priority each crash the build.
- U4 MEDIUM (low realism) - findings authored as a keyed OBJECT (dict of finding-dicts) silently
  drops every entry via T1's "lone dict = one item". My repro: two findings -> one blank row.

**Audit scores (rescored, highest finding severity per dimension):**
- Correctness / UX of the deliverable: HIGH (U1 crash kills the report on a plausible scope shape;
  U4 silent drop).
- Error handling: MEDIUM (U2, U3 raw tracebacks where a clean degrade is the contract).
- Testing: NONE reproduced (the T1-T5 tests are non-vacuous by their write-time mutation checks;
  slice D's independent vacuity sweep did not complete but nothing contradicts that).
- Security / Dependency hygiene / Documentation: not independently re-scored this pass (slice D
  interrupted); the battery + T4 grep + prior 3.10.19 run leave no known issue, but I am NOT
  claiming these dimensions certified this iteration - a clean slice D is owed before convergence.
- Performance / Architecture / DevEx / Observability: NONE found.
- Overall: HIGH. NOT CONVERGED (1 High, 3 Medium).

**Learnings:** ninth audit, and the class-completeness trap recurred TWICE more - S4's container
coercion missed scope (U1) and T5's ledger coercion missed the fail/warn sub-lists (U2). The habit
is still not landing: I keep declaring a coercion "class-complete" after handling the level the repro
hit, and the audit keeps finding the adjacent level. New concrete rule for coercion fixes: when I add
an isinstance/`_dict` guard, immediately (a) AST-enumerate every peer read at the SAME level (U1's
six containers) and (b) descend one level into each guarded container and guard its sub-fields too
(U2's fail/warn). Do both in the same change and prove with a fuzz, or the next audit files the
sibling. Also: I must not call slices "covered" loosely - slice D genuinely did not run, so I did not
claim its dimensions certified.

**Next:** U1 (scope coercion, High) - the top open item. Zero Low; 1 High, 3 Medium open. When U1-U4
clear, re-run the certifying full audit WITH a complete slice D. Not converged. No promise. ~4
iterations of budget remain.

## Iteration 7 (jeffy N=10) - U1: coerce a non-dict top-level scope (High)

**Task:** U1. The S4 container-coercion loop covered five top-level containers but omitted scope, the
sixth; a non-dict scope crashed _scope_text / add_glance_tiles and killed the deliverable.

**Files changed:** build_exec_report.py (added "scope" to the coercion tuple, now all six AST-
enumerated containers). test_exec_report.py (new test_non_dict_scope_builds_and_valid_scope_still_
renders; added "scope" to the S4 container test's tuple). README.md (builder 45->46 resync).
BACKLOG.md (U1 done), JOURNAL.md.

**Verification:** scope as string/list/scalar builds clean; a valid scope dict still renders
"Automated plus manual" and the pages-reviewed tile. Mutation check: removing scope from the loop
fails the new test. Full battery green - scanner 387, builder 45 -> 46, charts 8; README guard exit
0 at 433.

**Learnings:** the fix was one word (add "scope" to the tuple), but the durable part was the AST
enumeration I did BEFORE filing U1 - it proved scope was the ONLY omitted container, so the class is
now provably closed, not just closed for the case the audit happened to hit. That is the new coercion
discipline landing: enumerate every peer at the level before calling it done. U2 next applies the
second half (descend into the guarded container's sub-fields).

**Next:** U2 (diff_issues crash on a non-list issues.fail/warn, Medium) - the top open item. Zero
High now; 3 Medium remain (U2, U3, U4). Not converged. No promise.

## Iteration 8 (jeffy N=10) - U2: guard the issues.fail/warn sub-lists; replenishment finds U5

**Task:** U2. The T5 fix coerced a non-dict `issues` field but not its fail/warn sub-lists or items;
a corrupt entry crashed diff_issues, and it runs on every fresh run via attach_delta.

**Files changed:** scan_site.py (keyed() coerces fail/warn to [] when not a list and filters the
comprehension to items that are dicts with a string scan AND check - the string-check guard also
prevents an unhashable dict key). test_review_tools.py (test_diff_issues_survives_corrupt_fail_warn_
sublists). README.md (scanner 387->388 resync). BACKLOG.md (U2 done, U5 filed), JOURNAL.md.

**Verification:** fail/warn as None/str/dict/int and a good list holding non-dict / bad-scan items all
degrade to no-diff-for-that-side; a well-formed diff still computes the correct verdict-agnostic new/
resolved; the fresh-run attach_delta path survives a corrupt prev entry. Mutation check: reverting to
the old flat= line fails the new test. Full battery green - scanner 387 -> 388, builder 46, charts 8;
README guard exit 0 at 434.

**Replenishment (partial audit - the descend-one-level rule applied across ALL six containers) - ONE
new finding (U5, filed):** fuzzed every guarded container with a bad SUB-field. Five are robust
(scorecard.rows/web_vitals.metrics/key_dates.items via _as_rows, assessment.strengths/weaknesses via
_as_str_list, scope.method/pages_reviewed via add_run/truthy) and _issue_name tolerates a malformed
item. But progress.trend as a DICT with a non-dict latest_delta/pages_scanned (or non-list quarters)
crashes add_trend_section - the SAME `X or {}` idiom I fixed in trends.py (_score/_delta_rows) and
diff_issues (U2), in the builder's separate trend RENDERER I never touched. Filed U5 (Medium, lowest
realism of the series).

**Learnings:** U5 is the exact thing the T2 note deferred as "unrealistic", and the third time this
run that a deferred "unrealistic" judgment came back as a real finding (S->T scope, T5->U2 sublists,
T2->U5 trend nesting). The honest update to my realism heuristic: when a crash is of a defect CLASS I
am already fixing elsewhere, "unrealistic input" is NOT sufficient grounds to defer it - the class
consistency (same idiom, same fix) outweighs the marginal realism argument, because the audit keeps
proving my realism line too optimistic. Fix the idiom everywhere it appears; only decline a genuinely
NOVEL speculative case.

**Next:** U3 (unhashable list/dict lookup key, Medium) - the top open item. Zero High; 3 Medium open
(U3, U4, U5). Budget: iterations 9-10 remain for 3 tasks + no room for the certifying re-audit, so
this run will not formally converge - it will land U3 and U4, leave U5, and need one more /jeffy for
U5 plus the clean audit. Not converged. No promise.

## Iteration 9 (jeffy N=10) - U3: hashable-coerce every field used as a lookup key (Medium)

**Task:** U3. A list/dict value used as a band/severity/rating/priority color- or sort-lookup key
raised TypeError: unhashable, crashing the build.

**Files changed:** build_exec_report.py (added `_hkey(x)` = x if isinstance(x,str) else str(x);
applied at all NINE field-as-key sites - the four filed PLUS the findings sort key SEVERITY_ORDER.get
(:1042) and the trend DIRECTION_STYLE lookup (:441), found by a grep enumeration). test_exec_report.py
(test_unhashable_lookup_key_field_does_not_crash_the_build). README.md (builder 46->47). BACKLOG.md
(U3 done), JOURNAL.md.

**Verification:** list/dict-valued overall/band/severity/priority/rating/direction all build clean; an
all-at-once fuzz builds; normal string severities still sort High-before-Low. Mutation check:
neutering _hkey to identity fails the test. Full battery green - scanner 388, builder 46 -> 47, charts
8; README guard exit 0 at 435.

**Learnings + a STRATEGIC FLAG for the user:** the enumeration-before-done habit again caught two
sites the finding did not name (the sort key and direction). But the deeper signal, raised by the user
this iteration, is that U2/U3/U4/U5 (and arguably T5) are ALL one meta-class: "the docx builder / trend
layer crashes or mis-renders on malformed HAND-AUTHORED exec_report_data.json." Patching each .get()/
lookup site defensively is whack-a-mole - the audit will keep finding the next input type/level because
a permissive JSON interface can always be made to crash with adversarial input. The right structural
move is EITHER (a) one input-normalization/validation boundary that coerces/validates the data file
once, replacing dozens of scattered isinstance guards, OR (b) a scope decision that machine-generated
data (what draft() emits) is the real contract and hand-authored-JSON abuse is Low/Declined, not
Medium. This is a decision only the user can make (loop rule), so I paused to ask rather than grind U4/
U5. See the reply to the user.

**Next:** PAUSED for a user scope decision on the input-robustness meta-class (structural fix vs.
decline-as-Low). U4, U5 open. Zero High; 2 Medium open. Not converged. No promise.
