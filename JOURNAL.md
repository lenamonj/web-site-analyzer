# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-05 - JOURNAL rotation

**Task:** housekeeping. JOURNAL.md passed the 500-line rotation threshold, so
the oldest entries move to JOURNAL-archive.md and the last 10 stay here.

**What I did:** moved 6 entries verbatim to JOURNAL-archive.md:
- 2026-07-05 - P39: coerce a non-string evidence code/image in the appendix
- 2026-07-05 - P41: detect an http:// formaction downgrade, not just form action
- 2026-07-05 - P44: fail on multiple SPF records (a permerror)
- 2026-07-05 - P45: warn on the full-URL-leaking referrer policies
- 2026-07-05 - JOURNAL rotation
- 2026-07-05 - P46: fail a cross-host canonical instead of grading presence

**Verification:** archive is append-only and unchanged above the move; JOURNAL.md
now holds the preamble, the last 10 substantive entries, and this rotation note.
No code or state logic touched.

**Next:** P56 (scan_links fabricated mixed-content fail). No promise.

## 2026-07-05 - P56: ignore commented-out markup in the mixed-content scan

**Task:** P56 (Medium, fabricated security fail). _mixed_content ran MIXED_RE over the
raw body, so an http:// script/iframe inside an HTML comment - which no browser fetches
- was graded as active mixed content, fabricating a security vulnerability in the CEO
report (the charter's cardinal sin).

**What I did:** _mixed_content now strips HTML comments via a new _strip_comments helper
before matching (both MIXED_RE and the <link> scan). _strip_comments is a LINEAR string
scan (find "<!--", then "-->"), deliberately NOT a lazy <!--.*?--> regex: I measured
that regex at 37s on 50k unclosed "<!--" (a ReDoS, the N6 class). Scoped to comments
(the reproduced case); left <template>/<noscript> alone as rarer and more arguable.

**Files changed:** scan_links.py (_strip_comments helper, applied in _mixed_content),
test_review_tools.py (new test_mixed_content_ignores_commented_out_markup), README.md
(count resync), BACKLOG.md (P56 done), JOURNAL.md (this entry).

**Verification:** a commented http script -> pass; a comment does not hide a real script
after it -> fail; real uncommented script/img still fail/warn; 20k unclosed "<!--" stays
under 1s (linear, not catastrophic). Scanner 355 -> 356, all green; README resynced to
356/393 (guard exit 0); builder untouched.

**Learnings:** the obvious fix (a lazy comment regex) reintroduces the exact ReDoS the
project already fixed once (N6). A resource's location in the DOM decides whether it is
mixed content: inside a comment it is inert, so the check must model what a browser
actually fetches, not what text appears in the source. When the safe pattern for
"strip a delimited region" is a lazy regex, reach for a linear string scan instead.

**Next:** P57 (a dangling aria-labelledby counts as a real accessible name). Three
Medium and three Low remain, zero High. Not converged. No promise.

## 2026-07-05 - P57: validate aria-labelledby references against the page ids

**Task:** P57 (Medium, presence-not-value). _accessible_name returned "aria-labelledby"
on mere presence of the attribute, so a control whose aria-labelledby points at a
non-existent id (a typo, or a JS-generated id absent from the static DOM) graded as
labeled - assistive tech gets no name, yet the report said "all controls labeled".

**What I did:** _accessible_name now takes the page ids set and credits aria-labelledby
only when at least one referenced id exists (it is a space-separated id list); a
dangling reference falls through to the next name source (title/alt) or None. Scoped to
aria-labelledby - the only reference-based name source here: aria-label is a literal
string, label[for] was already validated (the control id must be in labels_for), and
aria-describedby is a description not a name (never used by _accessible_name).
_form_check passes set(parsed["ids"]).

**Files changed:** scan_accessibility.py (_accessible_name signature + aria-labelledby
validation, _form_check call), test_review_tools.py (extended test_accessible_name and
test_form_check with the new ids arg and dangling/resolved cases), BACKLOG.md (P57
done), JOURNAL.md (this entry). No count change (extended existing tests).

**Verification:** a resolved aria-labelledby -> labeled/pass; a dangling one -> not
labeled (falls through; form_labels fail); a title still names a control whose
aria-labelledby dangles; existing labeled/unlabeled/placeholder cases unchanged. Scanner
356, all green; README total 393 (guard exit 0); builder untouched.

**Learnings:** an id reference is only as good as its target - the presence-not-value
class in its cross-reference form. aria-label (a literal) and aria-labelledby (a
pointer) look symmetric in the attribute list but are not: the pointer has to resolve.
The other reference source, label[for], was already validated the same way (control id
in labels_for), which is why only aria-labelledby leaked.

**Next:** P58 (the image-dimension check accepts any "width" substring, so a
max-width:100% responsive image false-passes the layout-shift check). Two Medium and
three Low remain, zero High. Not converged. No promise.

## 2026-07-05 - P58: grade image dimensions by declared property, not a width substring

**Task:** P58 (Medium, substring-on-structured-data). The layout-shift check matched any
style attribute containing the substring "width", so max-width:100%, min-width, and a
bare percentage width (all reserve no vertical space) false-passed as "declares
dimensions", hiding the exact CLS pattern the check exists to catch.

**What I did:** replaced the substring STYLE_DIM_RE with STYLE_ATTR_RE (captures the
style value) plus a _style_reserves_space helper that parses the CSS declarations by
property NAME and reserves space only on aspect-ratio, or an explicit width AND height.
So max-width/min-width (distinct property names) and a width with no height no longer
count; the width/height HTML-attribute branch is unchanged.

**Files changed:** scan_design.py (STYLE_ATTR_RE, _style_reserves_space helper,
check_image_dimensions), test_review_tools.py (new
test_style_dimensions_grade_properties_not_a_width_substring), README.md (count resync),
BACKLOG.md (P58 done), JOURNAL.md (this entry).

**Verification:** max-width:100% / min-width / width:100% / height:auto -> warn (missing
dimensions); width:800px;height:600px / aspect-ratio / aspect-ratio+width / width+height
HTML attrs -> pass. Scanner 356 -> 357, all green; README resynced to 357/394 (guard exit
0); builder untouched.

**Learnings:** substring-on-structured-data again, this time on CSS - "width" as a
substring matches max-width and min-width, which are different properties that reserve
no space. Parsing declarations by property name (split on ; then :) is the CSS analogue
of the ';'-boundary tag parsing the DKIM/DMARC checks already use; the meaning lives in
the property name, not in the character sequence.

**Next:** P59 (any CAA record grades "restricts issuance", even an iodef-only record
that restricts nothing). One Medium and three Low remain, zero High. Not converged. No
promise.

## 2026-07-05 - P59: grade CAA on the issue/issuewild tag, not mere presence

**Task:** P59 (Medium, presence-not-value on DNS). check_caa graded pass on any CAA
answer, so an iodef-only record (an incident-reporting contact that restricts nothing)
was reported as "CAA restricts certificate issuance" though any public CA could still
issue.

**What I did:** added _restricts_issuance(record) - it reads the tag (second token of
the "<flags> <tag> <value>" presentation format) and returns True only for
issue/issuewild. check_caa passes only when at least one record restricts issuance (and
the note lists only those); a CAA set with no issue/issuewild (iodef- or
contactemail-only) grades info "present but no issue/issuewild, any public CA may still
issue"; no CAA stays info.

**Files changed:** scan_tls.py (_restricts_issuance helper, check_caa grading),
test_review_tools.py (new test_caa_iodef_only_does_not_restrict_issuance), README.md
(count resync), BACKLOG.md (P59 done), JOURNAL.md (this entry).

**Verification:** iodef-only and contactemail-only -> info; issue and issuewild -> pass;
iodef+issue -> pass naming only the issue record; no CAA -> info. Scanner 357 -> 358, all
green; README resynced to 358/395 (guard exit 0); builder untouched.

**Learnings:** the presence-not-value class on DNS again - a CAA answer's meaning is in
its tag, and only issue/issuewild are restrictions; iodef/contactemail are present but
inert. Same shape as the SPF/DKIM/DMARC tag parsing: read the structured field's tag,
never grade the record's mere existence. This closes the last Medium of the P49-run
replenishment.

**Next:** the Low tail - P50 (viewport width=device-width), P55 (snapshot filename
churn), P60 (far-future cert expiry crash). Zero High, zero Medium open. When the Low
clear, the next iteration runs the full convergence audit that can certify done. Not
converged. No promise.
## 2026-07-05 - JOURNAL rotation

**Task:** housekeeping. JOURNAL.md passed the 500-line rotation threshold, so
the oldest entries move to JOURNAL-archive.md and the last 10 stay here.

**What I did:** moved 5 entries verbatim to JOURNAL-archive.md:
- 2026-07-05 - P42: require a real hash token before crediting SRI
- 2026-07-05 - P43: credit Expires and s-maxage as caching lifetimes
- 2026-07-05 - P47: treat an empty DKIM p= as a revoked key
- 2026-07-05 - P48: grade an absent Permissions-Policy as info, not a hard fail
- 2026-07-05 - JOURNAL rotation

**Verification:** archive is append-only and unchanged above the move; JOURNAL.md
now holds the preamble, the last 10 substantive entries, and this rotation note.
No code or state logic touched.

**Next:** P50 (viewport width=device-width). No promise.

## 2026-07-05 - P50: require width=device-width for a mobile-friendly viewport

**Task:** P50 (Low, presence-not-value). The viewport check passed on any non-empty
content, but Google's mobile-friendly criterion is width=device-width; a fixed-width
viewport (content="width=1024") is present but not responsive.

**What I did:** extracted _viewport_check(viewport) - absent -> fail (unchanged); a value
containing width=device-width (space- and case-insensitive) -> pass "Responsive viewport
set"; present but without it (width=1024, or a width-less value) -> warn "set but not
responsive".

**Files changed:** scan_seo.py (_viewport_check helper, viewport check now calls it),
test_review_tools.py (new test_viewport_check), README.md (count resync), BACKLOG.md (P50
done + P61-P63 filed), JOURNAL.md (this entry).

**Verification:** width=device-width (incl. uppercase, with initial-scale) -> pass;
width=1024 and initial-scale-only -> warn; None/"" -> fail. Scanner 358 -> 359, all green;
README resynced to 359/396 (guard exit 0); builder untouched.

**Learnings:** presence-not-value once more, and the last of the P41-run Low tail's
grading fixes - "has a viewport" is not "is responsive"; the value that matters is the
width=device-width directive.

**Replenishment (P50-run partial audit):** completing P50 left two open (below three), so
I audited the least-recently-scored DIMENSIONS - documentation accuracy, test-suite
integrity, and the aggregator/CLI orchestration (the prior four rounds swept the code). An
auditor swept them read-only; I reproduced every finding myself. The orchestration layer
and the doc counts/defaults were clean. Filed P61 (Medium: TestBuildMainInputGuard lacks
the skipUnless(HAVE_DOCX) guard its siblings carry, so without python-docx its 5 tests
error with NameError instead of skipping, contradicting the module docstring's "Skipped
entirely" - reproduced with docx blocked: errors 5, skipped 0), P62 (Low: two inaccurate
README statements - network isolation is not "suite-wide", and "Both test suites" should
be three), and P63 (Low: the cover-contents "in_order" test checks membership, not order).

**Next:** P61 (the missing skipUnless guard), the one new Medium. One Medium and four Low
now open, zero High. The docs/tests dimension sweep surfaced a Medium, so convergence is
not yet reachable. Not converged. No promise.

## 2026-07-05 - P61: guard TestBuildMainInputGuard on python-docx like its siblings

**Task:** P61 (Medium, misleading docs + broken skip path). TestBuildMainInputGuard
lacked the @unittest.skipUnless(HAVE_DOCX, ...) decorator its three sibling classes
carry, and its 5 tests reference ber (bound only under `if HAVE_DOCX:`), so without
python-docx they raised NameError instead of skipping - contradicting the module
docstring's "Skipped entirely when python-docx is not installed".

**What I did:** added @unittest.skipUnless(HAVE_DOCX, "python-docx not installed") above
the class, matching TestExecReport/TestTrendSection/TestReportLabel.

**Files changed:** test_exec_report.py (one decorator), BACKLOG.md (P61 done), JOURNAL.md
(this entry). No code or count change (a decorator, not a new test method).

**Verification:** with the docx import blocked, the class's 5 tests SKIP (errors 0,
skipped 5), no NameError; with docx present the full builder suite runs and passes (37).
TestBuilderDependencies stays unguarded by design - it reads requirements.txt to assert
the deps are declared, so it must run without docx. Scanner 359 and README total 396
unaffected (guard exit 0).

**Learnings:** a skip guard is load-bearing infrastructure, not a formality - a test
class that references a conditionally-imported symbol MUST carry the same guard as the
import, or the "optional dependency" contract breaks exactly for the contributor the
option exists to serve. The docstring was the tell: it promised a behavior the newest
class did not honor.

**Next:** the Low tail - P55 (snapshot filename churn), P60 (far-future cert expiry
crash), P62 (two inaccurate README statements), P63 (vacuous cover-order test). Zero
High, zero Medium open. When the Low clear, the next iteration runs the full convergence
audit that can certify done. Not converged. No promise.

## 2026-07-05 - P55: reuse a DOM page's snapshot filename across runs

**Task:** P55 (Low, determinism/disk hygiene). taken is seeded from the manifest, which
already holds a refreshed URL's own filename, so snapshot_filename allocated a NEW name
each run - the file oscillated (home.html -> home-2.html -> home.html) and each run
orphaned the prior snapshot on disk. The deliverable stayed correct (scan_site reads the
manifest-referenced file), so this was internal evidence hygiene.

**What I did:** the DOM-snapshot branch now reuses manifest["pages"][url]["file"] when
the URL already has an entry, and calls snapshot_filename only for a URL new to the
manifest, so a refresh keeps its slot.

**Files changed:** capture_rendered.py (snapshot filename reuse), test_review_tools.py
(new test_refreshing_a_dom_page_reuses_its_snapshot_filename), README.md (count resync),
BACKLOG.md (P55 done), JOURNAL.md (this entry).

**Verification:** capturing the same DOM page three times -> one stable filename, exactly
one .html on disk (no orphan); the distinct-page and manual-merge tests still pass, so
genuinely new URLs still get distinct names. Scanner 359 -> 360, all green; README
resynced to 360/397 (guard exit 0); builder untouched.

**Learnings:** an idempotency bug hidden by a correct-enough output - the report read the
manifest's current file, so the churn only showed as orphaned files and run-to-run
filename drift. Seeding a uniqueness set from state that already contains the item you
are about to re-key is the trap: allocate a new key only for genuinely new items, reuse
the existing key otherwise.

**Next:** P60 (a far-future cert notAfter crashes gmtime on Windows, aborting the TLS
scan). Zero High, zero Medium; three Low remain (P60, P62, P63). Not converged. No
promise.

## 2026-07-05 - P60: guard far-future cert-expiry formatting against a gmtime crash

**Task:** P60 (Low, uncaught crash). time.strftime(time.gmtime(expiry_epoch)) raises
OSError on Windows for a notAfter past ~year 3000, uncaught in _scan, aborting the whole
TLS scan.

**What I did:** wrapped the strftime/gmtime call in try/except (OSError, ValueError,
OverflowError); on failure expires_on is set to None (the display date is dropped, never
fabricated) and days_left - plain arithmetic in _parse_not_after, not gmtime - still
drives the verdict.

**Files changed:** scan_tls.py (guarded expires_on formatting), test_review_tools.py (new
test_far_future_cert_expiry_does_not_abort_the_scan), README.md (count resync), BACKLOG.md
(P60 done + P64-P66 filed), JOURNAL.md (this entry).

**Verification:** notAfter year 9999 -> scan ok, expiry pass (huge days_left),
expires_on None; a 2027 cert still formats "2027-08-29"; an expired 2020 cert still fails.
Scanner 360 -> 361, all green; README resynced to 361/398 (guard exit 0); builder
untouched.

**Learnings:** degrade the derived DISPLAY value, keep the load-bearing computation -
days_left (arithmetic) is robust where gmtime (a platform C call) is not, so the verdict
survives even when the pretty date cannot be formatted. Dropping expires_on to None is
honest (no fabricated date); crashing the category was not.

**Replenishment (P60-run partial audit):** completing P60 left two open (below three), so
I audited the cross-cutting NUMERIC core - the scorecard rollup, band thresholds, and
trend/delta math - where a wrong number is a wrong deliverable. An auditor swept it
read-only; I reproduced every finding myself. Medians, quarter bucketing, the grouped
multi-page diff identity, and every guarded division were sound. Filed P64 (Medium: a
crashed scanner leaves the overall band Strong/1.0 and draft() drops the crash entirely -
reproduced: tls scanner ok=False + all else passing -> overall Strong, crashed tool absent
from report data; a gap in P7, which surfaces the crash in the digest/console but not the
docx), P65 (Medium: diff_issues keys on verdict, so a warn->fail defect is counted 1 new
AND 1 resolved and named "resolved" though it worsened - reproduced), and P66 (Low: band
from the unrounded score but the rounded score is displayed, so a boundary row shows e.g.
"Adequate (score 0.85)" with 0.85 being the Strong cutoff).

**Next:** P64 (crashed scanner -> uncaveated Strong headline), the higher-impact new
Medium (a single-scanner crash is common). Two Medium and three Low now open, zero High.
The numeric-core sweep reopened Medium findings, so convergence is further off, correctly.
Not converged. No promise.
## 2026-07-05 - JOURNAL rotation

**Task:** housekeeping. JOURNAL.md passed the 500-line rotation threshold, so
the oldest entries move to JOURNAL-archive.md and the last 10 stay here.

**What I did:** moved 5 entries verbatim to JOURNAL-archive.md:
- 2026-07-05 - P51: fetch only same-domain sitemaps in discover_pages
- 2026-07-05 - P52: gate the CWV strength on a complete field capture
- 2026-07-05 - P53: recover the body when an unclosed title swallows it
- 2026-07-05 - P54: coerce the last two non-string scalars in the builder
- 2026-07-05 - P49: require a dotted version before the version-banner warn

**Verification:** archive is append-only and unchanged above the move; JOURNAL.md
now holds the preamble, the last 10 substantive entries, and this rotation note.
No code or state logic touched.

**Next:** P64 (crashed scanner -> uncaveated Strong headline). No promise.

## 2026-07-05 - P64: surface a scanner crash in the deliverable and caveat the headline

**Task:** P64 (Medium, unmeasured-reported-as-clean at the overall level). build_scorecard
forces a crashed scanner's CATEGORY to Not measured (P7) but grades the OVERALL band from
the surviving categories and only bolts on an errors key; draft() then dropped
scanner_errors and the errors keys, so the CEO deliverable read "Strong" with no trace of
which category went unmeasured.

**What I did:** fixed in the data layer (draft_report_data), which the builder already
renders. _scorecard now carries scan["scanner_errors"] into the report data as
scorecard.scanner_errors, and bottom_line - the executive callout the builder renders
verbatim - gains a caveat clause when any scanner errored ("N scanner(s) could not
measure their category (<tools>), so this posture covers only the measured categories").
No new builder element: the per-category Not-measured row from P7 already shows in the
table, and the headline now explains it.

**Files changed:** draft_report_data.py (_scorecard scanner_errors passthrough,
bottom_line caveat), test_review_tools.py (new test_scanner_crash_is_surfaced_and_
caveats_the_headline), README.md (count resync), BACKLOG.md (P64 done), JOURNAL.md (this
entry).

**Verification:** a tls-category crash + all else passing -> report data names scan_tls in
scorecard.scanner_errors and bottom_line reads "...Strong...; 1 scanner(s) could not
measure their category (scan_tls), so this posture covers only the measured categories";
the no-crash base SCAN has empty scanner_errors and no caveat. Scanner 361 -> 362, builder
37 green (the new key is inert to the builder); README resynced to 362/399 (guard exit 0).

**Learnings:** P7 stopped the fabrication one layer too early - it corrected the category
band and the internal digest/console but not the deliverable's headline, so the overall
recovered a false clean. Fixing the data layer was enough because bottom_line is already
rendered verbatim; the cheapest honest fix routes the caveat through an existing surface
rather than adding a new one.

**Next:** P65 (a warn->fail defect counted as both resolved and new in the trend delta).
One Medium and three Low remain, zero High. Not converged. No promise.

## 2026-07-05 - P65: key the issue delta on (scan, check), not the verdict

**Task:** P65 (Medium, false improvement claim). diff_issues keyed the grouped identity
on (scan_label, check, verdict), so a defect that worsened warn->fail produced two
distinct keys - the fail counted "new" and the warn counted "resolved" - and the trend
section named the still-present, now-worse defect as resolved.

**What I did:** dropped the verdict from the key: diff_issues now keys on
(scan_label, check) only, so a verdict change (warn<->fail) is the same persistent defect
and is neither new nor resolved. Kept it minimal (no separate "worsened" bucket); the
docstring now explains why the verdict is excluded.

**Files changed:** scan_site.py (diff_issues key + docstring), test_review_tools.py (new
test_diff_issues_treats_a_verdict_change_as_persistence), README.md (count resync),
BACKLOG.md (P65 done), JOURNAL.md (this entry).

**Verification:** warn->fail and fail->warn -> 0 new / 0 resolved; a genuinely gone defect
-> 0/1; a genuinely new one -> 1/0; the existing new/resolved and defects-not-pages diff
tests still pass. Scanner 362 -> 363, all green; README resynced to 363/400 (guard exit
0); builder untouched.

**Learnings:** identity is what you compare by, and the verdict is a property OF a defect,
not part of WHICH defect it is - folding a mutable attribute into an identity key turns
every change of that attribute into a delete-plus-create. The grouped-finding view the
report shows already treats a defect as one thing across verdicts; the delta had to match
that identity or it would contradict the findings table.

**Next:** the Low tail - P62 (two inaccurate README statements), P63 (vacuous cover-order
test), P66 (band vs rounded-score boundary). Zero High, zero Medium open. When the Low
clear, the next iteration runs the full convergence audit that can certify done. Not
converged. No promise.

## 2026-07-05 - P62: correct two inaccurate README statements

**Task:** P62 (Low, misleading docs). README.md:239 claimed network primitives are stubbed
"suite-wide so no test can ever reach a real network", but only http_post_json/env_value/
rdap_domain are stubbed at import; http_fetch/tls_info/doh_query are per-test. README.md:261
said "Both test suites" though CI runs three plus the count guard.

**What I did:** reworded :239 to name what is stubbed suite-wide (the CrUX call, the
credential reader, RDAP) versus per-test (HTTP fetch, TLS, DoH), dropping the overstated
"no test can ever"; changed :261 to "All three test suites + README-count guard".

**Files changed:** README.md (two lines), BACKLOG.md (P62 done + P63... no new findings),
JOURNAL.md (this entry). Documentation-only, no code/test/count change.

**Verification:** ci.yml confirmed to run test_review_tools, test_exec_report,
test_report_charts, and check_readme_counts.py (so "three suites + guard" is accurate); the
stubbing description matches what is patched suite-wide vs per-test. Count guard still in
sync (400 total; prose edits do not touch counts).

**Replenishment (P62-run partial audit):** completing P62 left two open (below three), so I
audited the least-covered remaining layer - the plumbing: the registry, the contract
finalizer (finalize/verdicts_of/grade), the CONCURRENCY (the ThreadPoolExecutor fan-out in
scan_links/scan_performance and the reference-counted fetch cache), and the pipeline glue.
An auditor swept it read-only and found ZERO reproducible defects; I re-verified the two
highest-value claims myself - _FETCH_CACHE_LOCK guards every cache access, and a worker
exception PROPAGATES out of scan_links.scan (recorded by _safe_scan as an errored scanner,
now surfaced post-P64, never a fabricated clean pass). Cache integrity under 40 threads,
deterministic output under a racy network, and a balanced cache lifecycle across the nested
run all held. No findings filed - a clean partial audit is a valid outcome, and I did not
manufacture marginal ones to pad the backlog.

**Next:** P63 (the cover-contents "in_order" test checks membership, not order). Zero High,
zero Medium; two Low remain (P63, P66). Not converged. No promise.
