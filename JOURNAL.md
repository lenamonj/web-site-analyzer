# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-04 - JOURNAL rotation

Moved the 4 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.

---

## 2026-07-04 - Phase O: third full-audit convergence pass (NOT converged)

**Task:** BACKLOG empty after N1-N8, so the convergence gate fired. Ran the full
pass: a deterministic battery (compile, dangerous-pattern/TODO/silent-except
greps, all three suites, count guard, charter, and a re-verification that the
N1/N3/N6/N7/N8 fixes hold - all PASS) and four independent auditors across every
dimension. Verified each candidate finding by reproduction before filing.

**Per-dimension scores (fresh evidence):**
- Correctness: HIGH - O1, check_cookies matches Secure/HttpOnly by substring,
  fabricating a security pass on a __Secure- named cookie with no Secure attr.
- Performance: MEDIUM - O4, the fetch cache is torn down between scan and
  re-scan, so a browser run re-fetches the whole page set.
- Testing: MEDIUM - O3, the CdpSession dispatch layer of the browser tier is
  entirely untested (offline-testable with a stub conn).
- Documentation: MEDIUM - O2, README Install says "one package" but
  requirements.txt pins two and matplotlib is a real runtime dep; O6/O7 Low.
- Security (tool's own): NONE - subprocess injection-safe, no secret leak,
  path-safe, passive charter intact (O1 is a correctness bug in a security check).
- Error handling: NONE - the failure-path and non-dict-JSON classes stay closed.
- Architecture: LOW - the cache-lifetime ownership split (folded into O4).
- Code quality: LOW - O5 async/defer substring, O7 stale DKIM comment.
- Observability / Dependency hygiene / DX: NONE.

Overall: NOT CONVERGED - one High (O1), three Medium (O2, O3, O4).

**Findings filed (Phase O), each reproduced:** O1 (High) cookie Secure/HttpOnly
substring -> fabricated pass; O2 (Medium) README Install undercounts deps; O3
(Medium) CdpSession untested; O4 (Medium) fetch-cache double-fetch; O5-O7 (Low)
async/defer substring, "two suites" narrative, stale DKIM comment. Declined: the
decompression-bomb path (not realistic for authorized passive scanning; download
already capped by MAX_BODY_BYTES).

**Learnings:** the substring-on-structured-data class (L1/L4/L5/L12/L15) was
declared closed for DNS records and CSP, but two more instances survived in
cookies and in the async/defer script check - the same lesson as the ReDoS (N6)
and non-dict-JSON (N8) classes: a class is only closed for the sites the sweep
actually walked, and the earlier substring sweep never enumerated the cookie or
script-attribute readers. The durable fix is to sweep the class by grep
(`in low`, `in val`, substring membership on a header/cookie/attribute value)
across every scanner, not just the ones a bug was first found in.

**Run summary (second /jeffy run, iterations 1-7):** cleared the Phase N Low
backlog (N3-N5), then two replenishment sweeps found and fixed a High-severity
LOC_RE ReDoS (N6) and closed the non-dict-JSON class across every persisted-file
reader (N7, N8), each followed by a whole-class sweep so the class cannot recur.
The closing convergence audit surfaced a fresh High (O1) and three Medium, so the
Definition of done is not met and the 7-iteration budget is now reached. Scanner
suite 292 -> 298, builder 32, report-charts 8, all green throughout.

**Convergence status:** NOT converged. One High (O1) and three Medium (O2-O4) are
open and unfixed; the budget is spent. The next run should execute O1 first (the
fabricated-security-pass), then O2-O4, then sweep the substring-membership class
across all scanners by grep (the O1/O5 root), and only then re-run the full
convergence audit. No promise: a High and three Medium are open, so the
Definition of done is provably false right now.

---

## 2026-07-04 - O1: match cookie Secure/HttpOnly by token, not substring

**Task:** O1 (High). _parse_cookies detected Secure/HttpOnly with `"secure" in
low` / `"httponly" in low` over the whole Set-Cookie string, so a cookie named
__Secure-sid (the common RFC 6265bis prefix) or a value containing the flag word,
with NO Secure attribute, was credited the flag and check_cookies reported a
fabricated pass - hiding the exact gap the check exists to catch.

**What I did:** _parse_cookies now splits the cookie on ";", drops the name=value
pair (split(";")[0]), strips the remaining attribute tokens, and matches
secure/http_only by exact token membership; same_site reads from the same token
list. This closes the substring-on-structured-data class for cookies (same as
L1/L4/L5/L12/L15 did for SPF/DKIM/DMARC/BIMI/CSP).

**Files changed:** scan_http_security.py (_parse_cookies), test_review_tools.py
(test_cookie_flags_match_tokens_not_substrings), README.md (counts 298 -> 299 via
--fix), BACKLOG.md (O1 done), JOURNAL.md (this entry).

**Verification:** __Secure-sid=abc; HttpOnly; SameSite=Lax now parses
secure=False and check_cookies warns (was pass); a pref=httponly-secure-theme
value sets neither flag; a genuine Secure; HttpOnly cookie still passes; the
folded-list case still returns both cookies. Scanner 298 -> 299, builder 32, both
green; README resynced to 299/331, guard exit 0.

**Learnings:** the substring class the earlier sweep declared closed lived on in
two readers it never enumerated (cookies here, async/defer scripts in O5). The
right closing move, after O5, is a grep sweep for substring membership on a
header/cookie/attribute value across every scanner, not a per-instance fix.

**Next:** O2 (README Install dep count), O3 (CdpSession tests), O4 (fetch-cache
double-fetch) - all Medium - then O5-O7 (Low). The last High is closed; three
Medium remain before a fresh convergence pass could pass. No promise.

---

## 2026-07-04 - O2: name both builder dependencies in the README Install section

**Task:** O2 (Medium). README Install said "one package (python-docx)" but
requirements.txt pins two, and matplotlib is a real runtime dependency for
trend-chart reports; a reader trusting the prose over the pip command would
under-install.

**What I did:** the Install line now reads "two packages (python-docx, plus
matplotlib for the quarterly-trend charts), pinned in requirements.txt".

**Files changed:** README.md (Install line), BACKLOG.md (O2 done), JOURNAL.md
(this entry). Docs only.

**Verification:** grep confirms both packages named; the README count guard stays
in sync (299/32/331, exit 0) since the Install prose is not a guarded needle.

**Learnings:** the M3 fix declared matplotlib in requirements.txt and the file
tree but missed the Install prose that names the dependency count - a doc fix is
only complete when every place that states the fact is updated, which is exactly
what the count guard automates for the test/registry numbers but not for prose.

**Next:** O3 (CdpSession offline tests) then O4 (fetch-cache double-fetch), both
Medium; then O5-O7 (Low). No promise.

---

## 2026-07-04 - O3: offline tests for the CDP dispatch layer

**Task:** O3 (Medium). capture_rendered.CdpSession (cmd, wait_event, drop_events,
evaluate) - request/response id correlation, JSON-RPC error extraction, event
buffering, load-event waiting, Runtime.evaluate exception handling - had no
coverage; TestCaptureRendered drives capture_pages through a FakeSession that
replaces CdpSession wholesale, so a regression in the dispatch logic passed CI
(which cannot launch a browser) and only surfaced on a live capture.

**What I did:** added TestCdpSession, which drives CdpSession directly through a
FakeConn stub (records send_text, yields canned JSON from read_message; no socket
or browser). Five tests cover cmd id-matching plus event buffering, cmd's
CaptureError on a JSON-RPC error, wait_event returning None on a failed read
(best-effort load wait), evaluate returning the result value, and evaluate
raising CaptureError on a page exceptionDetails.

**Files changed:** test_review_tools.py (TestCdpSession, 5 tests), README.md
(counts 299 -> 304 via --fix), BACKLOG.md (O3 done), JOURNAL.md (this entry).

**Verification:** the five tests pass; each exercises a distinct dispatch path
that was previously dark. Scanner 299 -> 304, builder 32, both green; README
resynced to 304/336, guard exit 0.

**Learnings:** the browser tier looked untestable ("needs a real browser"), but
the id-correlation and error/exception logic sits above the socket and is fully
exercisable with a stub connection - the untestable part is only the socket
handshake and process spawn. Injecting the connection, not just the session, is
what opened the dispatch layer to offline tests.

**Next:** O4 (fetch-cache double-fetch, Medium) then O5-O7 (Low). Two of three
Phase O Medium now closed. No promise.

---

## 2026-07-04 - JOURNAL rotation

Moved the 5 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.

---

## 2026-07-04 - O4: reference-count the fetch cache so the re-scan reuses it

**Task:** O4 (Medium). enable_fetch_cache/disable_fetch_cache were not
reference-counted, so scan_site.run's `finally: disable_fetch_cache()` nulled the
pipeline's shared cache after the first scan, and the post-capture re-scan (always
run when a browser is present) re-fetched the whole page set - hundreds of
duplicate requests per browser-enabled run and a politeness regression.

**What I did:** added a _FETCH_CACHE_DEPTH counter (mutated under the existing
lock). enable increments and creates the cache only when it was None; disable
decrements (floored at 0) and clears the cache only at depth 0. So run_review's
enable holds depth at 1 across scan_site.run's enable/disable (2 -> 1), the cache
and its warmup survive, the re-scan reuses it, and the pipeline's outer disable
(1 -> 0) clears it.

**Files changed:** common.py (_FETCH_CACHE_DEPTH, enable/disable ref-count),
test_review_tools.py (test_fetch_cache_is_reference_counted_for_the_rescan),
README.md (counts 304 -> 305 via --fix), BACKLOG.md (O4 done), JOURNAL.md (this
entry).

**Verification:** the new test warms the cache under a pipeline-level enable,
enables+disables once more (the inner scan) and asserts the warmup survives, then
the outer disable clears it. scan_site.run standalone still nulls the cache
afterward, so test_scan_site_run_disables_the_cache_afterward passes unchanged,
and TestRunLevelDedup stays green. Scanner 304 -> 305, builder 32, both green;
README resynced to 305/337, guard exit 0.

**Learnings:** the enable docstring already promised the warmup would survive
"a pipeline that enabled it before scan_site.run", but the unconditional disable
broke that promise; reference-counting is the standard way to make nested
enable/disable of a shared resource compose, and it kept the standalone-teardown
invariant (and its test) intact for free.

**Next:** O5 (async/defer substring, the O1-class Low), O6 ("two suites"
narrative), O7 (DKIM comment) - all Low. Every Phase O High and Medium is closed;
three Low remain before a fresh convergence pass. No promise.

---

## 2026-07-04 - O5: match async/defer by attribute, not src-path substring

**Task:** O5 (Low). scan_performance._script_resources set
blocking = "async" not in low and "defer" not in low over the whole
tag-attribute string incl. the src value, so a render-blocking
<script src="/js/async-bundle.js"> was miscounted as non-blocking. Same
substring class as O1.

**What I did:** strip quoted attribute values before the check
(bare = re.sub(r'"[^"]*"|\'[^\']*\'', "", attrs.lower())), so a src path can no
longer match. Chose this over a word-boundary regex because it also handles a
".async." path segment, not just the hyphenated cases.

**Files changed:** scan_performance.py (_script_resources), test_review_tools.py
(test_script_blocking_ignores_async_defer_in_src_path), README.md (counts 305 ->
306 via --fix), BACKLOG.md (O5 done), JOURNAL.md (this entry).

**Verification:** async-bundle.js and asyncstore.js (path only) are now blocking
True; a real async or defer attribute stays blocking False; the existing
test_script_blocking_detection still passes. Scanner 305 -> 306, builder 32, both
green; README resynced to 306/338, guard exit 0.

**Replenishment - swept the substring-on-structured-data class across every
scanner to close it:** grepped every `"literal" in value` check. Beyond O1
(cookies) and O5 (scripts), none is a collision bug: HSTS includesubdomains/
preload, referrer-policy unsafe-url, robots noindex, cache-control immutable, and
viewport user-scalable=no all match specific directive strings that do not appear
as a substring of any other token in their value; robots.txt user-agent and
security.txt contact: are free-text presence heuristics; accessibility
landmarks/roles and the orchestrator ctx/checks/trackers checks are list/dict
membership (exact match). The class is closed - O1 and O5 were the only genuine
substring bugs, both where the matched word (secure/httponly, async/defer)
commonly appears inside a cookie name or a src path. No new task.

**Learnings:** the class had exactly two live instances, and both shared a tell:
the substring being matched is a common English word likely to appear in a
name/path/value, unlike a distinctive directive token (includesubdomains). That
is the grep filter for the next audit - flag substring checks whose needle is an
ordinary word, not a rare directive.

**Next:** O6 ("two suites" narrative) then O7 (DKIM comment), both Low doc.
Every Phase O High/Medium is closed. No promise.

---

## 2026-07-04 - O6: correct the "two suites" narrative to three

**Task:** O6 (Low). README's Tests-and-CI section said "Two offline suites" and
"runs both suites", but CI runs three (test_report_charts wired in by N2).

**What I did:** the section now reads "Three offline suites ... the scanner and
builder suites are 338 tests total, and a report-charts suite adds 8 more"; the
code block runs test_report_charts (noting it needs matplotlib); CI is described
as running "all three suites".

**Files changed:** README.md (narrative, code block, CI line), BACKLOG.md (O6
done), JOURNAL.md (this entry). Docs only.

**Verification:** grep confirms the three-suite wording and the report-charts
command; the guarded "338 tests total" needle is intact so the count guard stays
green (exit 0).

**Replenishment (open at one) - checked the O4-adjacent comment for staleness:**
run_review.py:71-73 says the cache's page fetches are "reused by the scan and the
post-capture re-scan (scan_site.run keeps existing entries and this finally clears
them)". Before O4 that was aspirational (the inner disable nulled the cache);
O4's reference-counting now makes it literally true, so the comment is accurate
and needs no change. No new task.

**Learnings:** O2 and O6 were both cases where a fix updated the code and one doc
spot but left a sibling doc claim stale; the count guard catches the numeric ones
automatically, but prose narrative ("one package", "two suites") has no guard and
drifts. A cheap future guard could assert the CI workflow's unittest invocations
match the suites the README lists.

**Next:** O7 (stale DKIM selector-count comment), the last open task, Low. Every
Phase O High/Medium is closed. No promise.

---

## 2026-07-04 - O7: drop the stale DKIM selector count from the comment

**Task:** O7 (Low). The check_dkim fan-out comment said "14 serial DoH round
trips" but DKIM_SELECTORS holds 26; the note text uses len() so only the comment
was wrong.

**What I did:** the comment now reads "one serial DoH round trip per selector
otherwise", dropping the hardcoded number so it cannot drift again.

**Files changed:** scan_dns_email.py (comment), BACKLOG.md (O7 done, O8 filed),
JOURNAL.md (this entry). Comment-only, no behavior change.

**Verification:** grep confirms no "14 serial" remains; scanner suite green at
306, count guard exit 0 (no test or count change).

**Replenishment - swept for other stale hardcoded counts (the O7 class):** the
only count-in-comment hit besides the fixed one is a self-contained
test-fixture comment (test_review_tools.py:659, describing an in-memory README
fixture, not the real project). The README's live collection counts (154
trackers, 20 CMP hosts, 26 DKIM selectors) are all accurate today, so no stale
count remains. But those three README numbers are unguarded, the same class that
produced O2/O6/O7, so I filed O8 (hardening): extend check_readme_counts.py to
derive and enforce them from the live collections. Not a current bug - a
prevention task in the L11/L14 guard-the-invariant pattern.

**Run summary (third /jeffy run, iterations 1-7):** worked the Phase O
convergence findings to completion - O1 (High) closed the cookie Secure/HttpOnly
substring fabrication; O2 named both builder deps; O3 added offline tests for the
CDP dispatch layer; O4 reference-counted the fetch cache so the re-scan reuses it;
O5 fixed the async/defer src-path substring and then a whole-scanner sweep
confirmed cookies and scripts were the only two substring-membership bugs; O6/O7
corrected the three-suite narrative and the DKIM comment. Scanner suite 298 ->
306, builder 32, report-charts 8, all green throughout. The substring-on-
structured-data class is now genuinely closed (verified by sweep), joining the
ReDoS and non-dict-JSON classes.

**Convergence status:** every Phase O High and Medium is fixed and the backlog
holds one Low hardening task (O8). The 7-iteration budget is now reached, and a
fresh full-audit convergence pass has not been re-run since O1-O7 closed, so the
Definition of done is not yet certified. The next run should run the convergence
audit first: if it comes back clean, the DoD is met; otherwise fix what it finds,
then O8. No promise - the required clean full pass has not been executed this run.

---

## 2026-07-04 - JOURNAL rotation

Moved the 5 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.
