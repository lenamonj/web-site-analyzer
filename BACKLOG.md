# BACKLOG.md - Prioritized task list

Statuses: todo, doing, done, blocked. One task per loop iteration. Pick the
highest-priority unblocked `todo`. Keep tasks small enough to finish and verify
in a single run; split anything larger. See PLAN.md for the design each task
serves.

## Phase O - Third convergence-audit findings (2026-07-04)
The third full-audit pass (after N1-N8 closed; four independent auditors, all
suites green at 298 + 32 + 8 beforehand) confirmed every prior fix holds but
found more: the substring-on-structured-data class thought closed (L1/L4/L5) has
two more instances, plus a doc inaccuracy, a test gap, and a cache double-fetch.
One High, three Medium, so convergence is still not met. Each cites file:line and
a reproduced behavior; see JOURNAL.md 2026-07-04 (Phase O audit) for scores.

### Now (High)
- [x] **O1 (done, S)** check_cookies fabricates a "pass" for a cookie missing
  Secure/HttpOnly when the name or value contains the flag substring.
  scan_http_security.py _parse_cookies does `low = c.lower()` then
  `"secure": "secure" in low` and `"http_only": "httponly" in low` - a substring
  over the whole Set-Cookie string, not a `;`-delimited attribute token. A cookie
  named __Secure-sid (the common RFC 6265bis prefix) or secure_customer_sig
  (Shopify) with NO Secure attribute is credited secure=True, so check_cookies
  reports pass "All cookies carry Secure, HttpOnly, and SameSite" and the missing
  Secure flag - the exact gap this check exists to catch - is hidden, raising the
  security band. Reproduced: _parse_cookies("__Secure-sid=abc; HttpOnly;
  SameSite=Lax")[0]["secure"] is True and check_cookies verdict is pass. This is
  the substring-on-structured-data class (L1/L4/L5/L12/L15) missed for cookies;
  same_site is already matched by token (part.startswith("samesite=") over
  low.split(";")). Fix: detect secure/httponly as whole `;`-split tokens, like
  same_site. Accept: a test with __Secure-sid (no Secure attr) plus HttpOnly
  asserts secure is False and check_cookies warns (not pass); a real Secure
  cookie still passes; scanner suite green.
  Done: _parse_cookies now parses the ;-delimited attribute tokens after the
  name=value pair (attrs = [p.strip() for p in c.lower().split(";")[1:]]) and
  matches secure/http_only by exact token membership; same_site reads from the
  same tokens. Verified: __Secure-sid=abc; HttpOnly; SameSite=Lax now parses
  secure=False and check_cookies warns (was a fabricated pass); a value like
  httponly-secure-theme sets neither flag; a real Secure; HttpOnly cookie still
  passes; the folded-list case is preserved. New test
  test_cookie_flags_match_tokens_not_substrings. Scanner 298 -> 299, builder 32,
  both green; README resynced to 299/331 via --fix (guard exit 0). O5 (async/defer
  substring) is the remaining same-class Low.

### Next (Medium)
- [x] **O2 (done, S)** README Install prose contradicts requirements.txt.
  README.md:158 says "for the Word report only, one package (python-docx)", but
  requirements.txt pins two - python-docx and matplotlib - and matplotlib is a
  real runtime dependency (build_exec_report.py:474 calls render_trend_charts for
  any 3+ quarter report, which raises RuntimeError without matplotlib). The M3
  fix added matplotlib to requirements.txt and the file tree but left this Install
  sentence saying "one package". Fix: name both packages (or say "installed via
  requirements.txt"). Accept: the Install section names matplotlib alongside
  python-docx, or points at requirements.txt without a wrong count; grep confirms.
  Done: README Install line now reads "two packages (python-docx, plus matplotlib
  for the quarterly-trend charts), pinned in requirements.txt". Docs only; count
  guard in sync at 299/32/331, exit 0.
- [x] **O3 (done, M)** The CdpSession dispatch layer of the browser tier is
  entirely untested. capture_rendered.py:264-321 (CdpSession.cmd, wait_event,
  drop_events, evaluate) is the real logic driving every automated rendered
  capture - request/response id correlation with a timeout deadline, JSON-RPC
  error extraction, event buffering, load-event waiting, Runtime.evaluate
  exception-to-CaptureError - and coverage confirms these lines never run
  (TestCaptureRendered drives capture_pages through a FakeSession that replaces
  CdpSession wholesale). It is offline-testable: construct CdpSession(conn) with a
  stub conn whose read_message yields canned JSON. A regression in id-matching,
  error extraction, or timeout handling passes CI (which cannot launch a browser)
  and only surfaces on a live capture. Fix: add offline tests driving CdpSession
  with a stub connection over the cmd/wait_event/evaluate paths. Accept: new tests
  execute CdpSession.cmd (id match, JSON-RPC error), wait_event, and evaluate
  (result and exception-to-CaptureError) with a stub conn; scanner suite green.
  Done: new TestCdpSession drives CdpSession offline via a FakeConn that records
  send_text and yields canned JSON from read_message (no socket, no browser). Five
  tests: cmd matches the response id and buffers an intervening event; cmd raises
  CaptureError on a JSON-RPC error; wait_event returns None when the read fails
  (best-effort load wait); evaluate returns the result value; evaluate raises
  CaptureError on a page exceptionDetails. Scanner 299 -> 304, builder 32, both
  green; README resynced to 304/336 via --fix (guard exit 0).
- [x] **O4 (done, M)** The per-run fetch cache is destroyed between the scan and
  the post-capture re-scan, so a browser-enabled run re-fetches the whole page
  set. common.enable_fetch_cache/disable_fetch_cache are not reference-counted;
  scan_site.run has `finally: common.disable_fetch_cache()` (scan_site.py:181),
  so the inner run nulls the pipeline's shared cache after the first scan and the
  re-scan (always triggered when a browser is present) starts empty. Reproduced
  offline: cache is a dict during the first scan, None after it, empty on re-scan.
  For a 15-page review this re-issues hundreds of requests to the target every
  run - a real cost and a politeness regression, contradicting run_review.py:71-91's
  comment that the cache is reused across the re-scan. The teardown is
  test-enforced (test_scan_site_run_disables_the_cache_afterward), so the fix is
  to reference-count enable/disable (or let the pipeline own the cache lifetime)
  and update that test. Accept: after run_review enables the cache, the
  post-capture re-scan reuses it (a repeated URL is fetched once across scan plus
  re-scan); scan_site.run standalone still leaves the cache off; both suites green.
  Done: enable_fetch_cache/disable_fetch_cache are now reference-counted via a new
  _FETCH_CACHE_DEPTH (both under the existing lock); enable increments and creates
  the cache once, disable decrements and clears only at depth 0. So run_review's
  enable (depth 1) keeps the cache alive through scan_site.run's enable/disable
  (2 -> 1), and the post-capture re-scan reuses the warm cache; the outer disable
  (1 -> 0) clears it. Verified: the warmup survives the inner disable and clears
  at the outer; scan_site.run standalone still nulls the cache afterward (the
  existing teardown test passes unchanged); TestRunLevelDedup still green. New
  test test_fetch_cache_is_reference_counted_for_the_rescan. Scanner 304 -> 305,
  builder 32, both green; README resynced to 305/337 via --fix (guard exit 0).
  All three Phase O High/Medium (O1, O3, O4) plus the O2 doc are now closed.

### Later (Low)
- [x] **O5 (done, S)** scan_performance._script_resources detects async/defer by
  substring over the whole tag-attribute region, so a render-blocking
  <script src="/js/async-bundle.js"> (no async/defer attribute) is miscounted as
  non-blocking. scan_performance.py:53: `blocking = "async" not in low and
  "defer" not in low` where low is the full attribute string incl. the src value.
  Same substring class as O1; soft signal (render_blocking_scripts warns at >3),
  script paths with these substrings uncommon, hence Low. Fix: match the attribute
  token, e.g. re.search(r"(?<![-\w])(async|defer)(\s|=|>|$)", low). Accept: a test
  with src="/js/async-bundle.js" (no async attr) reports blocking True; a real
  `<script defer src=...>` reports blocking False; scanner suite green.
  Done: _script_resources now strips quoted attribute values
  (re.sub(r'"[^"]*"|\'[^\']*\'', "", attrs.lower())) before the async/defer check,
  so a src path can no longer false-match - more robust than a word-boundary regex
  (which still trips on a ".async." path segment). Verified: async-bundle.js and
  asyncstore.js (path only) are blocking True; real async/defer attributes stay
  blocking False. New test test_script_blocking_ignores_async_defer_in_src_path.
  Scanner 305 -> 306, both green; README resynced to 306/338 via --fix (guard exit
  0).
- [x] **O6 (done, S)** README's "Tests and CI" narrative says "Two offline
  suites" (README.md:228) and "runs both suites" (:239), but CI now runs three
  (test_review_tools, test_exec_report, test_report_charts - the third wired in by
  N2, and the file tree at :267 already notes it). Update the narrative to three
  suites. Accept: the section names the report-charts suite / says three; the
  guarded "330 tests total" count is unchanged; grep confirms.
  Done: the section now reads "Three offline suites ... the scanner and builder
  suites are 338 tests total, and a report-charts suite adds 8 more", the code
  block runs test_report_charts, and CI is described as running "all three
  suites". The guarded "338 tests total" needle is intact; count guard exit 0.
  Docs only.
- [x] **O7 (done, S)** scan_dns_email.py:116-117 comment says "14 serial DoH
  round trips" but DKIM_SELECTORS now holds 26. The note text uses
  len(DKIM_SELECTORS) so there is no functional bug; only the comment is stale.
  Fix: correct the comment (or drop the number). Accept: the comment no longer
  states a wrong selector count; scanner suite green.
  Done: the comment now reads "one serial DoH round trip per selector otherwise"
  - dropped the hardcoded number so it cannot drift again. Comment-only, no
  behavior or count change; scanner suite green at 306, guard exit 0.
- [ ] **O8 (todo, S)** Hardening (not a current bug): the README's collection
  counts - "154 tracker domains", "20 CMP hosts", "26 DKIM selector families" -
  are accurate today but unguarded, the same unguarded-doc-count class that
  produced O2 (one package), O6 (two suites), and O7 (14 selectors). The
  check_readme_counts.py gate already derives and enforces test counts and
  registry counts from the code; extend it to derive these three from the live
  collections (len(scan_privacy.KNOWN_TRACKERS), CMP_HOSTS, and
  scan_dns_email.DKIM_SELECTORS) and add them to the checked needles, so a future
  change to a collection that forgets the README fails CI. Accept: editing any of
  the three README counts to a wrong value fails check_readme_counts.py; the
  correct values pass; a test covers the new comparisons; runs in the same CI
  step.

## Phase N - Second convergence-audit findings (2026-07-04)
The re-run full-audit pass (after M1-M8 closed; four independent auditors plus a
deterministic battery, both suites green at 292 + 32 beforehand) confirmed the
M1-M8 fixes hold and every prior class stays clean, but surfaced two genuine new
findings and a few Low. One High and one Medium, so convergence is still not met.
Every task cites file:line and a reproduced behavior; see JOURNAL.md 2026-07-04
(Phase N audit) for the per-dimension scores.

### Now (High)
- [x] **N1 (done, S)** check_clickjacking fabricates a clickjacking FAIL for a
  site with repeated CSP headers when frame-ancestors is not in the last one.
  scan_http_security.py:92 (check_clickjacking) reads
  `csp = common.header_value(headers, "content-security-policy", "")`, which
  returns only the LAST value when the header is folded to a list (origin plus a
  CDN/WAF both send Content-Security-Policy). But repeated CSP headers are
  combined (every policy is enforced), which the sibling check_csp handles via
  _parse_csp (it joins the list with "; "). So a site whose origin CSP carries
  frame-ancestors 'self' while a CDN appends a second CSP header lacking it is
  graded fail "Clickjacking exposure" though check_csp correctly sees
  frame-ancestors. Reproduced: headers {'content-security-policy':
  ["frame-ancestors 'self'; default-src 'self'", "upgrade-insecure-requests"]}
  yields check_clickjacking fail while check_csp lists frame-ancestors. A
  fabricated graded security fail in the CEO deliverable (the charter's worst
  class) plus a spurious remediation action. This is the header-as-list family
  (L1/L4) one semantic level deeper: header_value's last-value rule is wrong for
  a header that must be combined. Fix: combine repeated CSP headers (join the
  list) before scanning for frame-ancestors, matching check_csp. Accept: a test
  with a folded CSP list where frame-ancestors is in a non-last part asserts
  check_clickjacking is pass (not fail); the single-header pass/fail cases still
  hold; scanner suite green.
  Done: check_clickjacking now reads the raw CSP (which may be a list) and does
  `has_fa = bool(raw_csp) and "frame-ancestors" in _parse_csp(raw_csp)`, reusing
  the same combiner as check_csp (list -> "; "-joined -> directive dict), so
  repeated headers combine and the match is on the directive name, not a
  substring. Verified: the N1 folded case (frame-ancestors in the first of two
  CSP headers) is now pass (was fail); single-header with/without, no-CSP, XFO,
  and folded-without-frame-ancestors all grade correctly; the existing
  test_clickjacking and duplicated-header cases still pass. New test
  test_clickjacking_combines_repeated_csp_headers. Scanner 292 -> 293, builder
  32, both green; README resynced to 293/325 via --fix (guard exit 0). Closes
  the header-as-list family at the never-fabricate level (L1/L4 closed
  never-raise; N1 closes the last-value-is-wrong-for-combined-headers gap).
- [x] **N6 (done, S)** LOC_RE in discover_pages.py:30 is a ReDoS
  (catastrophic backtracking). LOC_RE = `<loc>\s*(.*?)\s*</loc>` with re.S: the
  \s* before and after the lazy .*? overlap it (\s is a subset of ., and re.S
  makes . match whitespace and newlines), so on a sitemap body containing an
  opened <loc> followed by whitespace with no matching </loc> - a truncated,
  malformed, or adversarial sitemap, and _collect_sitemap_urls fetches sitemaps
  from the target - the engine backtracks over every way to split the whitespace
  among the three quantifiers. Measured O(N^3): "<loc>" + N spaces runs n=1000
  0.37s, n=2000 3.1s, n=4000 25s; a body near MAX_BODY_BYTES (3 MB) hangs
  discovery, and thus the whole run, effectively forever. Found by the N4-run
  replenishment sweep (discover_pages was not in L22's scanner-regex ReDoS
  audit). Fix: drop the overlapping \s* and strip in Python -
  LOC_RE = `<loc>(.*?)</loc>` (lazy body bounded by a required literal is linear),
  and strip each findall result at the two call sites (:53, :59). Accept: a test
  asserts LOC_RE.findall on "<loc>" + " "*100000 completes in well under a second
  and that "<loc> https://x/a </loc>" still yields the trimmed URL; scanner suite
  green.
  Done: LOC_RE is now `<loc>(.*?)</loc>` (re.I | re.S) - a lazy body bounded by a
  required literal, which is linear - and a new _extract_locs(body) helper does
  [m.strip() for m in LOC_RE.findall(body)] at both call sites (:53, :59),
  preserving the whitespace and newline trimming the old \s* padding gave.
  Verified: the 100000-space unclosed-<loc> input now runs in ~1.5 ms (was
  minutes); "<loc>  https://x/a  </loc>" and a newline-padded loc still yield the
  trimmed URL. New test test_extract_locs_no_redos_and_trims (asserts < 1s and
  the trims). Scanner 295 -> 296, builder 32, both green; README resynced to
  296/328 via --fix (guard exit 0).

### Next (Medium)
- [x] **N2 (done, S)** CI never runs test_report_charts.py, so the trend-chart
  module's tests are dead in CI. .github/workflows/ci.yml runs only
  test_review_tools (line 24) and test_exec_report (line 29); report_charts.py
  (the quarterly-trend PNG renderer, load-bearing for the report's "Progress this
  quarter" section) has a dedicated test_report_charts.py (8 tests) that CI never
  invokes, so a regression in drawable(), metric_panels(), or the K2
  matplotlib-need guard ships silently. Fix: add a CI step to run
  test_report_charts (or a unittest discover), and add test_report_charts.py to
  the README project tree so the third suite is visible. Accept: ci.yml runs
  test_report_charts; README lists it; both run green locally.
  Done: appended `python -m unittest test_report_charts` to the ci.yml "Report
  builder suite" step (same working-directory and after the pip install of
  requirements.txt, so matplotlib is present). Added report_charts.py and
  test_report_charts.py to the README project tree (they were both missing).
  Verified: test_report_charts runs green (8 tests) alongside test_exec_report
  (32); the count guard stays in sync at 293/32/325 (no counted-suite change, the
  new tree lines carry no conflicting "(N tests)" needle). This closes the last
  Medium; the report-charts safety net is now wired into CI on both OSes and
  Python versions.

### Later (Low)
- [x] **N3 (done, S)** scan_performance reads Content-Length directly, not via
  header_value (same header-as-list class as N1). scan_performance.py:81:
  `length = headers.get("content-length")`; a duplicated Content-Length folds to
  a list, str(list).isdigit() is False, so the asset is dropped from the weight
  floor (under-reports; info, not a fabricated grade). Fix: read via
  common.header_value. Accept: a test with a list-valued content-length measures
  the asset size; scanner suite green.
  Done: _measure now reads length via common.header_value (last value; duplicated
  Content-Length carries identical values per RFC 7230, so last-value is correct
  here). Deliberately left the adjacent cache_control list-valued with a comment:
  repeated Cache-Control combines and _cache_max_age joins it, so last-value
  would drop directives (the N1 lesson - last-value is wrong for combine
  headers). Verified: a folded ["4096","4096"] now measures 4096 (was None);
  single value and absent still 5678/None. New test
  test_measure_reads_folded_content_length. Scanner 293 -> 294, builder 32, both
  green; README resynced to 294/326 via --fix (guard exit 0).
- [x] **N4 (done, S)** common.grade band boundaries (score >= 0.85 / 0.65 / 0.4,
  common.py) are not tested at the exact thresholds; test_grade_bands checks 1.0
  / 0.75 / 0.5 / 0.0, none on a boundary, so a >= -> > regression would silently
  misband every scorecard category. Add boundary tests pinning the band at 0.85,
  0.65, and 0.4. Accept: tests assert the band at each exact threshold; scanner
  suite green.
  Done: test_grade_band_boundaries pins score+band at each exact threshold
  (7 pass + 3 warn = 0.85 Strong; 3 pass + 7 warn = 0.65 Adequate; 2 pass + 3
  fail = 0.4 Weak) plus the value just below each (0.80 Adequate, 0.60 Weak, 0.30
  Poor) for the other side. Test-only, no code change. Proven non-vacuous:
  mutating >= 0.85 to > 0.85 fails the test (restored). Scanner 294 -> 295,
  builder 32, both green; README resynced to 295/327 via --fix (guard exit 0).
- [x] **N5 (done, S)** SKILL.md accessibility check list (SKILL.md:35) omits the
  viewport-zoom (WCAG 1.4.4) check that README:87 lists and scan_accessibility
  implements. Add it so the list is complete. Accept: SKILL.md names the
  viewport-zoom check; no code change.
  Done: SKILL.md line 35 now ends "...empty buttons, viewport zoom (WCAG 1.4.4)",
  matching scan_accessibility._viewport_check and the README. Docs only; scanner
  suite unchanged at 296, guard exit 0.
- [x] **N7 (done, S)** crawler._load_state crashes crawl() on a valid-JSON
  non-dict state file - the same class as M8 (read_history). crawler.py:60-64
  catches OSError/ValueError but returns whatever json.loads produced, so a state
  file corrupted to `42` or `[...]` returns a non-dict, and crawl() line 80
  (`loaded.get("target")`) then raises AttributeError instead of starting fresh.
  Reproduced: _load_state on a file containing "42" returns 42, and
  crawl(..., state_path=<that file>) raises "'int' object has no attribute
  'get'". Low - opt-in --crawl path, internal state file, and only valid-JSON
  wrong-type corruption triggers it (a partial write is invalid JSON, already
  caught) - but _load_state should honor its contract like read_history now does.
  Fix: return the parsed value only when isinstance(data, dict), else None.
  Accept: a test asserts _load_state on a "42" file returns None and that crawl
  with a non-dict state file starts fresh without raising; scanner suite green.
  Done: _load_state now returns data only when isinstance(data, dict), else None,
  with a comment. Verified: int/str/list inputs return None, dict is preserved,
  and crawl with a "42" state file starts fresh (2 pages) without raising. New
  test test_non_dict_state_file_is_ignored_not_a_crash. Scanner 296 -> 297,
  builder 32, both green; README resynced to 297/329 via --fix (guard exit 0).
- [x] **N8 (done, S)** Close the non-dict-JSON-load class: three more twins of
  M8/N7 remain, each reading an internal file the tool writes and calling .get()
  with only a parse-error guard, so a valid-JSON non-dict (external corruption of
  the evidence dir) crashes the scan run with AttributeError instead of
  degrading. Sites: scan_vitals.load_metrics (scan_vitals.py:43 -> :46
  data.get("pages"), metrics.json), scan_site.load_rendered_snapshots
  (scan_site.py:71 -> :75 manifest.get("pages"), manifest.json), and
  scan_site.attach_delta (scan_site.py:418, prev scan JSON passed to diff_issues,
  which does prev.get). Reproduced: diff_issues(42, {...}) raises "'int' object
  has no attribute 'get'". Low (internal files, external-corruption-only
  trigger), found by the N7-run json.loads class sweep. Fix: guard each with
  isinstance(data, dict) so a non-dict falls back to the reader's empty result
  (None / {} / no delta). The CLI-read scan/report JSON (draft_report_data.py:408,
  build_exec_report.py:1057, capture_rendered.py:636) read a user-supplied path
  and may traceback on a non-dict; that is an acceptable bad-argument traceback,
  noted not required. Accept: a test corrupting each of metrics.json,
  manifest.json, and the previous scan JSON to a non-dict asserts the reader
  degrades (None / {} / no delta) without raising; scanner suite green.
  Done: added `if not isinstance(data, dict)` guards after the parse-error catch
  in scan_vitals.load_metrics (-> None), scan_site.load_rendered_snapshots
  (-> {}), and scan_site.attach_delta's scan-JSON fallback (-> no delta), each
  with a comment. The ledger path of attach_delta was already M8-safe. Verified:
  a non-dict metrics.json/manifest.json/prev-scan-JSON each degrades without
  raising (was AttributeError). New combined test
  test_corrupt_non_dict_json_files_degrade_not_crash. The three CLI-read spots
  are left as an acceptable bad-argument traceback, as noted. Scanner 297 -> 298,
  builder 32, both green; README resynced to 298/330 via --fix (guard exit 0).
  The non-dict-JSON-load class is now closed across every internal reader.

## Phase M - Convergence full-audit findings (2026-07-04)
The first full-audit pass for convergence (four independent read-only auditors
across every dimension, both suites green at 285 + 31 beforehand) found a defect
class the eleven prior partial audits never checked: a network-primitive failure
(a failed fetch or a failed DoH lookup) treated as a measured negative, which
fabricates findings in the CEO deliverable. Two High and two Medium. Convergence
is not met. Every task cites file:line and a reproduced behavior; see JOURNAL.md
2026-07-04 (Phase M audit) for the per-dimension scores.

### Now (High)
- [x] **M1 (done, S)** scan_http_security fabricates security findings for an
  unreachable target. scan_http_security.py:237-238: _scan grades every header
  check off `res.get("final_headers", {}) or {}` with no guard on res["ok"]; the
  result even carries a `reachable` flag (:262) it never acts on. On a
  no-response fetch (ok=False, hops=[], final_headers={}) the scan emits five
  fabricated FAILs (hsts, clickjacking, x_content_type_options, referrer_policy,
  permissions_policy), a csp WARN, and information_disclosure: pass "No
  version-revealing banners observed." - a definitive clean claim about data
  never measured - for a Poor 0.21 band that flows straight into the deliverable.
  Reproduced by stubbing http_fetch to the common.py:262 no-response shape. The
  correct pattern is scan_tls.check_caa (info when not ok) and the page scanners
  (bail on ok=False). Fix: when the target is unreachable (not res["ok"] and no
  hops), return the header checks as info/unknown, not fail/pass. Accept: a test
  stubbing http_fetch to the no-response dict asserts no check verdict is fail
  and information_disclosure is info (not pass), and the band is Not measured
  (not Poor); the healthy-target tests still pass; scanner suite green.
  Done: added a measured = res["ok"] guard and a header_check(fn, *args) wrapper
  in _scan that returns info "Target did not respond to the HTTPS request; this
  header could not be measured." for the eight header-derived checks (hsts, csp,
  clickjacking, x_content_type_options, referrer_policy, permissions_policy,
  cookies, information_disclosure) when ok is False; https_redirect and
  security_txt already degraded on their own fetches (:32, :206). Chose res["ok"]
  (not "ok and no hops") because http_fetch returns ok=True for any completed
  response incl. 4xx/5xx, so a real error page still grades and only a genuine
  no-response is gated. When measured, header_check calls the check unchanged, so
  the healthy path is byte-identical. New test
  test_unreachable_target_is_not_measured_not_fabricated asserts no fail verdict,
  information_disclosure and hsts are info, and the band is Not measured.
  Reproduced Poor 0.21 before the fix, Not measured after. Scanner 285 -> 286,
  builder 31, both green; README resynced to 286/317 via check_readme_counts.py
  --fix (guard exit 0).
- [x] **M2 (done, S)** scan_dns_email fabricates SPF/DMARC fails when the DoH
  lookup fails. scan_dns_email.py:60,82: check_spf/check_dmarc do
  `records, _ = _txt_records(domain)`, discarding the res["ok"]/error that
  _txt_records already returns (:56). On a DoH failure (a dns.google timeout or
  rate-limit mid-run) records is [] and both return fail "No SPF/DMARC record..."
  for a Poor email-auth band, though nothing was ever observed. check_dnssec and
  check_mx similarly assert "not signed"/"no mail here" from an unknown result
  (info, lower impact). Reproduced by stubbing doh_query to ok=False. The correct
  pattern is scan_tls.check_caa:91-93 (`if not res["ok"]: return info`). Fix:
  these checks must return info/unknown when res["ok"] is False, distinguishing
  "no record published" from "lookup failed". Accept: a test stubbing doh_query
  to ok=False asserts spf and dmarc are info (not fail) with an honest
  lookup-failed note; the existing real-record parsing tests still pass; scanner
  suite green.
  Done: closed the whole "DoH failure treated as a measured negative" class in
  scan_dns_email. check_spf/check_dmarc now capture res and return info
  "<x> lookup failed (...); presence could not be determined." when not res["ok"]
  (before the "no record" fail); check_mx and check_dnssec do the same (info
  "lookup failed", not "does not receive mail"/"not signed"). check_mx marks
  lookup_ok False on failure, so _scan sets has_mx to None (tri-state), and a new
  shared _mx_gate(has_mx, feature) helper makes MTA-STS/TLS-RPT/BIMI report
  "applicability unknown" instead of the false "domain has no MX records"; the
  has_mx False path keeps its byte-identical "not applicable" note. Two updated
  test stubs (test_spf_all_mechanism, test_dmarc_rua) now return {"ok": True}
  since the checks read res["ok"]. New tests: test_doh_failure_is_unknown_not_
  fabricated (spf/dmarc/mx/dnssec info, honest note, gate unknown) and
  test_full_scan_with_dns_down_is_not_fabricated_poor (offline; band not Poor,
  no fail). Reproduced Poor-with-fabricated-fails before, band Not measured and
  spf/dmarc info after. Scanner 286 -> 288, builder 31, both green; README
  resynced to 288/319 via --fix (guard exit 0).

### Next (Medium)
- [x] **M3 (done, S)** requirements.txt omits matplotlib, a hard dependency of
  the builder's trend-charts feature. report_charts.py imports matplotlib and
  build_exec_report.add_trend_section (build_exec_report.py:474) calls
  render_trend_charts with no fallback, so a report whose trend has three or more
  quarters raises RuntimeError when matplotlib is absent. requirements.txt lists
  only python-docx and its comment claims "whose only third-party dependency is
  python-docx", so a user who installs per the docs and builds a 3+ quarter
  retainer report hits that RuntimeError. Fix: declare matplotlib in
  requirements.txt (pinned) and correct the comment, or make add_trend_section
  degrade gracefully (skip charts with a note) when matplotlib is absent and
  document it as optional. Accept: requirements.txt plus its comment name every
  third-party dependency the builder needs, or the builder renders a report
  without matplotlib and a test proves the graceful skip; builder suite green.
  Done: took the declare option (it matches the deliberate K2 design of failing
  loudly when a needed chart cannot render, rather than silently shipping a
  chart-less report). requirements.txt now pins matplotlib>=3.7,<4 (installed
  3.10.8 satisfies it) and its comment names both deps and their roles. Added
  the builder analog of L17's charter guard:
  TestBuilderDependencies.test_builder_third_party_imports_are_declared
  ast-parses build_exec_report.py and report_charts.py, and asserts every
  third-party import (docx -> python-docx, matplotlib) is declared in
  requirements.txt, so the exact undeclared-dependency drift that made M3 now
  fails CI. Proven non-vacuous: removing matplotlib from requirements.txt fails
  it with "builder imports 'matplotlib' ... does not declare it" (restored).
  Builder 31 -> 32, scanner 288, both green; README resynced to 288/32/320 via
  --fix (guard exit 0).
- [x] **M4 (done, S)** capture_rendered abort/restart safety net is untested.
  capture_rendered.py:577-590: the three-consecutive-failure abort
  (`if consecutive_failures >= 3: ... break`) and the browser-restart-failure
  path (`except (CaptureError, OSError): ... break`) have no coverage - the only
  failure test fails exactly one page, so consecutive_failures never reaches 3
  and the restart always succeeds. A regression to the threshold or the counter
  reset would let a dead browser churn the whole page set (each restart waits up
  to LAUNCH_WAIT_S = 15s) with no test catching it. Fix: add a test that drives
  three consecutive page failures and asserts the run aborts with the "aborting
  the capture run" note, and one where the restart raises and asserts the
  "browser restart failed" abort. Accept: both branches are entered by new tests
  asserting the documented abort; scanner suite green.
  Done: added test_three_consecutive_failures_abort_the_run (all pages fail via
  FakeSession(fail_goto=all); asserts ok False, "aborting the capture run" note,
  exactly 3 failures recorded, the 4th page never tried, nothing captured) and
  test_browser_restart_failure_aborts_the_run (a factory that returns a working
  initial session then raises on the relaunch; asserts ok False, "browser restart
  failed" note, and exactly two factory calls). Both assert states set only
  inside the target branches, and a mutation (>= 3 -> >= 99) fails the abort test
  (restored), confirming non-vacuous coverage. Scanner 288 -> 290, builder 32,
  both green; README resynced to 290/322 via --fix (guard exit 0).

### Later (Low)
- [x] **M5 (done, S)** SKILL.md names the wrong CrUX key variable. SKILL.md:41
  and :56 say field data needs GOOGLE_API_KEY, but scan_crux.py:65 reads
  CRUX_API_KEY first and only falls back to GOOGLE_API_KEY (README lists both,
  preferring CRUX_API_KEY). Update SKILL.md to name CRUX_API_KEY (preferred) and
  GOOGLE_API_KEY. Accept: grep of SKILL.md shows both keys with CRUX_API_KEY
  named as preferred; no code change.
  Done: SKILL.md line 41 now reads "when CRUX_API_KEY, or the fallback
  GOOGLE_API_KEY, is set", matching scan_crux.py:65's precedence. Only one CrUX
  mention exists in SKILL.md (the audit's ":56" reference was off by lines).
  Docs only; scanner suite unchanged at 290, guard exit 0. Noted but not fixed:
  scan_crux.py:8 docstring still says "Needs a GOOGLE_API_KEY" - not false
  (GOOGLE_API_KEY works as fallback), and M5's acceptance is "no code change", so
  the internal docstring is left as a below-threshold item.
- [x] **M6 (done, S)** registrable_domain, a shared domain helper, lives in a
  peer scanner. scan_dns_email.py:42 defines registrable_domain + MULTI_SUFFIXES,
  imported by seven modules (scan_tls, scan_privacy, scan_page_security,
  scan_performance, scan_crawl, discover_pages, crawler). A utility imported by
  seven modules from a sibling scanner is a leaky dependency. Relocate it to
  common.py, keeping scan_dns_email working. Accept: registrable_domain lives in
  common.py, the importers reference it there, and both suites stay green with
  byte-identical scan output on a canned run.
  Done: moved MULTI_SUFFIXES + registrable_domain verbatim into common.py beside
  the host/URL helpers. scan_dns_email now calls common.registrable_domain
  internally; the seven importers each swapped dns.registrable_domain ->
  common.registrable_domain (13 call sites) and dropped the now-dead
  "import scan_dns_email as dns" (all seven used dns only for this helper). The
  test_registrable_domain unit test targets common. Verified: no
  dns.registrable_domain / scan_dns_email.registrable_domain / MULTI_SUFFIXES
  remains outside common.py; all nine touched modules compile; scanner 290,
  builder 32, both green; count guard unchanged (no test added). Helper output
  unchanged incl. multi-suffix (example.com.au) and single-label (localhost)
  edges. Behavior byte-identical (verbatim function, contract tests pass).
- [x] **M7 (done, S)** Replenishment from the M4 iteration partial audit
  (encoding/charset robustness). _decode_body is robust (errors="replace", plus a
  LookupError/TypeError fallback to utf-8), but common._decompress catches only
  (OSError, zlib.error); gzip.decompress on a truncated stream raises EOFError,
  which propagates. When a gzip body exceeds MAX_BODY_BYTES (3 MB compressed) the
  resp.read cap truncates it, so _decompress raises EOFError, http_fetch's outer
  except turns the whole fetch into ok=False "EOFError...", and the page is
  reported as unreachable rather than partially analyzed - unlike a large
  uncompressed page, which gets its first 3 MB analyzed. Reproduced: a
  half-truncated gzip stream makes _decompress propagate EOFError. Low (trigger
  is a >3 MB compressed page, degrades to ok=False with no crash or fabrication),
  but the framing is misleading and the partial content is lost. Fix: decompress
  gzip via zlib.decompressobj(16 + zlib.MAX_WBITS) so a truncated stream yields
  its decompressed prefix (matching the uncompressed-truncation behavior), or at
  minimum catch EOFError. Accept: a test feeds a gzip body truncated mid-stream
  and asserts _decompress returns the decompressed prefix (not a raise, not raw
  compressed bytes); scanner suite green.
  Done: _decompress now uses streaming decompressors for both codecs - gzip via
  zlib.decompressobj(16 + zlib.MAX_WBITS), zlib-deflate via
  zlib.decompressobj(zlib.MAX_WBITS) with the raw-deflate
  (-zlib.MAX_WBITS) fallback preserved - so a truncated stream yields its
  decompressed prefix instead of raising. Removed the now-unused import gzip.
  Verified: a half-truncated gzip (539 of 1078 bytes) yields a 9912-byte prefix
  starting with the real text; complete gzip/deflate bodies and the
  magic-byte auto-detect all round-trip unchanged. New test
  test_truncated_gzip_yields_decoded_prefix. Scanner 290 -> 291, builder 32,
  both green; README resynced to 291/323 via --fix (guard exit 0).
- [x] **M8 (done, S)** Replenishment from the M6 iteration partial audit
  (corrupt-persisted-state handling). capture_rendered._load_or_new is robust
  (bad JSON or wrong shape -> rebuild), but scan_site.read_history admits any
  valid-JSON line, including a non-dict. Its docstring claims "malformed lines
  are skipped", yet a line like `42` or `"x"` (external ledger corruption) is
  kept, and a consumer (write_digest_md line 503 `e.get("bands", {})`,
  trends.quarterly_points) then raises AttributeError on it. Reproduced: a ledger
  with a dict line then `42` returns [dict, 42] and the consumer crashes with
  "'int' object has no attribute 'get'". Low (a partial/interrupted append yields
  invalid JSON, which is already skipped; only valid-JSON-non-dict corruption
  triggers it), but read_history should honor its own contract. Fix: skip lines
  that do not parse to a dict. Accept: a test feeds a jsonl with a dict line and
  a valid-JSON non-dict line and asserts read_history returns only the dict;
  scanner suite green.
  Done: read_history now parses each line, then appends only when
  isinstance(obj, dict); the docstring records that a valid-JSON non-dict line is
  skipped for the same reason. New test
  test_read_history_skips_valid_json_non_dict_lines feeds a dict line, then 42, a
  string, and a list, and asserts only the two dict entries survive and all are
  dicts (before the fix it returned five and a consumer's .get crashed). Scanner
  291 -> 292, builder 32, both green; README resynced to 292/324 via --fix (guard
  exit 0).

### Declined
- common._decompress runs zlib/brotli with no max_length, so a hostile 3 MB
  compressed body could expand to gigabytes (Phase O audit): the threat model is
  passive scanning of authorized sites, not adversarial input, and MAX_BODY_BYTES
  already caps the download; a decompression bomb is not realistic here.
Marginal Low observations from the Phase M audit, judged not worth a task:
- common.py optional `import brotli` sits outside the TestScannerCharter guard
  (which globs scan_*.py only): intentional, guarded, degrades to raw; the charter
  is a scanner invariant, and extending it to common.py would flag a deliberate
  optional enhancement.
- No MAX_BODY_BYTES-style size cap on the RDAP/CrUX/DoH JSON reads: all three hit
  trusted first-party endpoints (IANA, Google), so the risk is theoretical.
- Per-run fetch cache has no eviction: bounded at 512 entries and the crawl path
  is opt-in, so it is not a real cliff.
- CrUX key passed as a URL query param: a valid key never leaks; only a malformed
  key could surface via an InvalidURL repr, which requires an already-broken key.
- scan()/main() boilerplate repeated across the 14 scanners: deliberate
  standalone-CLI-per-module design; a shared helper would couple them.
- draft_report_data.LABEL_TO_CATEGORY duplicates the registry's label->category
  map (Phase N audit): drift degrades one weakness bullet's "Example:" suffix,
  never a crash or wrong number, and the map is tiny; deriving it from the
  registry is a nicety, not a fix.
- scan_site orchestrator hardcodes the "performance" key for the rendered-DOM
  skip (Phase N audit): a documented single exception to the registry-driven
  design; moving it to a scanner flag is churn for one line.

## Phase L - Audit findings (Ralph audit pass 2026-07-04)
Generated by an evidence-based audit of the whole suite (both test suites green
at 266 scanner + 31 builder before the audit). Every task cites a file:line and
carries an acceptance check. Ordered worst severity first. See JOURNAL.md
2026-07-04 for the per-dimension scores.

### Now (High)
- [x] **L1 (done, S)** Duplicate response header crashes the http-security
  checks. common._headers_to_dict folds a repeated header into a list
  (common.py:80-84), but check_hsts (scan_http_security.py:50 val.split),
  check_simple_header (:74 val.lower), check_referrer_policy (:84 val.lower),
  and check_clickjacking (:93 csp.lower) assume a string, so a site sending
  HSTS/CSP twice (origin + CDN, a common misconfig) raises AttributeError out
  of the check. This violates the never-raise contract and, via _safe_scan,
  silently drops the entire security-header scorecard. check_csp and
  _parse_cookies already tolerate lists, so the fix is a shared list-tolerant
  header accessor (e.g. common.header_value returning the last value), used by
  the four checks. Accept: a unit test passing list-valued
  strict-transport-security, referrer-policy, x-content-type-options, and CSP
  headers to each check asserts a normal verdict and no exception; scanner
  suite still green.
  Done: new common.header_value(headers, name, default) returns the last value
  when a header is folded into a list (identical duplicates collapse to the
  same string). check_hsts, check_simple_header, check_referrer_policy, and
  check_clickjacking now read through it. Two tests added
  (test_duplicate_headers at the check level, test_scan_folded_headers_no_raise
  end-to-end via a stubbed http_fetch); both reproduced the AttributeError
  before the fix and pass after. Scanner suite 266 -> 268, green. L4 (the same
  root cause in check_disclosure) stays a separate task per the no-batch rule.

### Next (Medium)
- [x] **L2 (done, S)** TLS certificate date parse is locale-dependent.
  scan_tls._parse_not_after (scan_tls.py:50) uses time.strptime with %b, which
  reads month names in the process LC_TIME locale; OpenSSL always emits English
  ("Aug"), so on a non-English-locale machine every TLS scan raises ValueError
  and _safe_scan drops the whole TLS category. Parse the month with an explicit
  English month map (or email.utils.parsedate_to_datetime), locale-independent.
  Accept: a test that parses 'Aug 29 21:41:26 2026 GMT' returns a numeric epoch
  regardless of locale (assert under a stubbed/forced non-English LC_TIME);
  scanner suite green.
  Done: replaced the strptime call with an explicit _MONTHS map and a tokenized
  parse (split() also collapses OpenSSL's double-space day padding); no locale
  dependence remains. Reproduced the crash first under French_France.1252
  (ValueError), then the new test test_parse_not_after_locale_independent passes
  the core parse plus a re-parse under a forced non-English LC_TIME (skipped
  cleanly when no such locale is installed) and a single-digit-day case. Scanner
  suite 268 -> 269, green.

### Later (Low)
- [x] **L3 (done, S)** parse_rdap_domain raises on a non-dict RDAP body.
  common.py:353 calls parse_rdap_domain(data) outside the guarding try
  (:346-352); a valid-JSON non-object (null, array, string) makes data.get
  raise AttributeError through check_domain_registration -> scan(). Guard with
  an isinstance(data, dict) check returning ok=False. Accept: a test that
  parse_rdap_domain(None), ([]), and ("x") each return ok=False without raising.
  Done: parse_rdap_domain now returns the ok=False degraded shape when data is
  not a dict, and skips non-dict elements inside the events array (the same
  crash one level deeper). Test covers None/[]/"x"/3 and a mixed events array;
  reproduced the AttributeError before the fix. Scanner suite 269 -> 270, green.
- [x] **L4 (done, S)** check_disclosure misreads a duplicated Server header.
  scan_http_security.py:223 (has_version = any(ch.isdigit() for ch in val)):
  when Server/X-Powered-By is a list, the loop iterates whole strings not
  chars, so "nginx/1.25".isdigit() is False and a version banner is missed
  (silent false negative). Normalize the header value first (same root cause as
  L1). Accept: a test with server ["nginx/1.25.3","nginx/1.25.3"] asserts
  verdict warn.
  Done: check_disclosure now reads each banner via common.header_value (the L1
  helper), so a folded list collapses to a string before the isdigit scan and
  the stored banner value is the string. test_disclosure extended with the
  duplicated-Server case (asserts warn and the normalized value); reproduced
  the info false negative before the fix. Scanner suite green at 270.
- [x] **L5 (done, S)** SPF qualifier note over-matches on the -all substring.
  scan_dns_email.py:66 (if "-all" in low): a record like
  "v=spf1 include:my-all.com ~all" contains "-all" and wrongly reports "ends in
  -all (hard fail)" though the policy is soft fail. Anchor the test to the
  trailing all-mechanism token. Accept: a test on that record yields the ~all
  (soft fail) note, not the hard-fail note.
  Done: check_spf now finds the all-mechanism as a whole space-separated token
  (-all/~all/?all/+all/all) instead of a substring scan, so include:my-all.com
  no longer masquerades as -all. New test_spf_all_mechanism_is_a_token_not_a_
  substring covers the my-all.com soft-fail case, a real -all hard fail, ?all
  permissive, and no-all; reproduced the false hard-fail before the fix.
  Scanner suite 270 -> 271, green.
- [x] **L6 (done, S)** Socket left open on a mid-body read error in http_fetch.
  common.py:206 (raw = resp.read(MAX_BODY_BYTES)) is unguarded; if read raises
  (e.g. timeout mid-body) control jumps to the outer except without
  resp.close(), leaking the connection until GC. Wrap the response so resp is
  closed on every path. Accept: a test stubbing resp.read to raise asserts
  resp.close() was called (and http_fetch still returns an error dict, no
  raise).
  Done: the body-read block is now inside a try/finally that closes resp on
  every path (success, read error, or decode error); the outer except still
  builds the error dict. New test_mid_body_read_error_closes_socket uses a fake
  response whose read raises and whose close is tracked; before the fix close
  was never called. Scanner suite 271 -> 272, green.
- [x] **L7 (done, S)** README test counts are stale. README.md:227/231/233/277
  cite 263 total / 242 scanner / 21 builder; the measured suites are 266
  scanner + 31 builder = 297. Update every count to the measured values.
  Accept: the numbers in README match the output of both `python -m unittest`
  runs; grep finds no "263"/"242 tests" test-count references.
  Done: measured fresh (Phase L added scanner tests since the audit) - scanner
  272, builder 31, total 303. Updated all five references (the badge on line 9,
  the summary line, both suite comments, the tree annotation). grep confirms no
  263/242 test-count references remain. Note: any later task that changes a
  suite count must re-update these five spots.
- [x] **L8 (done, S)** No requirements.txt documents the builder's one
  dependency. Scanners are pure stdlib, but build_exec_report.py and
  test_exec_report.py need python-docx, which is only installed ad hoc by
  ci.yml (pip install python-docx). Add a requirements.txt (python-docx pinned
  to a compatible range) and reference it from README and ci.yml. Accept:
  requirements.txt exists, ci.yml installs from it, README's install section
  names it; both suites still green.
  Done: added requirements.txt at the repo root (python-docx>=1.1,<2, with a
  comment that the scanner suite needs nothing). ci.yml now runs
  pip install -r ../../../requirements.txt from the builder working-directory
  (path verified). README Install section installs via
  pip install -r requirements.txt. Dry-run resolves (1.2.0 satisfies the
  range); both suites green (272 + 31).
- [x] **L9 (done, S)** Dead constant. htmlmeta.py:16 defines VOID_TAGS, never
  referenced anywhere. Remove it. Accept: grep VOID_TAGS over tools/ returns
  nothing; scanner suite green.
  Done: removed the VOID_TAGS line. grep over tools/ returns no match; scanner
  suite green at 272.
- [x] **L10 (done, M)** DRY the self-describing wrapper. The identical scan()
  tail (result["category"]=CATEGORY; result["grade"]=common.grade(
  common.verdicts_of(result))) is copy-pasted across 14 scanners, and the same
  pass/warn/fail tally loop across 12. Add a common.finalize(result, CATEGORY)
  helper and route every scanner through it. Accept: the wrapper body appears
  once (in common.py); grep shows no scanner re-implements the category+grade
  stamping inline; both suites green with identical scorecard output on a
  canned run.
  Done: added common.finalize(result, category) (category + grade). All 14
  scanner scan() wrappers now return common.finalize(_scan(...), CATEGORY);
  grep confirms no scanner stamps grade inline. Deliberately scoped OUT the
  tally-loop consolidation: scan_tls uniquely emits no summary, so folding the
  tally into finalize would add a summary key to scan_tls (an observable-output
  change the constraints forbid). The remaining tally duplication is filed as
  L13. Verified: a canned offline scan gives a byte-identical grade/summary to
  the pre-refactor baseline (security, Strong, 0.88); scanner suite 272 -> 273
  (new test_finalize_stamps_category_and_grade), builder 31, both green; diff
  is a clean -3/+1 per file, no line-ending noise.

### Later (Low) - replenishment from the iteration-9 partial audit
Partial re-audit (substring-on-structured-data sweep, silent-except sweep,
TODO sweep, doc-count accuracy) found no new High or Medium: no TODO/FIXME
markers, no bare or silent excepts (the except Exception: pass hits are the
guarded socket close), and the README "14 registered scanners" claim matches
the registry. Two genuine Low items surfaced.
- [x] **L11 (done, S)** CI does not guard the README test counts against drift,
  which is exactly how they went stale (fixed by hand in L7). Add a CI step (or
  a small tools/check_readme_counts.py run in CI) that reads the "Ran N tests"
  from both suites and fails if README's badge/summary/comments disagree.
  Accept: deliberately editing a README count to a wrong value makes the new
  check fail locally; with correct counts it passes; the step runs in ci.yml.
  Done: new tools/check_readme_counts.py counts both suites via unittest
  loaders (no re-run) and asserts README's badge, summary, both suite comments,
  and tree annotation all match; exits non-zero on drift. It immediately caught
  L10's drift (scanner 272 -> 273); updated README to 273/31/304. ci.yml runs
  it as a step after the builder suite (python-docx installed). Verified: passes
  with correct counts (exit 0), a deliberately-wrong count fails (exit 1, README
  restored). Scanner suite green at 273.
- [x] **L12 (done, S)** Defense-in-depth: the DKIM presence probe
  (scan_dns_email.py:106) and the DMARC has_rua check (:92) test for "p=" /
  "rua=" as bare substrings of the whole record rather than parsed tags, the
  last of the L5-family substring-on-structured-data spots. Real-world risk is
  very low (records live at _domainkey/_dmarc names), so this is hardening, not
  a live bug. Match on ";"-split tag boundaries. Accept: a test where "p="
  appears only inside a base64 blob (no DKIM tag) is not detected as DKIM, and
  rua detection keys on the parsed tag; scanner suite green.
  Done: new _is_dkim_record(record) detects a DKIM key by a v=DKIM1/k/p tag at
  ";"-boundaries; check_dkim probes through it. check_dmarc has_rua now checks
  any ";"-split part starts with rua=. Two tests reproduce the substring false
  positives (a google-site-verification value with "p=", a ruf= value
  containing "rua=") and confirm real records still detect. Scanner 273 -> 275,
  green; README resynced to 275/306 (the L11 CI guard flagged the drift).
- [x] **L13 (done, S)** Discovered during L10: the pass/warn/fail tally loop
  (tally = {...}; for c in checks.values(): ...) is duplicated across 13
  scanners' _scan bodies. It was left out of L10 because scan_tls uniquely
  emits no summary, so it could not fold into finalize without changing
  scan_tls output. Add a common.summarize(checks) helper (identical logic:
  count each check's verdict, default missing to info) and replace the inline
  tally in the 13 scanners that set "summary". Do NOT add a summary to scan_tls.
  Accept: common.summarize is the only tally implementation; grep shows no
  scanner builds the {"pass":0,...} tally inline; each scanner's summary output
  is unchanged on a canned run; both suites green.
  Done: added common.summarize(checks) (default-missing-to-info form, the more
  robust of the two inline variants) with a unit test. Replaced the inline
  tally in all 13 scanners via a scripted edit that handled both variant forms
  (12 used c["verdict"], scan_http_security used c.get("verdict","info")),
  asserting one block per file. scan_tls untouched (no summary). grep confirms
  no scanner builds the tally inline; a canned http_security scan gives the
  identical summary {pass 7, warn 0, fail 1, info 2}. Scanner 275 -> 276,
  builder 31, both green; README resynced to 276/307 (L11 guard flagged it).

### Later (Low) - replenishment from the iteration-2 partial audit (2026-07-04)
Open tasks fell to two after L11, so a partial audit ran. It found no new
High/Medium; one genuine same-class doc-guard gap surfaced.
- [x] **L14 (done, S)** README line 17 hard-codes "14 registered scanners, 10
  scorecard categories" - drift-prone facts that L11's check does not cover.
  They are currently accurate (verified against the registry: 14 tools, 10
  distinct categories), but adding a scanner will silently stale them. Extend
  check_readme_counts.py (or a sibling) to read the registry (host_tools +
  page_tools, distinct categories) and assert README line 17 matches. Accept:
  editing the "14"/"10" claim to a wrong value fails the check; correct values
  pass; runs in the same CI step.
  Done: check_readme_counts.py now imports the registry, computes len(host+page
  tools) and distinct categories, and adds "N registered scanners" / "M
  scorecard categories" to the checked needles. Verified: correct README passes
  (14 scanners, 10 categories), rewriting "14 registered scanners" to 99 fails
  naming that needle (README restored). Already runs in the CI step from L11.
  Scanner suite green at 276.
- [x] **L15 (done, S)** Replenishment from the iteration-3 partial audit: one
  more L5-family spot. check_bimi (scan_dns_email.py:202) sets has_logo via
  the bare substring "l=" in rec.lower() rather than a tag-boundary match, so
  "l=" appearing inside another tag's value (e.g. an a= evidence URL) would
  false-positive. Very low real risk (BIMI records are rare and short), pure
  hardening. Match any ";"-split part starting with "l=". Accept: a test where
  "l=" appears only inside another tag's value reports has_logo False, and a
  real l= tag reports True; scanner suite green. (All other dns_email record
  reads - SPF, DMARC p=, MTA-STS mode:, record-type via startswith(v=...) - were
  checked in this audit and already parse at boundaries.)
  Done: has_logo now checks any ";"-split tag starts with "l="; test confirms
  an a=.../l=x.pem value is not read as a logo and a real l= tag is. Scanner
  276 -> 277, green; README resynced to 277/308. This closes the
  substring-on-structured-data family (L1, L4, L5, L12, L15).
- [x] **L16 (done, S)** Replenishment from the iteration-4 partial audit:
  tools/check_readme_counts.py (the L11 CI gate) has zero test coverage, unlike
  the project's other tools/ utilities (crawler.py, triage.py are tested). The
  builder's one broad except was checked and is fine (it surfaces the image
  error into the docx, not a silent swallow). Extract a pure function
  readme_mismatches(text, scanner, builder) -> list of mismatch strings and
  unit-test it: a matching README yields [], a wrong count yields the specific
  mismatch. Accept: a test drives the pure checker over in-memory README strings
  (matching and mismatched); the CLI still works; scanner suite green.
- [x] **L20 (done, S)** Replenishment from the iteration-8 partial audit. This
  audit swept two more classes and found them clean: no mutable default
  arguments anywhere in the suite, and discover_pages core functions are tested
  (discover() itself is covered indirectly by the run_review integration test).
  The project is deep in convergence - no new High/Medium and no substantive
  Low. Remaining genuine item is an output-quality sweep in the same class as
  L18 (which found a raw list repr in one note): grep the human-facing text
  builders that L18 does not touch - scan_site's digest/summary markdown writer
  and build_exec_report's finding/evidence notes - for f-strings that embed a
  raw header/list/dict value, and normalize any found (or record that none
  exist). Accept: every such site either renders a clean string or is confirmed
  to only ever receive a string; a test covers any fix; scanner suite green.
  Done: swept both named writers; no new leak. scan_site's digest writer
  (write_digest_md, issue_line, console main) embeds only scanner-built note
  strings, band names, and integer counts, with pages rendered via ', '.join -
  no raw header/list/dict embed. build_exec_report renders JSON-contract strings
  through python-docx sinks (add_run/set_cell_text require a string, so a list
  would raise, not repr) with the numeric-ish values str()-wrapped; its source,
  draft_report_data, builds every finding/evidence/detail/value as a string, an
  f-string over strings/ints, or a number-formatted value (fmt guarded by
  value is not None). The header-as-list normalization that prevented the one
  L18 leak is already enforced at the scanner boundary (common.header_value;
  http_security CSP/report-only isinstance/join). To make the class
  un-reintroducible registry-wide, added
  TestToolContract.test_no_repr_leak_in_notes_on_duplicated_headers: under the
  L19 folded-header stimulus every registered tool's check notes carry no
  list/dict repr signature (['/{') and every stored value stays scalar. Proven
  non-vacuous - reverting the L18 header_value fix makes scan_performance.
  cache_control fail it ("Cache-Control: ['max-age=3600', 'no-cache']."),
  restoring passes. Scanner 283 -> 284, builder 31, both green; README resynced
  to 284/315 (the L11 guard confirmed sync, exit 0). This closes the
  output-repr class (the L18 family) registry-wide.
- [x] **L18 (done, S)** Replenishment from the iteration-6 partial audit (a
  sweep of header-as-list handling in the non-http_security scanners, the L1
  class). scan_performance was already list-safe in its parsing paths
  (_cache_max_age and _asset_caching_check both join a list before string ops),
  and content-length is guarded by str().isdigit(). The one gap:
  _caching_check (scan_performance.py:154) embeds a duplicated Cache-Control
  header straight into its info note and stored value, so an origin+CDN double
  Cache-Control renders as a Python list repr ("Cache-Control: ['no-cache',
  'no-store']."). Info-only, no crash or misgrade, but unpolished. Normalize via
  common.header_value (the L1 helper). Accept: a test with a list-valued
  cache-control yields a clean string in the note and stored cache_control;
  scanner suite green.
- [x] **L21 (done, S)** Replenishment from the iteration-9 partial audit, which
  swept the last unchecked class - thread-safety in the fan-out scanners - and
  found it clean: scan_links/scan_performance/scan_dns_email all use
  pool.map(pure_worker, items), every .append() is in a serial pre-fan-out
  function, and the only thread-shared state (common.http_fetch) has a lock.
  With five defect classes now audited clean (substring-on-structured-data
  closed, header-as-list, int/float parsing, mutable defaults, concurrency) and
  three invariants CI-enforced (test counts, registry counts, pure-stdlib
  charter), the Phase L improvement pass has converged. Record this in PLAN.md:
  a short "Enforced invariants and audited-clean classes" section so future work
  discovers the guards and does not re-audit closed classes. Accept: PLAN.md has
  the section naming each CI guard (with its test/script) and each audited class
  with its outcome; no code change; suites unaffected.
  Done: added PLAN.md section 38 "Enforced invariants and audited-clean classes
  (Phase L convergence record)" listing five CI-enforced invariants, each with
  its test or script (README test counts -> check_readme_counts.py +
  TestReadmeCountGuard; line-17 registry facts -> same script; pure-stdlib
  charter -> TestScannerCharter; header never-raise ->
  test_no_tool_raises_on_duplicated_headers; note never-repr ->
  test_no_repr_leak_in_notes_on_duplicated_headers), and nine audited-clean
  classes each with its outcome (three CLOSED, six CLEAN, now including the
  division-by-zero sweep from L20's run). Added a Phase L pointer to section 38
  in the section 6 Roadmap so an auditor finds it. Docs only; no code change.
  Verified: count guard exit 0, scanner suite unchanged at 284, both green; a
  closing note records that the section does not itself satisfy the
  Definition of done.
- [x] **L19 (done, S)** Replenishment from the iteration-7 partial audit. This
  audit swept two more classes and found the scanners clean: no unguarded
  int()/float() on external data (all such calls are behind str().isdigit(),
  a regex \d+ group, the _MONTHS map, or the stdlib-guaranteed-numeric
  robots crawl_delay), and the builder accesses report data defensively (.get
  with fallbacks; the one required data['slug'] raises a clear error by
  design). Genuine gap: the L1/L4 header-as-list never-raise fix is locked in
  only for the two scanners with direct tests; the contract test feeds
  well-formed single-value headers, so a future host scanner reading a header
  unsafely would not be caught. Add a contract-level test that runs every
  host tool against a response whose security headers are duplicated
  (list-valued) and asserts none raises and each returns a dict. Accept: the
  new test exercises all registered host tools with list-valued headers; it
  passes now; scanner suite green.
- [x] **L17 (done, M)** Replenishment from the iteration-5 partial audit: guard
  the pure-stdlib scanner charter (PLAN.md principle 2; README badge "scanner
  dependencies zero"). Nothing enforces that every scan_*.py imports only the
  standard library plus local modules, so a stray third-party import would
  silently break the project's load-bearing invariant. The invariant currently
  holds (verified: ast-parsed every scanner's imports against
  sys.stdlib_module_names plus {common, registry, htmlmeta, sibling scanners} -
  zero external). Add a check (a test in test_review_tools, or a tools/ script
  run in CI) that does this parse and fails on any external import. Accept: the
  check passes now; adding a fake "import requests" to any scanner makes it
  fail; it runs offline in the suite or CI.
  Done: TestScannerCharter.test_scanners_import_only_stdlib_and_local ast-parses
  every scan_*.py and asserts each top-level import is in sys.stdlib_module_names
  or a local .py stem; a companion test proves the guard is not vacuous (it
  flags requests). Passes now; verified end to end that injecting "import
  requests" into scan_seo.py fails the guard and names the offender (then
  restored). Runs in the offline suite (so CI). Scanner 280 -> 282, green;
  README resynced to 282/313.
- [x] **L22 (done, S)** Replenishment from the iteration-10 partial audit, which
  swept ReDoS risk and found the scanner regexes safe (negated char classes,
  lazy-with-anchor, and simple \s*/\d+ quantifiers - no (X+)+/(X*)* nesting;
  input is bounded by MAX_BODY_BYTES). That is the seventh class audited clean;
  the Phase L pass is fully converged. Genuine DX task felt firsthand this run:
  every added test forces a manual four-site README count edit. Give
  check_readme_counts.py a --fix mode that rewrites the README counts (badge,
  summary, both comments, tree, and the line-17 registry counts) to the
  measured values, so contributors run one command instead of hand-editing.
  Accept: with a drifted README, --fix rewrites it and a following plain run
  exits 0; without --fix behaviour is unchanged; a test drives the rewrite over
  an in-memory README string.
  Done: added a pure fixed_readme(text, scanner, builder, scanners, categories)
  to check_readme_counts.py that regex-rewrites all seven count sites (the two
  suite comments disambiguated by the test module named on their line), plus a
  --fix branch in main() that writes it back; without --fix behaviour is
  unchanged (check and exit 0/1). Dogfooded live: adding this task's own test
  drifted the suite to 285, a plain run reported the four drifted sites (exit 1),
  --fix rewrote README to 285/316 preserving surrounding text (e.g. the scanner
  comment tail), and the following plain run exited 0. Test
  test_fix_rewrites_every_drifted_count_site drives the rewrite over an in-memory
  README fixture: a fully drifted copy yields mismatches, fixed_readme clears
  them all, and re-fixing is a no-op (idempotent). Scanner 284 -> 285, builder
  31, both green; README resynced to 285/316 via --fix itself (guard exit 0).

### Later (Low) - replenishment from the third run's partial audit (2026-07-04)
Open fell to two (L21, L22) after L20, so a partial audit ran on a class not
previously swept: division-by-zero / empty-collection math. Clean across the
suite, no new task filed. scan_readability.py:105 (word_count / sentence_count)
cannot divide by zero - word_count >= MIN_WORDS (100) guarantees non-whitespace
text, which guarantees _sentences returns >= 1 part (reproduced: 80 words of
punctuation-free text still yields sentence_count 1); :120 (syllables /
word_count) and :107 (link_words / word_count) are covered by the same >= 100
floor and an explicit "if word_count" guard; common.grade guards graded == 0 ->
score None; scan_performance.py:146 guards uncompressed / transfer with
"if transfer"; scan_vitals has no variable division. Eighth class audited clean
(after substring-parsing, header-as-list, int/float, mutable-defaults,
concurrency, builder-access, ReDoS, and now the output-repr class L20 closed).
L21 (record enforced invariants in PLAN) and L22 (README --fix) remain the
genuine open items.

## Phase K - Quarterly trend layer follow-ups (final review backlog 2026-07-02)
- [x] **K1 (done, S)** Order-independent quarter selection: trends.quarterly_points
  takes the last ledger line in file order as a quarter's point; a backfilled
  line appended later would silently win. Select max by measured_at_utc within
  each quarter instead.
  Done: quarterly_points now keeps the entry with the greatest measured_at_utc
  per quarter regardless of file position; docstring updated. Tests: a
  backfilled line appended after a later run no longer shadows it, plus a
  2025-Q4 -> 2026-Q1 boundary case (also covers K5's year-boundary ask).
- [x] **K2 (done, S)** report_charts raises for missing matplotlib even when no
  series is drawable (all pre-metrics ledger); gate the RuntimeError on actual
  drawability so the failure tracks need.
  Done: new pure _any_series_drawable helper checks overall/category/metric
  drawability before touching matplotlib; render_trend_charts returns [] when
  nothing would draw and only raises RuntimeError once something needs mpl.
  Tests fake HAVE_MPL = False in a non-skip-guarded class covering both paths.
- [x] **K3 (done, S)** archive_scan stamps "unknown" when measured_at_utc is
  missing and would silently overwrite a prior unknown archive; raise instead
  (archive is business data). Related: same-second stamps overwrite, accepted
  at quarterly cadence.
  Done: archive_scan now raises ValueError when measured_at_utc is falsy; the
  "unknown" fallback is gone. Test covers the refusal; existing archive tests
  unaffected since the pipeline always stamps.
- [x] **K4 (done, S)** Builder chart prefix falls back to "site" when data lacks
  slug, so two clients' trend PNGs could overwrite under _evidence/rendered/.
  Consider failing loudly instead.
  Done: the "site" fallback is gone; add_trend_section raises ValueError
  naming the missing slug once a trend reaches three quarters (charts about
  to render). A two-quarter trend (no charts) still builds without a slug.
- [x] **K5 (done, S)** trends._delta_rows drops categories present in the prev
  quarter but absent from current bands; emit them as held/not-measured rows.
  Also add a year-boundary quarter-sort test and a draft test with delta and
  trend present simultaneously.
  Done: _delta_rows appends prev-only categories (skip overall) after the
  current-category rows, with band None and direction "held". Year-boundary
  quarter-sort test added under K1 (2025-Q4 -> 2026-Q1). Draft test added
  confirming progress carries both delta fields (previous_date, new_issues,
  resolved_issues) and trend together; passed on first run, confirming
  draft() already composed them correctly.

## Phase J - Automation of the rendered tier (user request 2026-07-02)
- [x] **J3 (done, M)** Prospect triage mode. Spec: PLAN.md section 36. New
  tools/triage.py sweeps a domain list (static, homepage-only, serial,
  polite), ranks sites worst-first as prospects, and picks a measured
  door-opener hook per site (priority: plain HTTP, cert expiry, trackers
  without consent, missing security headers, poor perf/a11y band, SEO gaps,
  else weakest area). CSV + Markdown output under the git-ignored sales/;
  input from sales/prospects.txt, a --file, or CLI domains; unreachable
  domains become a flagged row, not a crash. Reuses scan_site.run
  homepage-only; no new measurement. Suite 223 -> 234 (11 triage tests, all
  offline via stubbed run). Live: ranked example.com/neverssl.com/python.org
  worst-first with correct measured hooks. Committed PROSPECTS.example.txt
  template; README + SKILL documented.

- [x] **J2 (done, L)** CEO-grade report refresh. Spec: PLAN.md section 35.
  Cover page (kicker, Georgia display title, short gold rule, posture chip,
  meta, static contents list, method line), Georgia/Calibri two-face
  typography, numbered gold section headings, bottom line as a display-type
  statement behind a navy bar, measured score bars in the scorecard
  (draft_report_data now emits the numeric score per row; the redundant
  score suffix is stripped from the detail column when a bar renders),
  white cards for tiles and vitals, colored-underline assessment columns,
  different-first-page running header with content numbering from page 1.
  Data contract unchanged. Builder suite 16 -> 20, scanner 222 -> 223, all
  green. Verified on a rendered PDF: the Word COM export that hung during
  F1 works again under a guarded PowerShell call, so the design was
  inspected page by page before delivery (cover, cards, bars, chips all
  render as specified). Preview docx and PDF sent to the user for the
  visual verdict.

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

- [x] **J4 (done, M)** Key-dates conversation starters. Spec: PLAN.md section
  37. New common.rdap_domain (IANA-bootstrap RDAP lookup, passive, stdlib-only,
  stubbed offline, honest degradation on unsupported TLDs); scan_dns_email
  domain_expiry + domain_created info checks (never scored, so the email-auth
  band is unchanged); scan_tls gains an ISO expires_on. draft_report_data
  assembles a key_dates panel (cert renewal, domain renewal, domain age) and
  the builder renders it as a white-card "Key dates" section. Suite 234 -> 242
  scanner + 20 -> 21 builder. Live: RDAP returned real dates for python.org
  (registered 1995, renews 2033) and example.com; .co has no public RDAP so
  archanalytics honestly shows only the SSL cert card. example.com report
  renders all three cards.

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
  client-a pages and 15 python.org pages, and had to be hand-corrected in the
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
