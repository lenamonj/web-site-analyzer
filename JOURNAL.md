# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

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

## Iteration 1 (jeffy N=15) - U6: structural normalization boundary closes the malformed-input meta-class (user-approved)

**Task:** U6 (structural, replacing instance-patches U4 and U5 per the three-strike rule). Iteration 9
of the prior run paused and put the scope decision to the user: U2/U3/U4/U5 are one meta-class (the
docx builder / trend layer crashes or mis-renders on malformed hand-authored exec_report_data.json),
and patching each site is whack-a-mole. This run relaunched without an answer, so I re-put the decision
via AskUserQuestion. User chose the STRUCTURAL boundary over decline-as-Low or keep-patching.

**Files changed:** build_exec_report.py (new `normalize(data)` called first in build(); helpers
`_as_collection` and `_normalize_trend`; module constants TOP_CONTAINERS/LIST_FIELDS/NESTED_LIST_FIELDS;
retired the scattered S4 container-coercion loop and the T2 nested-trend guard, which normalize()
subsumes). test_exec_report.py (test_keyed_object_of_item_dicts_renders_every_item_not_one_bogus_row for
U4; test_partial_trend_dict_with_bad_nested_subfields_builds_clean for U5). README.md (badge/summary/
builder comment 435->437, 47->49). BACKLOG.md (U4/U5 marked done via U6; U6 recorded with the class
closure and the user decision). JOURNAL.md.

**What normalize() does (the single boundary):** coerces the six top-level containers to {} when non-
dict; flattens a list field authored as a keyed OBJECT of item-dicts to list(values) so EVERY item
renders (the no-silent-drop rule - this is U4's real fix, not a drop-and-carry-on); and coerces the
nested trend (latest_delta/pages_scanned to {}, scorecard/quarters to [] - class-complete, scorecard
added though U5 named only three fields, because add_trend_table iterates it as a row-list). Per-ITEM
coercion stays in _as_rows/_as_str_list and per-value hashing in _hkey (local, not whack-a-mole).

**Verification:** builder 47 -> 49 green; scanner 388, charts 8 green; README guard exit 0 at 437;
compileall clean; dash-clean on all changed files. Mutation check: neutering _as_collection to identity
fails the U4 test (keyed object stays a dict, both findings dropped); neutering _normalize_trend to a
no-op fails the U5 test (str latest_delta -> AttributeError in add_trend_section). Both confirmed
non-vacuous. Accept criteria for U4 and U5 both met (keyed-object renders every item + lone dict still
one row; partial trend builds clean + valid trend still renders).

**Learnings:** the iteration-9 meta-class read was right and the user confirmed the structural call. The
boundary is genuinely simpler than the guard pile it replaces (removed two in-build coercion blocks,
added one named function with a clear contract: normalize owns field-shape, _as_rows owns item-shape).
The class-complete habit paid off again - latest_delta.scorecard was a shape-dependent read the U5
finding did not name; enumerating add_trend_section/add_trend_table's reads before declaring done caught
it. This closes the malformed-exec_report_data meta-class at a boundary; a future audit should not
re-file a per-site .get()/lookup crash on that file - the fix is normalize(), and only a shape-dependent
read that normalize() does not cover is a new finding.

**Next:** zero open tasks remain. The next iteration must run the certifying FULL convergence audit
(the Definition-of-done gate): rescore every applicable dimension against the rubric with fresh
evidence, hardest on the just-changed normalize() code. Not converged yet - the audit has not run since
these changes. No promise this iteration.

## 2026-07-05 - JOURNAL rotation

Rotated at >500 lines: moved the oldest 6 entries (the 2026-07-05 rotation marker through Iteration 1 (jeffy N=10) - T1) to JOURNAL-archive.md, kept the last 10 here. History preserved, not rewritten. Standing: the malformed-input meta-class is closed by the U6 normalize() boundary; zero open tasks; the certifying full convergence audit has NOT run since the U6 changes, so NOT converged.

## Iteration 2 (jeffy N=15) - Phase V: tenth FULL convergence audit (backlog empty)

**Task:** Backlog had zero open tasks after U6, so this iteration is the certifying full convergence
audit. Ratchet: no Converged line exists, so it does not apply. Filled the Operating envelope
(PLAN.md section 2a) first - it was absent; the text documents the trust classes the eight prior
audits already reasoned by (scanned-site responses adversarial-but-bounded, exec_report_data.json
user-error, state files state-at-rest, CLI/env user-error).

**Method:** four independent adversarial auditors (the established project practice) over slices
A scanners, B report builder (hardest on the new normalize()), C orchestrator/trends/history,
D tests/docs/deps/security. Every in-envelope finding reproduced by me before filing.

**Files changed:** PLAN.md (section 2a Operating envelope). BACKLOG.md (Phase V section: V1 Medium,
V2/V3 Low, three-strike note). JOURNAL.md.

**Baseline (fresh, green):** scanner 388, builder 49, charts 8, README guard exit 0 at 437,
compileall clean, Python 3.13.8.

**Findings - 1 Medium, 2 Low. NOT CONVERGED.**
- V1 (Medium, in-envelope, structural): trends._delta_rows BAND_RANK.get crashes TypeError:
  unhashable on a ledger entry whose bands dict has a non-hashable VALUE (list/dict). State-at-rest,
  in-contract ("malformed ledger lines never crash the trend layer"), same class/score as T3/T5/U2.
  4th instance of that root cause -> three-strike -> filed as ONE structural entry-sanitization
  boundary at read_history, mirroring U6. Reproduced via build_trend and trend_from_ledger; poisons
  draft_report_data.main.
- V2 (Low, in-envelope-but-unrealistic-shape): _as_collection silently drops content on a MIXED keyed
  object (all-values-dict guard too strict). Two auditors split Medium/Low; the envelope decides Low
  (a mixed keyed object is beyond a realistic slip), but filed (not declined) because the hard
  no-silent-drop rule forbids the behavior and the fix is cheap. Reproduced.
- V3 (Low): trend latest_delta.scorecard items not per-item coerced -> non-dict row crashes
  add_trend_table; the item-level completion of U5's container-level trend fix.

**Audit scores by dimension (highest finding severity each):** architecture None; code quality Low
(V2/V3); security None (secrets/.env/sales ignored, no key leak); testing None (recent paths covered;
guard non-vacuous); error handling Medium (V1 ledger crash); performance None; documentation None
(dashes/counts/caps/CrUX wording all clean; envelope added); dependency hygiene None (requirements
pinned, stdlib guard holds); correctness Low (V2 silent drop). Overall highest: Medium. Zero High.

**Learnings:** the U6 boundary and the T3/T5/U2 trends guards each closed CONTAINER-shape robustness
but not always the VALUES inside a well-formed container - V1 (band value as key), V2 (mixed keyed
object), V3 (trend row item) are all "container coerced, contents not." V1 crossed the three-strike
threshold in the trends layer, so it is filed as a structural boundary rather than a fifth guard. V2/V3
are the builder analog but only Low, so no re-escalation yet; the Phase V note records the escalation
trigger if the builder keeps leaking item-level gaps after V2/V3.

**Next:** convergence NOT met (1 Medium). Execute V1 (structural ledger-entry sanitization boundary),
then V2, V3, then a fresh certifying full audit. No promise this iteration.

## Iteration 3 (jeffy N=15) - V1: structural ledger-entry sanitization boundary (Medium, three-strike)

**Task:** V1, the top open item. The trends/ledger layer crashed (TypeError: unhashable) on a
corrupted-but-valid-JSON ledger entry whose bands dict mapped a category to a non-hashable VALUE
(list/dict) used as a BAND_RANK lookup key. 4th instance of "trends crashes on a corrupt ledger entry"
(T3/T5/U2), so filed and fixed as ONE structural boundary, not a fifth per-read guard.

**Files changed:** trends.py (new `_sanitize_entry(e)` coercing each bands value to str-or-None,
applied to every entry at the top of build_trend; _issue_name made type-safe for a non-string check/
note/scan). test_review_tools.py (test_corrupt_ledger_value_inside_a_valid_container_does_not_crash).
README.md (scanner 388->389, total 437->438, badge + file-tree). BACKLOG.md (V1 done), JOURNAL.md.

**Verification:** reproduced V1 (band value list/dict -> unhashable crash) AND a SIBLING the four
auditors all missed - a resolved issue with a list `note` crashes _issue_name .strip() (AttributeError);
band-KEY int and score-VALUE list are safe (verified, not filed). After the fix both crash sites build
clean and a well-formed ledger still yields series [0.4, 0.9], seo improved, resolved finding named.
Mutation check: neutering _sanitize_entry to identity + reverting _issue_name reproduces the exact
TypeError: unhashable (test errors). The test forces the band-rank branch by omitting scores - an early
version passed vacuously because differing scores short-circuit _delta_rows before the band lookup;
caught by the mutation check and fixed. Full battery green: scanner 389, builder 49, charts 8, README
guard exit 0 at 438, compileall clean, dash-clean.

**Learnings:** the three-strike structural call paid off concretely - a per-site BAND_RANK patch would
have shipped while leaving the _issue_name note crash for the next audit (the four auditors, including
the trends slice, did not find it; I only found it by enumerating every value read at the boundary). The
boundary + one same-module value guard closes both. Also relearned the vacuous-test trap: a robustness
test must drive the actual crash path, not a sibling branch that short-circuits it; the mutation check is
what exposes a vacuous assertion.

**Next:** V2 (mixed keyed-object silent drop, Low) then V3 (trend scorecard item coercion, Low), then a
fresh certifying full audit. 2 open (V2, V3); both Low; the Phase V full audit this run already scored
every dimension, so no non-speculative replenishment finding exists to add. Zero High, zero open Medium.
Not converged (V2/V3 Low remain and the certifying audit must re-run clean on the changed code). No
promise.

## Iteration 4 (jeffy N=15) - V2: _as_collection flattens a mixed keyed object (Low, no-silent-drop)

**Task:** V2, top open item. A list field authored as a keyed object whose values were NOT all dicts
(item dicts plus a stray comment key, or a bare-string sibling) fell through _as_collection's all-dict
guard, then _as_rows collapsed the whole object into one bogus row - silently dropping every real
finding and showing a wrong count in the deliverable.

**Files changed:** build_exec_report.py (_as_collection: "ALL values dicts" -> "ANY value is a dict";
dropped the redundant `value and` guard). test_exec_report.py (test_mixed_keyed_object_flattens_and_
drops_nothing). README.md (builder 49->50, total 438->439, badge). BACKLOG.md (V2 done), JOURNAL.md.

**Verification:** a mixed keyed object now flattens to list(values) - both dict findings render and the
stray note renders as a visible text row, nothing dropped. A lone finding dict (all scalar values) is
still one row (U4/T1 preserved); an all-dict keyed object still flattens (U4); empty dict passes through.
Mutation check: reverting to the all-dict guard fails the new test (mixed object not flattened). Full
battery green: builder 49 -> 50, scanner 389, charts 8, README guard exit 0 at 439, compileall clean,
dash-clean.

**Learnings:** the "any value is a dict" signal is the right disambiguation - a keyed collection's values
are records (dicts), a lone record's values are scalars per the schema, so it separates the two cleanly
while honoring the no-silent-drop rule (a stray comment becomes visible content, never a dropped finding).

**Next:** V3 (trend latest_delta.scorecard items not per-item coerced, Low), then a fresh certifying full
audit. 1 open (V3). No non-speculative replenishment finding to add (Phase V scored every dimension this
run). Zero High, zero open Medium; V3 (Low) remains and the certifying audit must re-run clean on the
V1/V2 changes, so not converged. No promise.

## Iteration 5 (jeffy N=15) - V3: per-item coercion of the trend scorecard rows (Low)

**Task:** V3, the last open item. U5/normalize() coerced the trend latest_delta.scorecard CONTAINER to a
list but not its ITEMS, so a non-dict row (str/None) crashed add_trend_table's row.get() on a hand-
authored partial trend.

**Files changed:** build_exec_report.py (_normalize_trend: scorecard now runs through _as_collection then
_as_rows(sc, "category") when a list, else [], mirroring the top-level scorecard.rows treatment).
test_exec_report.py (test_trend_scorecard_with_non_dict_rows_builds_clean). README.md (builder 50->51,
total 439->440, badge). BACKLOG.md (V3 done), JOURNAL.md.

**Verification:** str/None/scalar rows, a keyed-object scorecard, and a non-list scorecard all build
clean; a valid trend still renders its "Security" QoQ row. Mutation check: reverting to container-only
coercion crashes with the exact 'str' object has no attribute 'get'. Full battery green: builder 50 ->
51, scanner 389, charts 8, README guard exit 0 at 440, compileall clean, dash-clean.

**Learnings:** V3 closes the item-level completion of the U6 builder boundary that V2 started; the trend
scorecard is now treated identically to the top-level scorecard.rows (one consistent _as_collection +
_as_rows path). The Phase V three-strike-watch note asked whether the builder would keep leaking item-
level gaps; V2 and V3 were the two remaining and are now closed, so the boundary coerces both container
shape AND item shape everywhere it reads a list of records.

**Next:** all V-series findings closed (V1 Medium, V2/V3 Low). Zero open tasks. The next iteration must
run the certifying FULL convergence audit on the V1/V2/V3-changed code (trends.py sanitizer, _as_collection,
_normalize_trend) - if it rescores every dimension at zero High and zero Medium in-envelope with fresh
evidence, that satisfies the Definition of done. Not converged yet (the certifying audit has not run since
these changes). No promise this iteration.

## Iteration 6 (jeffy N=15) - Phase W: certifying re-audit of V1/V2/V3 (zero High/Medium; 1 Low filed)

**Task:** Backlog empty after V3, so this is the certifying full audit, focused on the code changed since
Phase V (all localized: trends.py sanitizer/_issue_name, build_exec_report.py normalize/_as_collection/
_normalize_trend). Ratchet N/A (no Converged line).

**Method:** git diff --name-only HEAD confirmed only the changed code + state/doc files differ since the
last commit, so the scanner slice and all Phase V slice-A/D clean ground is unchanged with fresh git
evidence; re-confirmed docs/dashes/deps clean inline (no new imports in either changed file, requirements
unchanged). Two independent adversarial auditors hammered the changed code for regressions and residual
gaps; I verified F1 empirically before filing.

**Files changed:** PLAN.md unchanged this iteration; BACKLOG.md (Phase W: W1 filed, F2/F3/F4 declined);
JOURNAL.md. No source changed (audit iteration).

**Verification / auditor verdict:** BOTH fixes complete and regression-free. Auditor 1 (trends): the V1
sanitizer + _issue_name closes the COMPLETE set of trend value-level crash sites (24 corruption cases
across every value read survive; well-formed ledgers still produce correct series/directions/resolved
names; _sanitize_entry does not mutate shared state or drop fields). Auditor 2 (builder): V2 CANNOT mis-
render draft_report_data's own output (no draft item type has a dict-valued field, verified across all six
item types); V3 preserves valid-trend rendering. Battery green: scanner 389, builder 51, charts 8, README
guard exit 0 at 440, compileall clean, dash-clean.

**Audit scores by dimension (Phase W):** architecture None; code quality Low (F1/W1 cosmetic blank row);
security None (git: no scanner/crux/env change); testing None (changed paths covered + mutation-checked);
error handling None (V1 closed the ledger-crash class; auditor confirmed complete); performance None;
documentation None (dashes/counts/deps clean, README synced); dependency hygiene None; correctness Low
(W1 cosmetic; F2/F3/F4 out-of-realistic-envelope, Declined). Overall: ZERO High, ZERO Medium. One worth-
fixing Low (W1). Three Declined (F2/F3/F4) with envelope-based reasons.

**Learnings:** the re-audit confirmed the three-strike structural calls held (V1 sanitizer is complete;
the auditor's independent 24-case sweep found no sibling I missed). The one new item, W1, is an empty-{}
list field rendering a blank row - I verified it empirically because the auditor's old-vs-new reasoning
about the {} path looked internally inconsistent; the behavior (blank row on {}, correct skip on []) is
real regardless. Declined F2/F3/F4 strictly by the Operating envelope (machine-generated / beyond-realistic-
slip), not to reach convergence - convergence is already met on severity (zero High/Medium); W1 is a
worth-fixing Low so it is filed, not deferred-as-Declined.

**Next:** fix W1 (empty dict -> [] in _as_collection), then a final micro-re-audit confirming zero
High/Medium with W1 closed, then convergence. Zero High, zero Medium; W1 (Low) open. Not converged. No
promise this iteration.

## 2026-07-05 - JOURNAL rotation

Rotated at >500 lines: moved the oldest 6 entries (Iteration 2 (N=10) T2 through Iteration 6 (N=10) Phase U audit) to JOURNAL-archive.md, kept the last 10 here. History preserved, not rewritten. Standing: V1/V2/V3 landed and the Phase W certifying re-audit found zero High and zero Medium; one worth-fixing Low (W1) is open, three Lows Declined; not yet converged pending W1 and a final clean re-audit.

## Relaunch iteration 1 (jeffy N=6) - W1: empty-object list field skips its section (Low)

**Task:** W1, the last open finding from the Phase W re-audit. A list field authored as an empty object
({}) rendered a spurious blank row instead of skipping, because _as_collection returned {} for an empty
dict and _as_rows then wrapped the bare {} as one blank item.

**Files changed:** build_exec_report.py (_as_collection returns [] for an empty dict, before the any-dict-
value check). test_exec_report.py (test_empty_object_list_field_skips_section_like_empty_list; updated the
V2 test's _as_collection({}) assertion from {} to []). README.md (builder 51->52, total 440->441, badge).
BACKLOG.md (W1 done), JOURNAL.md.

**Verification:** findings={} now skips the section exactly like findings=[]; nested scorecard.rows/web_
vitals.metrics/key_dates.items = {} skip their sections; a real finding still renders; mixed/all-dict/lone-
dict cases unchanged. Mutation check: removing the empty-dict branch fails the new test ({} != []). Full
battery green: builder 51 -> 52, scanner 389, charts 8, README guard exit 0 at 441, compileall clean, dash-
clean. (One expected fallout: my own V2 test hard-coded the old _as_collection({}) == {} behavior; updated
it to [] since W1 intentionally changes that.)

**Learnings:** W1 completes the empty/degenerate-shape handling of the builder boundary - {} for a list
field now behaves like [] (no items) rather than one blank record, matching author intent. The loop
relaunched with an explicit instruction to run the final audit INLINE, since the prior run exhausted its
15-iteration budget on holding-turns spent waiting for background audit subagents (each turn-end ticks the
ralph counter).

**Next:** all W-series resolved (W1 fixed; F2/F3/F4 Declined). Zero open tasks. The next iteration runs the
final certifying re-audit INLINE on the W1 change (and confirms the V-series still clean); if it rescores
zero High and zero Medium with fresh evidence, the Definition of done is satisfied and it converges. Zero
High, zero Medium, zero open findings. No promise this iteration (the final audit has not yet run on the
W1 change).

## Relaunch iteration 2 (jeffy N=6) - CONVERGENCE: certifying full-audit pass, zero High/zero Medium

**Task:** Backlog empty after W1, so this is the final certifying full-audit pass (run INLINE, no
background agents, so waiting does not consume iterations). Ratchet N/A (no Converged line with a hash).

**Method / evidence:** git diff --name-only HEAD shows only the U6/V-series/W1 code (build_exec_report.py,
trends.py) and their tests changed since the last commit; everything else (all scan_*.py, common.py,
htmlmeta.py, registry.py, scan_site.py, report_charts.py, crawler.py, capture_rendered.py, run_review.py,
etc.) is UNCHANGED, so the Phase V slice-A (scanners) and slice-D (docs/deps/secrets) clean scores hold
with fresh git evidence. Full battery green: scanner 389, builder 52, charts 8, README guard exit 0 at
441, compileall clean, dash-clean. Inline adversarial re-verification of the changed code: every list/
nested-list field authored as {} builds clean (W1); the V-series all still hold post-W1 (V2 mixed keyed
object keeps its findings, V1 unhashable band value does not crash); a full realistic report renders its
bottom line, scorecard, findings, and recommendations sections.

**Closing scores by dimension (all zero High, zero Medium in-envelope):** architecture None; code quality
None (W1 was the last cosmetic Low, fixed); security None (scanners/crux/env unchanged; .env and sales/
ignored and untracked); testing None (every changed path covered and mutation-checked; 441+8 tests green);
error handling None (V1 sanitizer closed the trends ledger-crash class, independently confirmed complete);
performance None; documentation None (dashes/counts/deps clean, README synced); dependency hygiene None
(requirements pinned, no new imports, stdlib guard holds); correctness None (W1 fixed; F2/F3/F4 Declined by
the Operating envelope). Observability n/a. Zero open findings; F2/F3/F4 Declined (out of realistic
envelope), not deferred.

**Convergence:** the Definition of done (PLAN.md section 38: a single full-audit pass rescoring every
applicable dimension at zero High and zero Medium in-envelope with fresh evidence) is genuinely and
verifiably true this iteration. This project's PLAN does not require a commit hash, and no autonomous
commit was made (harness/skill git rules), so the working tree is green and uncommitted for the user's
review, and a future run should re-audit rather than ratchet.

**Learnings:** the whole U6 -> V1/V2/V3 -> W1 arc closed one meta-class (the builder/trend layer crashing
or mis-rendering on malformed hand-authored/state-at-rest input) at two boundaries (normalize() for the
builder, _sanitize_entry for the ledger), which is materially simpler and more complete than the scattered
per-site guards it replaced. The relaunch ran the final audit inline after the first run exhausted its
budget on background-agent wait-turns.

**Next:** converged. Nothing open. Outputting the promise.

## iter 1/3 | 3008acaa | 2026-07-06 | RATCHET | converged
**Task:** Ratchet check on relaunch (jeffy N=3). Verify the recorded convergence anchor still holds so the run converges without re-auditing already-settled code.

**Changed:** JOURNAL.md only (this entry). No product code touched this iteration.

**Checkpoint:** d0879938

**Verification:** BACKLOG.md ## Converged names anchor 67dbb6aa024f0fcbeeef612c6f0c813c0d37e012. git status --porcelain is empty (clean tree). git diff --name-only 67dbb6aa lists only BACKLOG.md, a state file. Every path changed since the anchor is a state file (PLAN/BACKLOG/JOURNAL), so no implementing code has changed since certification; the Phase V/W zero-High/zero-Medium scores stand by the ratchet rule.

**Learnings:** the anchor recorded by the prior run (commit e498f91) makes this relaunch a one-step ratchet rather than a full re-audit, which is the intended fast path when nothing but the ledger moved since convergence.

**Next:** converged. Nothing open. Outputting the promise.

## iter 1/10 | f48e8ba2 | 2026-07-12 | AUDIT | audit
**Task:** Fresh audit after the ratchet broke: BACKLOG's Converged anchor is 67dbb6aa but f224650 (the
executive-grade report upgrade, 20 source files) changed implementing code since it, so the prior
zero-High/zero-Medium scores no longer carry and the backlog was empty.

**Changed:** PLAN.md (new section 39 recording the Verify command and definition of done, both referenced
by the closing rule but never written down; the prompt directs the first audit to fill them), BACKLOG.md
(new Phase X section with X1), JOURNAL.md (this entry).

**Checkpoint:** 53de067

**Verification:** Fresh battery at f224650: scanner suite 395 OK, builder+charts 62 OK (54+8), compileall
clean, dash check clean over every skill .py. check_readme_counts.py exits 1 (badge, summary, suite
comments, tree annotation all stale; actual 395/54/449) and ci.yml runs it as its own step, so CI is red
on the pushed main: filed as X1, the audit's one Medium. Zero High. Consumer sweep of the changed string
contracts: triage.py matches verdicts and bands, never note text; README carries no old-format strings;
tests updated in the same commit. Envelope sweep of the changed surface: labels flow as data with
fallbacks for old drafts and ledgers (verified by rebuilding the old dws draft through the new builder);
count_noun call sites are all len()/int counts; _compact_page keeps full URLs on host mismatch including
port and case differences; the strongest-area pick is structurally safe (category strengths always carry
a colon from their own format); chip rendering and score bars are pinned by the updated builder tests.
Lows, declined with reasons: the builder's local _plural twin of common.count_noun stays because the
builder cannot import tools/ across the JSON seam (documented in both places); the findings section note
says "paths are on the reviewed site" which reads loosely when hand-authored evidence uses full URLs
(cosmetic copy, method text, not a measurement).

**Learnings:** the ratchet did its job: it refused to converge on a tree whose code moved after
certification, and the one real regression the upgrade left (stale README counts) sat exactly in the gap
the count guard was built for. Filling PLAN section 39 turns the previously implicit gate into the
written one the closing rule points at.

**Next:** execute X1 (README counts, the only open task), then re-verify the full gate including the
count guard and assess convergence.

## iter 2/10 | f48e8ba2 | 2026-07-12 | X1 | converged
**Task:** X1 (Medium): update the README test counts the CI guard checks (badge, summary line, both suite
comments, file-tree annotation) to the post-upgrade sizes, then run the certifying gate for convergence.

**Changed:** README.md (five count sites: badge 449, summary 449 total, scanner comment 395, builder
comment 54, tree annotation 395), BACKLOG.md (X1 line deleted per ledger discipline; convergence evidence
appended under Converged), JOURNAL.md (this entry).

**Checkpoint:** pending

**Verification:** Acceptance: check_readme_counts.py exits 0 ("README counts in sync: scanner 395,
builder 54, total 449; 14 scanners, 10 categories"). Verify gate green at this tree: scanner suite 395
OK, builder 54 OK, charts 8 OK, compileall clean. Certification: git diff --name-only 53de067 (the audit
checkpoint) lists only JOURNAL.md and README.md, so no implementing code changed since the iteration-1
fresh audit scored zero High and one Medium; with X1 fixed the tree stands at zero High, zero Medium
in-envelope with the Verify command green, which is the PLAN section 39 definition of done.

**Learnings:** the audit-then-fix split cost one extra iteration but kept the certification honest: the
convergence claim rests on an audit of exactly this code plus a diff proving nothing else moved. Note for
the user: the X1 fix is committed locally only (jeffy never pushes), so CI on the pushed main stays red
until these commits are pushed.

**Next:** converged. Nothing open. Outputting the promise.
