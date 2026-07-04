# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-04 - L10: DRY the self-describing scan() wrapper into common.finalize

**Task:** L10 (M), first task of the second /jeffy run. The three-line scan()
tail (stamp category, stamp grade from the tool's own verdicts, return) was
copy-pasted verbatim into all 14 scanners.

**What I did:** added common.finalize(result, category) that stamps category and
the rolled-up grade and returns the dict. Confirmed the three-line block was
byte-identical across all 14 scanners (a script check), then replaced each with
a single `return common.finalize(result, CATEGORY)`. grep confirms no scanner
stamps grade inline anymore.

**Scope decision (recorded per the no-behavior-change constraint):** the task
also named the pass/warn/fail tally loop duplicated across scanners. I did NOT
fold it into finalize, because scan_tls uniquely emits no summary key; a
finalize that always computed summary would add one to scan_tls, an observable
output change. The tally consolidation is filed as L13 (a common.summarize
helper that leaves scan_tls alone).

**Files changed:** common.py (finalize), the 14 scan_*.py wrappers,
test_review_tools.py (test_finalize_stamps_category_and_grade), BACKLOG.md (L10
done, L13 added), JOURNAL.md (this entry).

**Verification:** captured a canned offline scan of scan_http_security before
and after (stubbed http_fetch, five folded headers): category security, grade
band Strong score 0.88, summary {pass 7, warn 0, fail 1, info 2} - byte
identical both ways, proving no scorecard change. Scanner suite 272 -> 273
(finalize unit test), builder 31, both green. git diff is a clean -3/+1 per
scanner with no line-ending noise (.gitattributes forces LF).

**Learnings:** the safe way to DRY a wrapper that is "identical" across many
files is to first prove byte-identity mechanically, then replace mechanically,
then prove output-identity on a canned run - not to eyeball it. The asymmetry
(scan_tls has no summary) is exactly the kind of thing a blind fold-everything
refactor would have silently changed.

**Next:** L11 - add a CI step that fails when the README test counts disagree
with the actual suite counts.

---

## 2026-07-04 - L11: CI guard against README test-count drift

**Task:** L11 (Low). The README test counts went stale (L7) because nothing
checked them; L10 immediately re-staled them (scanner 272 -> 273). Close the
loop with an automated check.

**What I did:** new tools/check_readme_counts.py counts the test cases in both
suites with unittest loaders (loads, does not run them) and asserts README's
five count sites (badge, summary line, both suite command comments, file-tree
annotation) all cite the current numbers; it exits non-zero with a specific
list on any mismatch. Added a ci.yml step "README test counts in sync" after
the builder suite (so python-docx is installed for the builder-module import).
The check caught L10's drift on first run; updated README to 273/31/304.

**Files changed:** tools/check_readme_counts.py (new), README.md (four counts to
273/304), .github/workflows/ci.yml (new step), BACKLOG.md (L11 done),
JOURNAL.md (this entry).

**Verification:** with correct counts the check prints "in sync" and exits 0;
temporarily rewriting "304 tests total" to "999 tests total" made it exit 1
naming the summary-line mismatch, then README was restored (confirmed equal).
The step is in ci.yml. Scanner suite still green at 273 (the script is a
utility like crawler.py/triage.py, not a registered scanner or a test module,
so it does not change the suite count).

**Learnings:** a documentation fact that must track code (a test count, a
version, a file list) should be verified by CI, not by discipline; L7 fixed the
symptom, L11 removes the cause. Counting via the TestLoader instead of re-running
keeps the check fast and independent of the suites that already run.

**Replenishment (open tasks fell to two):** a partial audit found no new
High/Medium. It did surface one same-class doc-guard gap: README line 17
hard-codes "14 registered scanners, 10 scorecard categories" (currently correct
per the registry, but unguarded), filed as L14 to extend the L11 check.

**Next:** L12 - harden the DKIM/DMARC presence checks to match tags at
";"-boundaries rather than as bare substrings.

---

## 2026-07-04 - L12: DKIM/DMARC presence checks match tags, not substrings

**Task:** L12 (Low), the last known L5-family substring-on-structured-data spot.
The DKIM probe detected a key via "p=" in the record, and DMARC aggregate
reporting via "rua=" in the record - both bare substrings, so a base64 blob
containing "p=" or a value containing "rua=" could false-positive. Hardening,
not a live bug (records live at fixed _domainkey/_dmarc names).

**What I did:** new _is_dkim_record(record) parses ";"-separated tags and
detects a DKIM key by a v=DKIM1, k, or p tag at a real boundary; check_dkim
probes through it. check_dmarc has_rua now checks whether any ";"-split tag
starts with rua=. Because tag parsing keys on the text before the first "=",
a "p=" buried mid-string becomes part of a longer key, not the p tag, so the
false positive is structurally impossible.

**Files changed:** scan_dns_email.py (_is_dkim_record, check_dkim probe,
check_dmarc has_rua), test_review_tools.py (two tests), README.md (counts
resynced to 275/306), BACKLOG.md (L12 done, L15 added), JOURNAL.md (this entry).

**Verification:** two tests reproduce the false positives (a
google-site-verification value containing "p=", a ruf= value containing
"rua=") - both mis-detected before the fix, correct after - and confirm real
DKIM/DMARC records still detect. Scanner suite 273 -> 275, green. The L11 CI
guard then flagged the README drift (275 vs 273); resynced README to 275/306
and re-ran the guard to exit 0 - L11 doing exactly its job on its first real
count change.

**Replenishment (open fell to two):** partial audit of the remaining dns_email
record reads. SPF, DMARC p=, MTA-STS mode:, and all record-type detection
already parse at boundaries (startswith on the trimmed record/line). One more
substring spot found: check_bimi has_logo uses "l=" in rec.lower(); filed as
L15. No new High/Medium.

**Learnings:** parsing keyed on the delimiter before "=" is self-defending -
the fix is not "also check it is a real tag" bolted on, it falls out of parsing
the record the way its grammar defines it. L11 immediately paid off by catching
the count drift this task introduced.

**Next:** L13 - extract the duplicated pass/warn/fail tally into
common.summarize, leaving scan_tls (which emits no summary) untouched.

---

## 2026-07-04 - L13: extract the pass/warn/fail tally into common.summarize

**Task:** L13 (Low, discovered during L10). The summary tally loop was
copy-pasted across 13 scanners in two variants (12 used c["verdict"], which
raises if a check lacks a verdict; scan_http_security used
c.get("verdict","info")).

**What I did:** added common.summarize(checks) using the robust default-to-info
form, and replaced the inline tally in all 13 scanners via a scripted edit that
matched both variants and asserted exactly one block per file. scan_tls was
left untouched because it uniquely emits no summary (the reason L10 could not
fold this into finalize). The 12 c["verdict"] sites now also default missing
verdicts to info, which is strictly safer and identical for well-formed checks.

**Files changed:** common.py (summarize), the 13 scan_*.py that build a summary,
test_review_tools.py (test_summarize_counts_verdicts), README.md (counts to
276/307), BACKLOG.md (L13 done, L16 added), JOURNAL.md (this entry).

**Verification:** captured a canned http_security summary before
({pass 7, warn 0, fail 1, info 2}) and after - byte identical. grep shows no
scanner builds the {"pass":0,...} tally inline. Scanner suite 275 -> 276,
builder 31, both green. The L11 guard again flagged the count drift (276 vs
275); README resynced and re-checked to exit 0.

**Replenishment (open fell to two):** partial audit. The builder's single broad
except (build_exec_report.py:1038) is fine - it writes "[image not embedded]"
into the docx, surfacing the error rather than swallowing it. Real gap found:
check_readme_counts.py (the L11 CI gate) has no test while crawler/triage do;
filed as L16. No new High/Medium.

**Learnings:** L10 and L13 together removed both halves of the copy-pasted
self-describing tail (category+grade, then the tally), each verified by
byte-identical canned output rather than by inspection. Keeping them as separate
tasks was right: the tally carried the scan_tls asymmetry that the wrapper did
not.

**Next:** L14 - guard README line 17's "14 registered scanners, 10 scorecard
categories" against the registry in the same CI check.

---

## 2026-07-04 - JOURNAL rotation

Moved the 6 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.

---

## 2026-07-04 - L14: guard README registry counts in the CI check

**Task:** L14 (Low). README line 17 states "14 registered scanners, 10
scorecard categories" - hard-coded facts the L11 test-count check did not
cover, so adding a scanner would silently stale them.

**What I did:** check_readme_counts.py now imports the registry, computes
len(host_tools + page_tools) and the number of distinct categories, and adds
"N registered scanners" and "M scorecard categories" to the checked needles.
One check now guards both the test counts and the registry counts.

**Files changed:** tools/check_readme_counts.py (registry import + two needles),
BACKLOG.md (L14 done, L17 added), JOURNAL.md (this entry). No README change
needed - line 17's 14/10 already match the registry.

**Verification:** the check prints "14 scanners, 10 categories" and exits 0;
rewriting "14 registered scanners" to "99 registered scanners" made it exit 1
naming that needle, then README was restored (confirmed equal). It already runs
in the L11 CI step. Scanner suite green at 276.

**Replenishment (open fell to two):** partial audit. Genuine load-bearing gap
found: nothing enforces the pure-stdlib scanner charter (PLAN.md principle 2).
I ast-parsed every scanner's imports against sys.stdlib_module_names plus the
local set - zero external today, so the invariant holds - and filed L17 to add
a CI/suite guard so a stray "import requests" cannot silently break it. No new
High/Medium.

**Learnings:** documentation counts and design invariants share a failure mode
- both are true until a change makes them false with nothing watching. The
cheap fix is the same: derive the truth from the code (TestLoader, the registry,
an ast import scan) and fail CI on divergence, rather than trusting a human to
update prose.

**Next:** L15 - tag-boundary match for the BIMI has_logo check (the last known
substring-on-structured-data spot).

---

## 2026-07-04 - L15: BIMI has_logo matches a tag, not a substring

**Task:** L15 (Low), the last known substring-on-structured-data spot.
check_bimi set has_logo via "l=" in rec.lower(), so an "l=" inside another
tag's value (e.g. an a= evidence URL like a=https://host/l=x.pem) would
false-positive as a logo tag.

**What I did:** has_logo now checks whether any ";"-split tag starts with "l=".
Same one-line pattern as the L12 DMARC rua fix.

**Files changed:** scan_dns_email.py (check_bimi has_logo),
test_review_tools.py (test_bimi_logo_keys_on_tag_boundary), README.md (counts
to 277/308), BACKLOG.md (L15 done, L18 added), JOURNAL.md (this entry).

**Verification:** the test reproduces the false positive (an a=.../l=x.pem
record read as having a logo) before the fix and confirms a real l= tag still
reports one. Scanner suite 276 -> 277, green; the L11/L14 guard flagged the
count drift and README was resynced to 277/308 (exit 0). This closes the
substring-on-structured-data family: L1, L4 (headers), L5 (SPF), L12
(DKIM/DMARC), L15 (BIMI).

**Replenishment (open fell to two):** swept header-as-list handling in the
non-http_security scanners (the L1 class). scan_performance is already
list-safe in its parsing paths - _cache_max_age and _asset_caching_check both
join a list before .lower(), and content-length is guarded by str().isdigit()
- so no crash exists there. One cosmetic gap: _caching_check embeds a
duplicated Cache-Control straight into an info note, rendering a Python list
repr; filed as L18 (normalize via common.header_value). No new High/Medium.

**Learnings:** the sweep confirmed the header-as-list defect was localised to
scan_http_security (fixed in L1/L4); the other header consumer, scan_performance,
had been written list-aware from the start. Auditing the whole class after
fixing one instance is what turns "fixed a bug" into "the class is closed".

**Next:** L16 - give check_readme_counts.py a pure, unit-tested core so the CI
gate itself has coverage.

---

## 2026-07-04 - L16: unit-test the README count guard via a pure core

**Task:** L16 (Low). check_readme_counts.py (the L11/L14 CI gate) had no test,
unlike crawler.py and triage.py.

**What I did:** extracted a pure readme_mismatches(text, scanner, builder,
scanners, categories) -> list of mismatch strings (no IO), so the comparison
logic is unit-testable; main() now measures the counts and calls it. Added
TestReadmeCountGuard with three cases: a matching README yields no mismatches,
a wrong scanner count is reported (badge/summary/comment/tree), and a wrong
registry count is reported by name.

**Files changed:** tools/check_readme_counts.py (extract pure function),
test_review_tools.py (TestReadmeCountGuard, 3 tests), README.md (counts to
280/311), BACKLOG.md (L16 done, L19 added), JOURNAL.md (this entry).

**Verification:** the three tests pass over in-memory README strings; the CLI
still works (ran it, it flagged the +3-test drift, then passed after README
resync). Scanner suite 277 -> 280, builder 31, both green. The gate now guards
its own logic, and the L11/L14 gate flagged its own count change - self-checking
end to end.

**Replenishment (open fell to two):** partial audit of two more classes, both
clean. No unguarded int()/float() on external data in the scanners (all behind
str().isdigit(), a regex \d+ group, the _MONTHS map, or the
stdlib-guaranteed-numeric robots crawl_delay); the builder reads report data
defensively (.get with fallbacks; the single required data['slug'] raises a
clear error by design). Genuine gap filed as L19: the L1/L4 header-as-list
never-raise fix is only locked in for the two directly-tested scanners, so a
contract-level test feeding every host tool duplicated headers would close the
class suite-wide. No new High/Medium.

**Learnings:** a CI gate is code too, and untested gate logic is a blind spot -
extracting a pure core made it as testable as any parser. The self-referential
moment (the count gate catching the drift caused by adding its own test) is the
system working as designed.

**Next:** L17 - guard the pure-stdlib scanner charter with an ast import scan.

---

## 2026-07-04 - L17: CI guard for the pure-stdlib scanner charter

**Task:** L17 (M). PLAN.md principle 2 and the README badge claim the scanners
have zero third-party dependencies, but nothing enforced it - a stray "import
requests" would silently break the charter.

**What I did:** TestScannerCharter.test_scanners_import_only_stdlib_and_local
ast-parses every scan_*.py and asserts each top-level import is in
sys.stdlib_module_names or a local .py stem (common, registry, htmlmeta,
sibling scanners, and any other tools/ module). A second test proves the guard
is not vacuous by confirming a synthetic "import requests" is flagged. It lives
in the offline suite, so it runs in CI with no extra step.

**Files changed:** test_review_tools.py (TestScannerCharter, 2 tests),
README.md (counts to 282/313), BACKLOG.md (L17 done, L20 added), JOURNAL.md
(this entry).

**Verification:** both tests pass. End to end: injecting "import requests" into
scan_seo.py made the guard fail and name the offender (scan_seo.py, requests),
then the file was restored. Scanner suite 280 -> 282, green; README resynced to
282/313 (the count guard flagged the drift).

**Replenishment (open fell to two):** partial audit of two more classes, both
clean. No mutable default arguments anywhere in the suite; discover_pages core
functions are tested (discover() covered indirectly via run_review's
integration test). Filed L20 (an output-quality sweep for raw-value-repr leaks,
the class L18 exemplifies) as the one genuine remaining item. No new
High/Medium.

**Learnings:** L17 completes a trio - L11/L14 guard documented counts, L16
tests that guard, L17 guards a design invariant - all by deriving truth from the
code (TestLoader, the registry, an ast scan) and failing CI on divergence. The
substantive bug work finished in the first run; this run has been converting
"true by discipline" facts into "enforced by CI" ones, which is the honest
remaining value at this maturity.

**Next:** L18 - normalize the duplicated-Cache-Control list repr in
scan_performance._caching_check via common.header_value.

---

## 2026-07-04 - L18: normalize duplicated Cache-Control in _caching_check

**Task:** L18 (Low). scan_performance._caching_check embedded a duplicated
Cache-Control header (folded to a list) straight into its info note and stored
value, so an origin+CDN double header rendered as a Python list repr
("Cache-Control: ['no-store', 'no-cache']."). Info-only, no crash, but
unpolished.

**What I did:** read the header through common.header_value (the L1 helper),
which coalesces a list to its last value, so the note and stored cache_control
are always a clean string.

**Files changed:** scan_performance.py (_caching_check header read),
test_review_tools.py (test_caching_check extended), BACKLOG.md (L18 done, L21
added), JOURNAL.md (this entry).

**Verification:** the extended test feeds a list-valued cache-control and
asserts a str cache_control and no "[" in the note; red before the fix, green
after. Full scanner suite green at 282 (assertions joined an existing test, so
no count change and README stays in sync).

**Replenishment (open fell to two):** swept the last unchecked class,
thread-safety in the fan-out scanners, and found it clean - all three use
pool.map over a pure per-item worker, every .append() is in a serial
pre-fan-out builder, and the only thread-shared state (common.http_fetch) is
locked. That makes five classes audited clean (substring-on-structured-data
closed, header-as-list, int/float parsing, mutable defaults, concurrency) and
three invariants CI-enforced. The Phase L improvement pass has converged; filed
L21 to record the enforced invariants and audited classes in PLAN.md so future
work does not re-audit them. No new High/Medium.

**Learnings:** after enough sweeps come back clean, the honest signal is
convergence, not "keep hunting". The remaining backlog (L19 contract test, L20
output sweep, L21 documentation) is deliberate hardening and record-keeping, not
bug-fixing. Recording that state is itself useful so the next run starts from
"what is guarded" rather than re-deriving it.

**Next:** L19 - a contract-level test feeding every host tool duplicated headers
to lock in the header-as-list never-raise guarantee suite-wide.

---

## 2026-07-04 - JOURNAL rotation

Moved the 6 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.

---

## 2026-07-04 - L19: contract-level header-as-list test (run budget reached)

**Task:** L19 (Low), and the final iteration of this second /jeffy run
(iteration 10 of 10).

**What I did:** added TestToolContract.test_no_tool_raises_on_duplicated_headers,
which stubs http_fetch to return a response whose headers (HSTS, CSP, Server,
Set-Cookie, Cache-Control, etc.) are all folded into lists, then runs every
registered tool (host and page) and asserts none raises and each stays
contract-conformant. This locks in the L1/L4/L18 header-as-list never-raise
guarantee registry-wide, so a future tool reading a header unsafely is caught,
not just the ones with direct tests.

**Files changed:** test_review_tools.py (new contract test), README.md (counts
to 283/314), BACKLOG.md (L19 done, L22 added), JOURNAL.md (this entry).

**Verification:** the test passes (every tool tolerates duplicated headers);
scanner suite 282 -> 283, green; the count guard flagged the drift and README
resynced to 283/314 (exit 0).

**Final partial audit (ReDoS):** swept the scanner regexes for
catastrophic-backtracking risk - all use negated char classes, lazy-with-anchor,
or simple whitespace/digit quantifiers, no (X+)+/(X*)* nesting, and input is
bounded by MAX_BODY_BYTES. Clean. That is the seventh class audited clean this
run. Filed L22 (a --fix mode for the README count guard, a DX task felt
firsthand: every added test forced a manual README edit). No new High/Medium.

**Run summary (second run, iterations 1-10):** L10 DRY'd the scan() wrapper into
common.finalize; L13 DRY'd the tally into common.summarize; L11/L14/L16/L17 built
a self-verifying web (README count guard, registry-count guard, a test for that
guard, and a pure-stdlib-charter guard) so documented facts and design
invariants fail CI on drift; L12/L15 closed the substring-on-structured-data
family (with L1/L4/L5 from the first run); L18 and L19 closed the header-as-list
class and locked it in registry-wide. Scanner suite 273 -> 283 (a regression
test per change), builder 31, both green throughout. Seven defect classes
audited clean (substring-parsing, header-as-list, int/float, mutable-defaults,
concurrency, builder-access, ReDoS). Zero open High or Medium at run end; three
Low tasks queued for a next run (L20 output-repr sweep, L21 record invariants in
PLAN, L22 README --fix).

**Learnings:** this run had almost no bug-fixing - the substantive defects were
the first run's. Its value was converting "true by discipline" into "enforced by
CI" and closing whole defect classes rather than instances. The honest signal
after seven clean sweeps is convergence; the remaining backlog is deliberate
polish, recorded as such so the next run does not re-audit closed ground.

**Next (budget reached this turn):** L20, L21, L22 - all Low. Zero open
High/Medium; the Phase L improvement pass has converged.
