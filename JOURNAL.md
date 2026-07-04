# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-04 - L1: duplicate-header crash in http-security checks

**Task:** L1 (High), the top Phase L item. A response that sends the same
security header twice (origin plus CDN, a common real-world misconfiguration)
is folded into a list by common._headers_to_dict, but four checks called string
methods on the value and raised AttributeError out of scan(), which both breaks
the never-raise contract and, through _safe_scan, silently drops the entire
security-header scorecard - exactly when the site is misconfigured.

**What I did:** added common.header_value(headers, name, default) that returns
the last value when a header is folded into a list (identical duplicates, the
overwhelming majority of real double-sends, collapse to the same string either
way) and the plain value otherwise. Routed check_hsts, check_simple_header,
check_referrer_policy, and check_clickjacking through it. check_csp and
_parse_cookies already tolerated lists, so they were left as is. check_disclosure
has the same root cause but a different symptom (a silent false negative, not a
crash) and is its own task L4, kept separate per the no-batch rule.

**Files changed:** common.py (new header_value helper), scan_http_security.py
(four checks read through it), test_review_tools.py (two tests), BACKLOG.md (L1
marked done), JOURNAL.md (this entry).

**Verification:** wrote the tests first and confirmed both reproduced
AttributeError: 'list' object has no attribute 'split' before the fix.
test_duplicate_headers exercises each of the four checks with list-valued
headers (identical duplicates keep their verdict; a differing referrer-policy
resolves last-wins to warn); test_scan_folded_headers_no_raise drives scan()
end to end with a stubbed http_fetch returning five folded headers and asserts
every check returns a valid verdict. Both pass after the fix. Full scanner
suite 266 -> 268, all green.

**Learnings:** the parser modelled HTTP reality (headers can repeat) but four of
its six consumers were written for the common single-value case; the tell was
that check_csp and _parse_cookies already handled lists. One shared accessor is
the right seam, not six per-check guards.

**Next:** L2 - make scan_tls cert-date parsing locale-independent so a
non-English LC_TIME machine does not crash every TLS scan.

---

## 2026-07-04 - L2: locale-independent TLS cert-date parsing

**Task:** L2 (Medium), the top open Phase L item. scan_tls._parse_not_after
parsed the certificate notAfter with time.strptime and a %b directive, which
reads month names in the process LC_TIME locale. OpenSSL always emits English
month names ("Aug"), so on any non-English-locale machine the parse raised
ValueError, which escaped scan() (the caller is unguarded) and, via _safe_scan,
dropped the entire TLS category from the scorecard on every run.

**What I did:** replaced the strptime call with an explicit _MONTHS map and a
tokenized parse (year, month, day, h/m/s from not_after.split()), feeding a
9-tuple to calendar.timegm exactly as before. split() with no argument also
collapses the double space OpenSSL uses to pad a single-digit day, so both
'Aug 29 ...' and 'Aug  9 ...' parse. No locale call remains in the path.

**Files changed:** scan_tls.py (_MONTHS map + rewritten _parse_not_after),
test_review_tools.py (test_parse_not_after_locale_independent), BACKLOG.md (L2
done), JOURNAL.md (this entry).

**Verification:** first reproduced the crash on this machine by forcing
French_France.1252 and calling the old parser (ValueError: time data does not
match format). The new test asserts the epoch for 'Aug 29 21:41:26 2026 GMT'
against an independent calendar.timegm value, checks the space-padded
single-digit day, and re-parses under a forced non-English LC_TIME when one is
installed (restored in finally; skipped cleanly otherwise). Red before the fix,
green after. Full scanner suite 268 -> 269, all green.

**Learnings:** strptime's %b/%a/%p directives are silent locale traps for
machine-format timestamps that are always English (OpenSSL, HTTP dates, many
log formats). An explicit map is both faster and correct; the project's
Windows environment with non-English locales is exactly where this bit.

**Next:** L3 - guard parse_rdap_domain against a non-dict RDAP body so a stray
null/array/string response does not raise out of scan_dns_email.scan().

---

## 2026-07-04 - JOURNAL rotation

Moved the 2 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.

---

## 2026-07-04 - L3: guard parse_rdap_domain against a non-dict RDAP body

**Task:** L3 (Low). common.parse_rdap_domain assumed its argument was a dict
and called data.get; the caller rdap_domain runs it outside the try/except, so
a third-party RDAP server returning valid JSON that is not an object (a stray
null, array, or string) raised AttributeError through check_domain_registration
into scan_dns_email.scan(), breaking the never-raise contract.

**What I did:** parse_rdap_domain now returns the ok=False degraded shape
(expiration/registration None, an explanatory error) when data is not a dict.
I also added an isinstance(e, dict) guard inside the events comprehension so a
non-object element in the events array is skipped rather than crashing the same
way one level deeper.

**Files changed:** common.py (two guards in parse_rdap_domain),
test_review_tools.py (test_parse_rdap_non_dict_body_degrades), BACKLOG.md (L3
done), JOURNAL.md (this entry).

**Verification:** the new test reproduced the AttributeError before the fix
(None body) and now asserts None/[]/"x"/3 all degrade to ok=False and a mixed
events array still reads the valid event. Full scanner suite 269 -> 270, green.

**Learnings:** the guarded try in rdap_domain covered only the network call, not
the parse that follows it; a pure parser that reads external JSON should
validate the shape it was handed rather than trust the caller to. Making the
pure function robust is better than widening the caller's try, since the parser
is also called directly in tests.

**Next:** L4 - normalize a duplicated Server/X-Powered-By header in
check_disclosure so version detection is not a silent false negative (same
list-folding root cause as L1, different symptom).

---

## 2026-07-04 - L4: normalize duplicated Server header in check_disclosure

**Task:** L4 (Low). check_disclosure read each banner with headers.get, so when
Server or X-Powered-By arrived duplicated (folded into a list by
_headers_to_dict), the version test any(ch.isdigit() for ch in val) iterated
whole header strings instead of characters. "nginx/1.25.3".isdigit() is False,
so a version banner was silently graded info (no version) instead of warn - a
false negative rather than a crash.

**What I did:** routed the banner read through common.header_value (the helper
added in L1), so a folded list collapses to a single string before the isdigit
scan and the stored banner value is that string. One-line change; the same L1
seam covers the fifth consumer of a security header.

**Files changed:** scan_http_security.py (check_disclosure banner read),
test_review_tools.py (test_disclosure extended), BACKLOG.md (L4 done),
JOURNAL.md (this entry).

**Verification:** extended test_disclosure asserts a duplicated
["nginx/1.25.3","nginx/1.25.3"] Server yields warn and a normalized string
value; it returned info before the fix. Full scanner suite green at 270 (the
assertions joined an existing test, so the count is unchanged).

**Learnings:** L1 and L4 were the same defect (a header consumer assuming a
string) with different symptoms - a crash for the split/lower callers, a quiet
wrong answer for the isdigit caller. Fixing them behind one shared accessor
means the sixth-and-later consumers cannot reintroduce either symptom.

**Next:** L5 - anchor the SPF -all check to the trailing all-mechanism token so
"include:my-all.com ~all" is not misreported as a hard fail.

---

## 2026-07-04 - L5: SPF all-mechanism matched as a token, not a substring

**Task:** L5 (Low). check_spf graded the SPF qualifier with substring tests
(if "-all" in low ...). A record like "v=spf1 include:my-all.com ~all" contains
the substring "-all" inside the include domain, so it was reported as a -all
hard fail when the actual policy is ~all soft fail. Wrong report, correct-ish
verdict (both -all and ~all grade pass), but the note misinforms the reader.

**What I did:** the all mechanism is a standalone space-separated term (normally
the last), so check_spf now tokenizes the record and selects the token that is
exactly one of -all/~all/?all/+all/all. A bare "all" (implicit +all) joins the
permissive-warn branch. include:my-all.com and redirect= modifiers no longer
match because they are not whole all-tokens.

**Files changed:** scan_dns_email.py (check_spf token match),
test_review_tools.py (test_spf_all_mechanism_is_a_token_not_a_substring),
BACKLOG.md (L5 done), JOURNAL.md (this entry).

**Verification:** the new test asserts the my-all.com record yields the ~all
soft-fail note (not -all), a genuine -all record still reads hard fail, ?all
grades permissive warn, and a record with no all mechanism warns; it reported
the false hard fail before the fix. Full scanner suite 270 -> 271, green. This
was the first direct unit test of check_spf (only an integration stub existed).

**Learnings:** substring tests on structured records (SPF terms, CSP directives,
header tokens) are a recurring trap in this suite; anchoring to the record's
own token boundaries is the correct read. Same family as the CSP directive
parse that already tokenizes.

**Next:** L6 - close the socket on a mid-body read error in common.http_fetch so
a timeout partway through the body does not leak the connection.

---

## 2026-07-04 - L6: close the socket on a mid-body read error in http_fetch

**Task:** L6 (Low). In common.http_fetch the resp.read(MAX_BODY_BYTES) that
pulls the body was outside any try, and the only resp.close() sat after it. A
read that raised partway through the body (a socket timeout, a reset) jumped
straight to the outer except that builds the error dict, skipping the close and
leaking the connection until garbage collection.

**What I did:** wrapped the body-read block in try/finally so resp.close()
(guarded) runs on every path - clean read, read error, or a decode/decompress
error - while the outer except still returns the error dict. The redirect path
already closed and continued, so it was unaffected.

**Files changed:** common.py (try/finally around the body read),
test_review_tools.py (test_mid_body_read_error_closes_socket in TestFetchCache),
BACKLOG.md (L6 done), JOURNAL.md (this entry).

**Verification:** the new test installs a fake opener whose response raises
TimeoutError on read and records close(); before the fix close was never
called (assertion red), after it the socket is closed and http_fetch returns
ok=False with TimeoutError in the error string (no raise). Full scanner suite
271 -> 272, green.

**Learnings:** resource cleanup that lives on the success path only is invisible
until the error path is exercised; a try/finally around the read is the right
shape, matching the guarded close the redirect path already had. The never-raise
contract was already honored; this closes the leak behind it.

**Next:** L7 - update the stale test counts in README (263/242 -> the measured
current totals) so the documentation matches the suites.

---

## 2026-07-04 - L7: refresh the stale README test counts

**Task:** L7 (Low). README cited 263 total / 242 scanner / 21 builder in five
places (a shields badge, the Tests section summary, both suite command
comments, and the file-tree annotation). The suites had grown, and Phase L
added six scanner tests on top, so the documentation understated coverage.

**What I did:** measured both suites fresh (scanner 272, builder 31, total 303)
and updated all five references to those numbers.

**Files changed:** README.md (five test-count references), BACKLOG.md (L7 done),
JOURNAL.md (this entry). No code touched.

**Verification:** grep confirms no 263 or "242 tests" test-count string remains
in README, and 303/272/31 are present at all five sites. The numbers match the
"Ran N tests" line from each suite run this iteration.

**Learnings:** hand-maintained counts in docs drift the moment a test is added;
they were stale before Phase L even began. A follow-up worth considering (not
this task) is deriving the badge from CI so it cannot go stale, but that needs
a CI step and is out of scope here.

**Next:** L8 - add a requirements.txt pinning python-docx (the builder's one
dependency) and reference it from README and ci.yml.

---

## 2026-07-04 - L8: requirements.txt for the builder; iteration-9 partial audit

**Task:** L8 (Low) plus the mandated partial-audit replenishment (completing L8
left only L9 and L10 open, fewer than three).

**L8:** the scanners are pure stdlib, but the report builder and its tests need
python-docx, which only ci.yml installed ad hoc. Added requirements.txt at the
repo root (python-docx>=1.1,<2, commented that the scanner suite needs nothing);
ci.yml now installs via pip install -r ../../../requirements.txt from the
builder working-directory; the README Install section uses
pip install -r requirements.txt.

**Partial audit (replenishment):** swept for the L5-family
substring-on-structured-data trap, silent/bare excepts, TODO markers, and
doc-count accuracy. Result: no new High or Medium. No TODO/FIXME/bare-except;
the except Exception: pass hits are the guarded socket close from L6; the
README "14 registered scanners" claim matches the registry (5 host + 9 page).
Two genuine Low items added: L11 (CI does not guard the README counts against
drift - the exact gap that let L7 rot) and L12 (DKIM/DMARC presence checks
still substring-match tags; very low real risk, so filed as hardening not a
bug). Backlog now has four open (L9-L12).

**Files changed:** requirements.txt (new), .github/workflows/ci.yml, README.md
(Install section), BACKLOG.md (L8 done, L11/L12 added), JOURNAL.md (this entry).

**Verification:** verified the CI relative path resolves (ls
../../../requirements.txt), the dependency is satisfiable (pip --dry-run: 1.2.0
meets the range), and both suites are green (272 scanner + 31 builder).

**Learnings:** the substring-on-structured-data pattern that produced L1/L4/L5
did not recur in any high-risk field; the remaining instances are on names that
live at fixed DNS locations, so they are hardening, not defects. Honest audit
result: the project is at zero open High/Medium, only Low polish remains.

**Next:** L9 - remove the dead VOID_TAGS constant in htmlmeta.py.

---

## 2026-07-04 - L9: remove the dead VOID_TAGS constant (iteration budget reached)

**Task:** L9 (Low), and the last iteration of this /jeffy run (iteration 10 of
10).

**What I did:** htmlmeta.py defined VOID_TAGS, a set never referenced by the
extractor or anywhere else in the suite. Removed the single line.

**Files changed:** htmlmeta.py (VOID_TAGS removed), BACKLOG.md (L9 done),
JOURNAL.md (this entry).

**Verification:** grep VOID_TAGS across tools/ returns no match; scanner suite
green at 272.

**Run summary (Phase L, iterations 1-10):** iteration 1 audited the project and
seeded Phase L worst-first. Then L1 (High: duplicate-header crash) and L2
(Medium: locale-dependent TLS date parse) were fixed, taking the project to zero
open High/Medium; then the Low run L3-L9 (RDAP non-dict guard, duplicated Server
banner, SPF token match, http_fetch socket leak, README counts, requirements.txt,
dead constant). Scanner suite 266 -> 272 with a regression test per code fix;
builder suite unchanged at 31. A partial re-audit at iteration 9 found no new
High/Medium and added two Low items (L11 CI count guard, L12 DKIM/DMARC tag
matching).

**Learnings:** the dominant defect family this run was "a consumer assuming a
simpler shape than the data can take" - a header treated as str not list
(L1/L4), an SPF record as a blob not tokens (L5), an RDAP body as always a dict
(L3), a cert date as always English-locale (L2). One shared accessor
(common.header_value) collapsed the header cases.

**Next (for the next run; budget reached this turn):** L10 (DRY the scan()
wrapper via common.finalize, M-sized), L11 (CI guard for README counts), L12
(DKIM/DMARC tag-boundary matching). All Low. Zero open High or Medium.

---

## 2026-07-04 - JOURNAL rotation

Moved the 4 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.

---

## 2026-07-04 - JOURNAL rotation

Moved the 5 oldest working entries to JOURNAL-archive.md to keep
this file under the 500-line threshold; the last 10 entries remain here.
The archive is append-only history and was not rewritten.
