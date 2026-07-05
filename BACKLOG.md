# BACKLOG.md - Prioritized task list

Statuses: todo, doing, done, blocked. One task per loop iteration. Pick the
highest-priority unblocked `todo`. Keep tasks small enough to finish and verify
in a single run; split anything larger. See PLAN.md for the design each task
serves.

## Phase P - Fourth convergence-audit findings (2026-07-04)
The fourth full-audit pass (after O1-O8 closed; four independent auditors, all
suites green at 307 + 32 + 8 beforehand) confirmed every prior fix and closed
class holds, but found four more: a partial-failure sibling of the M1 fabrication
class, an IPv6-slug crash, an untested grader, and an unbounded decompression
path. One High and three Medium, so convergence is still not met. Each cites
file:line and a reproduced behavior; see JOURNAL.md 2026-07-04 (Phase P audit).

### Now (High)
- [x] **P1 (done, S)** check_https_redirect fabricates a hard "fail" when the
  site DID redirect http->https but the https target failed at the connection
  level. scan_http_security.py:32-41: the only guard is
  `if not res["ok"] and not res["hops"]` (total failure -> info). But http_fetch
  records the 3xx hop before opening its target; when that target then fails with
  a connection-level error (URLError/timeout, not an HTTPError), no second hop is
  appended, so res is ok=False with hops=[the 301] and final_url the pre-redirect
  http:// URL. check_https_redirect skips the guard (hops present), reads
  final_scheme from the http URL, and grades fail "Plain HTTP is served without a
  redirect to HTTPS" - though the chain itself shows a 301. Reproduced: an
  ok=False result whose only hop is a 301 yields verdict fail with
  redirect_chain ['301 http://host.test']. A fabricated security fail into the
  deliverable, the M1 class one case deeper (M1 fixed the header checks; this
  check has its own total-failure-only guard). No test covers check_https_redirect
  at all. Fix: when ok is False, do not grade a fail off the pre-redirect URL;
  if the last hop is a 3xx toward https treat it as info/pass, else info. Accept:
  a test stubbing http_fetch to an ok=False result whose last hop is a 301 asserts
  the verdict is not fail (info or pass); a genuine no-redirect http page still
  fails; a normal https redirect still passes; scanner suite green.
  Done: when res is ok=False (a hop recorded but the fetch did not complete),
  check_https_redirect no longer grades off the pre-redirect http URL. It reads
  the last hop's Location via header_value and, if it points at https, returns
  pass ("redirects to HTTPS; target not reachable this run"), else info; the
  total no-hops case stays info. Verified the full matrix: 301->https connect
  failure -> pass (was fail), 301 bare -> info, served-over-http -> fail,
  completed http->https -> pass, no-answer -> info. New test
  test_https_redirect_not_fabricated_on_partial_failure (the check had zero
  coverage before). Scanner 307 -> 308, both green; README resynced to 308/340
  via --fix (guard exit 0).

### Next (Medium)
- [x] **P2 (done, S)** An IPv6-literal target crashes the run on Windows.
  common.slug_of (common.py:55-60) drops the scheme and www. and maps dots to
  hyphens but does not constrain the result to filesystem-safe characters, so
  http://[2001:db8::1]/ yields slug "2001:db8::1"; the colon is an illegal
  Windows filename character, and the first write_json (scan_site.py:451, plus
  _history.jsonl, the archive path, and rendered/<slug>) raises an uncaught
  OSError [Errno 22] that aborts the run. Reproduced: slug_of("http://[2001:db8::1]/")
  == "2001:db8::1". Not traversal (slug can never produce ".."; verified). Medium:
  a real crash but on an uncommon IPv6-literal target, and the slug is
  operator-supplied (never a redirect/third-party value). Fix: constrain the slug
  to [a-z0-9-], e.g. re.sub(r"[^a-z0-9-]+", "-", host.replace(".", "-")).strip("-"),
  mirroring snapshot_filename. Accept: a test asserts slug_of on an IPv6-literal
  and a colon/port host contains no ":" or path separator and is non-empty; the
  normal host->slug cases are unchanged; scanner suite green.
  Done: slug_of now maps filesystem-illegal characters ([\\/:*?"<>|] and control
  chars) to a hyphen after the dots-to-hyphens step, then strips edge hyphens.
  Chose the surgical set over the acceptance's [a-z0-9-] so unicode-IDN hosts stay
  readable (uber.example -> uber-example, not stripped). Verified:
  [2001:db8::1] -> 2001-db8-1 (safe), example.com -> example-com and
  192.168.0.1 -> 192-168-0-1 unchanged, IDN preserved. New test
  test_slug_of_is_always_a_safe_filename. Scanner 308 -> 309, both green; README
  resynced to 309/341 (guard exit 0).
- [x] **P3 (done, S)** The readability grader's entire graded-output path is
  untested. scan_readability.py:119-145 computes the Flesch score, the FK grade,
  and the pass/warn/fail verdicts (pass >= 50, warn >= 30, fail < 30; sentence
  length warn at 25) - the load-bearing output of the readability category. Both
  tests that drive rd.scan() feed non-prose input and assert verdict info, so
  they return early at the guards (lines 95, 108) and never reach the grading
  block; coverage reports scan_readability.py:119-145 as Missing. A regression to
  a Flesch coefficient, a threshold, or the spw term ships silently. Fix: add a
  test feeding a real prose page (>= 100 words, prose punctuation) through
  rd.scan() and assert a concrete flesch_reading_ease value plus the pass/warn/
  fail verdict. Accept: a new test drives rd.scan() on prose and asserts the
  numeric Flesch score and the reading_ease verdict; coverage shows 119-130
  executed; scanner suite green.
  Done: test_prose_is_graded_with_pinned_flesch_scores drives two real prose
  pages through rd.scan() - simple prose pins flesch 108.4, fk 0.7, verdict pass;
  dense academic prose pins flesch -150.1, verdict fail - covering the formulas
  and both the pass and fail threshold branches with exact values, so a
  coefficient, spw-term, or threshold change breaks the test. scan_readability
  coverage rose to 87% (grading block 119-130 now executed; the remaining misses
  are the main() CLI). Test-only, no code change. Scanner 309 -> 310, both green;
  README resynced to 310/342 (guard exit 0).
- [x] **P4 (done, S)** Unbounded decompression (decompression-bomb OOM).
  common._decompress (common.py:131-140) calls
  zlib.decompressobj(...).decompress(raw) and brotli.decompress(raw) with no
  max_length, so a 3 MB body served with Content-Encoding: gzip (DEFLATE reaches
  ~1000:1) expands to gigabytes; _decode_body then makes a second multi-GB str,
  and the except (OSError, zlib.error) does not catch MemoryError. MAX_BODY_BYTES
  caps the compressed read, not the decompressed output. The tool points at
  arbitrary external sites and triage.py sweeps unknown prospect domains, so a
  hostile or misconfigured target is in the threat model; scan_links/
  scan_performance run 8 concurrent fetches, multiplying the spike to an OOM-kill.
  Re-opened from the Phase O Declined list: that decline reasoned "MAX_BODY_BYTES
  already caps the download", which is factually wrong (it caps the compressed
  read), and did not account for triage's unknown-domain sweep. Fix: decompress
  incrementally with a decompressed-byte ceiling
  (decompressobj().decompress(raw, MAX_DECOMPRESSED_BYTES); treat a non-empty
  unconsumed_tail as truncate-here, mirroring the wire-truncation semantics) on
  the gzip, deflate, and brotli branches. Accept: a test feeds a small gzip body
  that decompresses past the ceiling and asserts _decompress returns at most the
  ceiling of bytes without raising; a normal body still round-trips; scanner suite
  green.
  Done: added MAX_DECOMPRESSED_BYTES = 30 MB and passed it as the max_length to
  the gzip and both deflate decompressobj().decompress calls, so a compression
  bomb is truncated at the ceiling instead of inflating to GBs (the same
  truncate-here semantics as the wire cap). The optional brotli path (never
  advertised in Accept-Encoding, so only a non-conformant server hits it) slices
  its result defensively. Verified with a patched-small ceiling: a 100 kB gzip
  and deflate bomb each return <= the ceiling; a normal body round-trips whole; a
  real full body decompresses fully at 30 MB and the M7 truncated-prefix behavior
  still holds. New test test_decompress_bounds_output_against_a_bomb. Scanner
  310 -> 311, both green; README resynced to 311/343 (guard exit 0). All three
  Phase P Medium (P2, P3, P4) plus the High (P1) are closed.

- [x] **P7 (done, M)** A crashed scanner is silently graded around, so a category
  whose primary scanner threw can still read "Strong". _safe_scan (scan_site.py:34)
  demotes any unexpected exception to `{"tool", "ok": False, "error"}` with no
  `checks` and no `verdict`. Three downstream consumers then treat that as a
  non-event: (1) the host-issue loop (scan_site.py:220-228) needs `checks` or a
  warn/fail verdict, so a crash contributes zero issues; (2) the page-issue loop
  (scan_site.py:229-232) gates on `ps[key].get("ok")`, so a crash is skipped;
  (3) build_scorecard (scan_site.py:155-165) rolls `common.verdicts_of` (which
  returns [] for a no-checks dict) into the category, so the category is graded
  only from its surviving sibling scanners. Reproduced: forcing scan_http_security
  to raise KeyError while scan_page_security passes yields security band =
  "Strong", score 1.0 (HSTS/CSP/clickjacking/cookies never ran), with the crash
  visible only as host_scans["http_security"]["error"] buried in the JSON - no
  line in the console summary or `<slug>_scan_summary.md`. This violates the
  charter (never report an unmeasured thing as pass/fail): a shared-category crash
  inherits a clean band from the survivor instead of reading degraded/unmeasured.
  Contrast scan_tls, whose own network-failure path returns verdict:"fail" and is
  surfaced. Found by the P5-run replenishment partial audit (observability
  dimension). Fix: surface every result where `ok is False and "verdict" not in
  result` (naming tool + error) in write_digest_md and the console summary, and
  make an errored scanner's category read as degraded rather than grading around
  it (e.g. verdicts_of a crashed scanner yields one "fail"/"info" so the band
  cannot float to Strong). Accept: a test monkeypatches one scanner to raise, runs
  scan_site, and asserts (a) the digest md and stdout both contain the errored
  tool_id and its error string, and (b) that scanner's category band is not
  "Strong"; scanner suite green.
  Done: build_scorecard (scan_site.py) now tracks, per category, any scanner that
  ran but produced no gradable verdict and reported ok False (a crash or an
  unfetchable target); such a category is graded Not measured with score None and
  an `errors: [tool_id]` list (the real pass/warn/fail counts still travel), and
  the overall grade carries an `errors` list so a crash is visible there too. A
  new errored_scanners(host_scans, page_scans) collects the same set for display,
  stored on the result as `scanner_errors` and surfaced in write_digest_md
  ("## Scanner errors") and a new print_console_summary (extracted from main as a
  testable seam) ("SCANNER ERRORS"). Two tests:
  test_crashed_scanner_does_not_float_category_to_strong (unit) and
  test_crashed_scanner_is_surfaced_in_digest_and_console (end to end: monkeypatch
  scan_http_security to raise KeyError, run site.run, assert security band ==
  "Not measured", the crash named in scanner_errors, the digest md, and the
  console summary). Scanner 313 -> 315; exec-report 32 and report-charts 8
  unchanged; README resynced to 315/347 (guard exit 0). Every Phase P High and
  Medium is now closed.

- [x] **P10 (done, M)** parse_rdap_domain crashes on a conformant object whose
  `events` field is a truthy non-list scalar, discarding good DNS-email verdicts.
  common.py:407-408 does `for e in (data.get("events") or [])`: the `or []` idiom
  only rescues falsy junk, so a truthy scalar passes straight into the loop.
  Reproduced: parse_rdap_domain({"events": 3}) -> TypeError: 'int' object is not
  iterable (also True, 1.5). This is the L3 non-dict-JSON class one level deeper -
  L3 guarded the top-level body being a non-dict (test_parse_rdap_non_dict_body_
  degrades passes None/[]/"x"/3 as the whole body), but left the nested `events`
  field. Impact: rdap_domain calls parse_rdap_domain at common.py:429 OUTSIDE its
  try/except, and scan_dns_email._scan (scan_dns_email.py:292) calls
  check_domain_registration unguarded, so a non-conformant registry (exactly the
  "stray array/string/null from a third-party RDAP server" the docstring already
  anticipates) crashes the whole dns_email scan; _safe_scan then marks the entire
  dns_email category "Not measured", throwing away the SPF/DMARC/DKIM/DNSSEC/
  MTA-STS verdicts that had already succeeded. Found by the P6-run replenishment
  partial audit (error-handling dimension). Fix: `events = data.get("events");
  ... for e in (events if isinstance(events, list) else [])`. Accept:
  parse_rdap_domain({"events": 3})["ok"] returns without raising; add {"events": 3}
  (and a truthy scalar) to the loop in test_parse_rdap_non_dict_body_degrades;
  scanner suite green.
  Done: common.py now binds `raw_events = data.get("events")` and iterates
  `raw_events if isinstance(raw_events, list) else []`, so a scalar events field
  degrades to an empty event set instead of raising. Extended
  test_parse_rdap_non_dict_body_degrades to assert ok True (expiration/registration
  None) for events in (3, True, 1.5, "expiration"); the real-array and
  bogus-element-in-array cases still pass. Scanner suite green at 318 (existing test
  extended, not a new method, so counts unchanged); guard exit 0.

- [x] **P13 (done, M)** Accessibility flags a form's submit/button/image inputs as
  unlabeled, a false FAIL on nearly every real form. htmlmeta.py:122 admits every
  input except hidden into form_controls, and scan_accessibility._accessible_name
  (scan_accessibility.py:28) never consults `value` (the accessible name of a
  submit/reset/button) or `alt` (image input). Reproduced: a standard search form
  `<label for=q>Search</label><input type=text id=q><input type=submit value=Search>`
  grades form_labels = FAIL "1 control(s) have no programmatic label", example
  "submit". A submit/reset/button input always has an accessible name (its value,
  defaulting to "Submit"), and an image input uses alt, so they are not
  label-requiring controls. This false FAIL drags the whole accessibility band
  down. Found by the P9-run replenishment partial audit (grading-logic dimension).
  Fix: exclude button-type inputs from the labelable set at htmlmeta.py:122
  (`itype not in ("hidden", "submit", "reset", "button", "image")`). Accept: on the
  snippet above form_labels == "pass"; a bare `<input type=text name=q>` with no
  label/aria still FAILs; scanner suite green.
  Done: went one better than a blanket exclude - htmlmeta.py:122 now drops only the
  push buttons (submit/reset/button) from form_controls (their name comes from
  value/default), but KEEPS image inputs and captures their `alt`;
  _accessible_name (scan_accessibility.py) treats an image input's alt as its
  accessible name. So the common submit-button false FAIL is gone AND an alt-less
  image button is still correctly failed (no new false PASS). Used control.get for
  type/alt so the minimal test dicts in test_accessible_name still work. New test
  test_form_labels_ignore_buttons_and_honor_image_alt: labeled form + submit/reset
  -> pass; bare text no label -> fail; image with alt -> pass; image without alt ->
  fail. Scanner 318 -> 319; README resynced to 319/351 (guard exit 0); no builder
  change.
- [x] **P14 (done, M)** SEO robots-meta check misses `content="none"`, a false PASS
  on a de-indexed page. scan_seo.py:74 tests only `"noindex" in robots.lower()`,
  but `<meta name="robots" content="none">` is defined by Google as equivalent to
  `noindex, nofollow` - the page is excluded from search. Reproduced:
  _robots_meta_check("none") -> verdict "pass" note "Robots meta: none.". A site
  that accidentally ships `content="none"` (invisible to search) gets a clean SEO
  verdict. Found by the P9-run replenishment partial audit (grading-logic dimension).
  Fix: treat the `none` directive as noindex - lowercase, split on comma/space, and
  fail if the token set contains "noindex" or "none". Accept:
  _robots_meta_check("none")["verdict"] == "fail"; _robots_meta_check("index,
  follow")["verdict"] == "pass"; a note that mentions "nonexistent" or similar does
  not false-trigger (token match, not substring); scanner suite green.
  Done: _robots_meta_check now splits the content value on commas into a lowercased
  token set and fails if it contains "noindex" or "none", so content="none" (and
  "NONE", whitespace-padded) correctly fails while "index, follow"/"all" pass and
  "nonexistent"/"noindexing" pass (token match, not substring - also closes a latent
  substring risk in the old check). Extended test_robots_meta with the none/NONE/
  index-follow/all/nonexistent cases. Scanner suite green at 319 (existing test
  extended, count unchanged); guard exit 0; no builder change.
- [x] **P15 (done, M)** Mixed-content check mislabels an http `<link rel=canonical>`
  as active mixed content, a false FAIL. scan_links.py:39 `ACTIVE_TAGS` contains
  "link" unconditionally and MIXED_RE (scan_links.py:36) matches any `<link
  href="http://...">` regardless of rel. Reproduced: on an https page, `<link
  rel="canonical" href="http://example.com/">` grades mixed_content = FAIL "1
  insecure http reference(s); 1 are active content (script/iframe/stylesheet)". But
  rel=canonical/alternate/preconnect/dns-prefetch/icon are not subresource loads and
  are not mixed content; only rel=stylesheet (and preload as=style/script) is active
  mixed content. This is a security FAIL, mislabeled "stylesheet", on a page with
  zero mixed content. Found by the P9-run replenishment partial audit (grading-logic
  dimension). Fix: gate the `<link>` branch on rel - treat only a rel containing
  "stylesheet" as active mixed content, and do not count canonical/alternate/
  preconnect/dns-prefetch/icon as mixed content at all. Accept: `<link rel=canonical
  href="http://x/">` on https -> mixed_content pass; `<link rel=stylesheet
  href="http://x/s.css">` -> fail; `<script src="http://x/j.js">` still fail,
  `<img src="http://x/i.png">` still warn; scanner suite green.
  Done: removed "link" from MIXED_RE and ACTIVE_TAGS and added a dedicated <link>
  scan that reads each link's rel/href/as from its full attribute string (so
  attribute order does not matter). Only a subresource-loading rel counts:
  stylesheet -> active (fail), a preload/prefetch with as in {script,style,worker,
  font} -> active, icon-family/other preload -> passive (warn), and canonical/
  alternate/preconnect/dns-prefetch/etc -> skipped entirely (not a fetch).
  Deviation from the filed fix: an http rel=icon favicon IS passive mixed content,
  so it warns rather than being ignored - more correct than skipping it, and it
  never false-FAILs. New test test_mixed_content_link_rel (TestLinkChecks) covers
  canonical/alternate/preconnect (pass, incl. href-before-rel), stylesheet (fail),
  icon (warn), preload as=script (fail), and the script/img regressions. Scanner
  319 -> 320; README resynced to 320/352 (guard exit 0); no builder change.
- [x] **P16 (done, M)** Clickjacking check accepts permissive/ignored framing
  directives as protection, a false PASS. scan_http_security.py:110-111 tests only
  that the `frame-ancestors` directive NAME exists and that X-Frame-Options is
  non-empty, never their values. Reproduced: `frame-ancestors *` (every origin may
  frame the page - no protection) -> pass; `X-Frame-Options: ALLOW-FROM https://x`
  (deprecated, ignored by Chrome/Edge/Safari) -> pass; `X-Frame-Options:
  totally-bogus` -> pass. Only DENY/SAMEORIGIN and a non-wildcard frame-ancestors
  actually protect, so a site with real clickjacking exposure is reported protected.
  Found by the P9-run replenishment partial audit (grading-logic dimension). Fix:
  require XFO to be deny/sameorigin (case-insensitive), and require frame-ancestors
  to have at least one source that is not `*`. Accept:
  check_clickjacking({"content-security-policy":"frame-ancestors *"})["verdict"] ==
  "fail"; check_clickjacking({"x-frame-options":"ALLOW-FROM https://x"})["verdict"]
  == "fail"; check_clickjacking({"x-frame-options":"SAMEORIGIN"})["verdict"] ==
  "pass" and a real `frame-ancestors 'self'` stays pass; scanner suite green.
  Done: check_clickjacking now grades values, not presence. XFO protects only when
  it normalizes (strip/lower) to deny or sameorigin; frame-ancestors protects
  unless its source list contains a bare `*` (an empty list is 'none', which
  protects). A directive present but ineffective now fails with a note saying so
  (worse than absent - the site looks protected). New test
  test_clickjacking_rejects_permissive_and_ignored_directives covers frame-ancestors
  * / ALLOW-FROM / bogus (fail) and SAMEORIGIN / frame-ancestors 'none' / a specific
  allow-list origin (pass); the existing DENY / 'self' / folded-header / duplicate
  cases stay green. Scanner 320 -> 321; README resynced to 321/353 (guard exit 0);
  no builder change. Closes the last grading-logic Medium (P13-P16 all done).

- [x] **P17 (done, M)** DNSSEC check grades a zone "signed" from DNSKEY presence,
  ignoring the resolver AD flag - a false PASS on a zone that is not actually
  validated. scan_dns_email.py:147-148 returns verdict "pass" "zone is signed"
  whenever res["answers"] is non-empty (DNSKEY published), but a zone can publish a
  DNSKEY while its parent has no DS record, so the chain of trust is never
  established and a validating resolver treats it as insecure - an attacker can
  strip DNSSEC undetected. doh_query already returns the resolver's `ad`
  (Authenticated Data) flag (common.py), which is the correct signal (DNSKEY
  validated up a DS-anchored chain). Reproduced: a stubbed DNSKEY answer with
  ad=False yields {signed: True, verdict: pass}. Found by the P16-run replenishment
  partial audit (grading-logic dimension, capture/DNS tier). Fix: grade on
  res["ad"] - DNSKEY present with ad True -> pass; DNSKEY present with ad False ->
  info/warn ("keys published but not anchored by a parent DS"); no DNSKEY -> info as
  now. Accept: stub doh_query DNSKEY with ad=False -> not "pass"; with ad=True ->
  "pass"; scanner suite green.
  Done: check_dnssec now grades on res["ad"]. DNSKEY present with ad True -> pass
  ("published and validated by the resolver"); DNSKEY present with ad False -> warn
  ("published but the resolver did not authenticate it; likely missing a parent DS,
  so validators treat it as unsigned"); no DNSKEY -> info as before; lookup failure
  -> info. New test test_dnssec_grades_on_ad_flag_not_dnskey_presence. Scanner
  321 -> 322; README resynced to 322/354 (guard exit 0); no builder change.
- [x] **P18 (done, M)** DMARC check never parses `pct`, so `p=reject; pct=0` grades
  as full reject - a false PASS. scan_dns_email.py:79-92 parses only the p= tag; the
  pct tag (percentage of mail the policy applies to) is ignored, so a record that
  enforces reject on 0% of mail (receivers fall back to the lower policy - a
  documented monitor-while-claiming-reject pattern) is graded pass "DMARC policy is
  reject". Reproduced (stubbed _txt_records): "v=DMARC1; p=reject; pct=0" ->
  verdict pass; also p=quarantine; pct=0 -> pass. Found by the P16-run replenishment
  partial audit (grading-logic dimension). Fix: parse pct=; when policy is reject or
  quarantine and pct==0, downgrade to warn ("policy applies to 0% of mail;
  effectively monitoring"). Accept: check_dmarc on a stubbed p=reject;pct=0 record
  -> warn (not pass); p=reject with no pct or pct=100 -> pass; scanner suite green.
  Done: check_dmarc now parses pct= as an int in the tag loop; when policy is
  reject or quarantine and pct==0 it warns ("applies to 0% of mail, effectively
  monitoring only"), otherwise the enforcing policies still pass and a missing or
  unparseable pct defaults to full enforcement (pass). The record's pct is returned
  in the result dict. New test test_dmarc_pct_zero_is_not_full_enforcement covers
  reject/quarantine pct=0 (warn), pct=100 and pct-absent (pass). Scanner 322 -> 323;
  README resynced to 323/355 (guard exit 0); no builder change.
- [x] **P19 (done, M)** CSP check false-WARNs a strict-dynamic/nonce policy - the
  modern best practice - as "weakened". scan_http_security.py:171-177 flags a
  wildcard/scheme source (http:/https:/*) and unsafe-inline in the script directive
  without accounting for 'strict-dynamic' or nonce/hash sources. When
  'strict-dynamic' is present, supporting browsers ignore host/scheme allowlists and
  'unsafe-inline' entirely (the allowlist is a legacy fallback); a nonce or hash
  source also nullifies 'unsafe-inline'. Reproduced: `script-src 'strict-dynamic'
  'nonce-r4nd0m' https: 'unsafe-inline'` -> warn "allows any origin (https:);
  permits unsafe-inline", both cited weaknesses inert - so a genuinely strong CSP
  (what Google's CSP Evaluator rates high) is graded down, a misleading false WARN.
  Found by the P16-run replenishment partial audit (grading-logic dimension). Fix:
  if 'strict-dynamic' in the script sources, do not flag the host/scheme allowlist
  or unsafe-inline; if any nonce-/sha256-/sha384-/sha512- source is present, do not
  flag unsafe-inline. Accept: `script-src 'strict-dynamic' 'nonce-x' https:` ->
  pass; `script-src https: 'unsafe-inline'` (no strict-dynamic) stays warn;
  `script-src 'nonce-x' 'unsafe-inline'` -> pass (nonce nullifies unsafe-inline);
  scanner suite green.
  Done: check_csp now detects 'strict-dynamic' and nonce-/sha256-/sha384-/sha512-
  sources. With strict-dynamic it skips the host/scheme allowlist finding (browsers
  ignore it) and the unsafe-inline finding; with a nonce/hash it skips only the
  unsafe-inline finding; unsafe-eval is always flagged (unaffected by both). New
  test test_csp_strict_dynamic_and_nonce_are_not_weaknesses covers the pass cases
  and the still-warn cases (bare https:+unsafe-inline, strict-dynamic+unsafe-eval).
  Scanner 323 -> 324; README resynced to 324/356 (guard exit 0); no builder change.
  Closes the last grading-logic Medium (P13-P19 all done).

- [x] **P20 (done, M)** A real finding silently vanishes from the CEO deliverable
  when a poor site has many host-level fails. draft_report_data.draft builds
  `ordered = fails + warns` in raw scanner-registry order (host scanners first) and
  slices `ordered[:MAX_FINDINGS]` (cap 15, draft_report_data.py:25,341) with no
  disclosure pointer; separately _action_plan caps at MAX_ACTIONS=10 and _plan_order
  (draft_report_data.py:180) gives every host issue breadth=inf, so all host issues
  outrank any page issue. Reproduced: a scan with 15 site-wide host fails plus one
  accessibility form_labels fail affecting all 40 pages yields findings=15 (a11y
  absent), action_plan=10 (a11y absent), and no "N more" pointer - the 40-page
  accessibility failure disappears from the entire report while trivial host items
  survive. This violates the "name every subject, no silent truncation" bar (memory:
  findings-name-every-subject); contrast _page_list (draft_report_data.py:112) which
  already appends a "+N more in scan_summary.md" pointer for pages within a finding.
  Found by the P19-run replenishment partial audit (report-data transformation).
  Fix: when len(ordered) > MAX_FINDINGS, append a disclosure finding naming the
  omitted count and pointing at <slug>_scan_summary.md (and sort ordered so fails
  precede warns before slicing, which already holds). Accept: re-run the
  15-host-fail + all-pages-a11y repro and assert either form_labels is in
  data["findings"] or a pointer finding names the omitted count; suites green.
  Done: removed the MAX_FINDINGS=15 truncation entirely (draft now names every
  distinct grouped finding). Chose completeness over a disclosure pointer because
  the grouped findings are already deduplicated to one entry per defect (naturally
  bounded, ~a few dozen worst case), the builder already sorts by severity and
  renders the whole set with no size assumption, and the user's standing bar is
  "name every subject, no silent truncation". The action plan keeps its
  MAX_ACTIONS=10 cap - it is intentionally a prioritized top-actions list and the
  full findings section now documents everything. Replaced test_findings_are_capped
  (which locked in the old cap) with test_findings_name_every_subject_without_
  truncation: 15 host fails + a 40-page a11y fail -> all 16 findings present, a11y
  included. Scanner suite green at 324 (test replaced, count unchanged); builder
  suites 32/8 green; guard exit 0.
- [x] **P21 (done, M)** The re-review "N new / N resolved" progress headline
  miscounts: it uses the flat per-page delta while every other count in the report
  is grouped by template defect. draft_report_data.py:359-360 sets new_issues /
  resolved_issues from len(delta["new"]) / len(delta["resolved"]); delta comes from
  scan_site.diff_issues (scan_site.py:112-115) which keys off the ungrouped per-page
  `issues` list, whose scan label carries the page URL, so one defect on N pages
  makes N distinct keys. Reproduced: one form_labels defect newly appearing on 40
  pages yields progress.new_issues = 40 while the findings table shows 1 grouped
  finding; the builder renders "40 new" in the CEO progress strip - a single new
  template defect reads as a 40-issue regression. Found by the P19-run replenishment
  partial audit (report-data transformation). Fix: dedup the delta by (label, check,
  verdict) with the per-page URL stripped from the label before counting, so the
  headline matches the grouped-finding view. Accept: re-run the 40-page single-defect
  repro and assert progress.new_issues == 1; suites green.
  Done: fixed at the source - diff_issues now keys by (scan.partition(":")[0], check,
  verdict), the same grouped identity group_issues uses, so it counts distinct
  defects not per-page instances. This corrects BOTH consumers consistently: the
  progress strip (attach_delta) and the report trend section (trends.build_trend),
  which both diff the ungrouped per-page ledger issues. A defect merely shrinking
  from 40 to 30 pages is now neither new nor resolved (it persists at the defect
  level), which matches the grouped-finding view. New test
  test_diff_issues_counts_defects_not_pages; the existing distinct-check diff test
  still passes. Scanner 324 -> 325; exec-report 32 and report-charts 8 green; README
  resynced to 325/357 (guard exit 0). Closes the last report-transformation Medium.

- [x] **P22 (done, M)** The scan set is not deduplicated, so the homepage is scanned
  twice and the deliverable claims "2 page(s)" for one physical page.
  scan_site._run (scan_site.py:235) does `page_urls = [target] + [normalize_url(u)
  for u in extra_pages]` with no dedup, and common.normalize_url does not strip a
  trailing slash, so `https://example.com` and `https://example.com/` are treated as
  two pages. The crawl path (run_review.py:81 filters extra by exact string only) and
  discovery both surface the `/` variant, since a homepage almost always links to
  `/`. Reproduced: scan_site.run("https://example.com", ["https://example.com/"])
  yields two page_scans for the same page. Consequence: group_issues gives every
  homepage failure pages=["https://example.com","https://example.com/"],
  page_count=2, and _finding_from_issue writes evidence "2 page(s):
  https://example.com, https://example.com/" - a false claim listing the same page
  twice; pages_scanned is inflated (cover "PAGES REVIEWED" tile) and the homepage's
  vitals/weight enter the trend medians twice. Found by the P21-run replenishment
  partial audit (integration flow). Fix: in scan_site._run, dedup page_urls after
  normalizing (a seen-set; the target is already normalized upstream). Accept:
  scan_site.run(target, [target + "/"]) produces exactly one page_scans entry;
  suites green.
  Done: scan_site._run now dedups the review set by a canonical key
  (scheme, netloc.lower(), path or "/", query), so an empty path and "/" collapse
  (https://h and https://h/ are one page) while distinct paths stay distinct
  (/a vs /a/ are kept, being genuinely-possibly-different resources). New test
  test_scan_set_is_deduplicated: homepage+slash -> 1 page, two distinct pages -> 3,
  /a vs /a/ -> 3. Scanner 325 -> 326; README resynced to 326/358 (guard exit 0);
  no builder change.
- [x] **P23 (done, M)** Stale rendered evidence from a prior run is graded as a
  current lab measurement. scan_vitals.load_metrics (scan_vitals.py:36-48) reads
  planning/_evidence/rendered/<slug>/metrics.json unconditionally with no freshness
  or run-scoping check and returns the entry, which the report labels "lab
  measurement, one load" (scan_vitals.py:65) with no date in the vitals panel.
  metrics.json persists across runs and capture merges over it (capture_rendered.py
  _load_or_new), and the page-failure branch does not overwrite a prior entry. So
  `python run_review.py --no-browser` after a prior browser run (capture=False, no
  new capture) still consumes the old metrics.json, presenting last run's Core Web
  Vitals as this run's; likewise a page that succeeded last run but fails capture
  this run shows stale "Good" vitals, masking a regression - the charter's
  "unmeasured thing reported as a pass". Found by the P21-run replenishment partial
  audit (capture correctness). Fix: stamp the current run id/timestamp on the
  captured metrics and have scan_vitals ignore entries not from the current run (or
  clear stale automated entries on a --no-browser / failed-capture run). Accept:
  after a --no-browser run with a pre-existing metrics.json, the vitals checks grade
  info / Not measured, not pass; suites green.
  Done: the metrics/manifest entries already carried captured_at_utc, so I added a
  freshness boundary rather than clearing evidence (CAPTURE.md guarantees a manual
  capture is never clobbered). run_review.pipeline stamps run_start at the start and
  passes min_capture_utc to both scan_site.run calls; scan_site threads it to
  load_rendered_snapshots (drops stale DOM) and onto each page context;
  scan_vitals.load_metrics rejects an entry with captured_at_utc < the boundary.
  Standalone scan_site.py / a manual capture pass None, so any on-disk evidence is
  still used (backward compatible). ISO-8601 UTC stamps compare lexicographically.
  New test test_stale_metrics_are_rejected_under_a_run_boundary (stale -> info, no
  boundary/fresh -> measured); updated two tests whose stubs predated the signature
  (one lambda arity, one fake_capture that stamped a fixed 2026-01-01 now stamps
  now). Scanner 326 -> 327; exec-report 32 and report-charts 8 green; README resynced
  to 327/359 (guard exit 0).
- [x] **P24 (done, M)** The contrast DOM walk ignores background images and assumes
  white, fabricating a false WCAG 1.4.3 violation that names the exact on-page text.
  capture_rendered.py CONTRAST_JS bgOf (capture_rendered.py:86-92) walks ancestors
  for a non-transparent backgroundColor and defaults to rgb(255,255,255) when none
  is opaque; it never reads background-image. For the common hero pattern (light
  text over a dark background image) every ancestor's backgroundColor is transparent,
  so the assumed background is white and white-on-white gives ratio 1.0, below the
  3/4.5 threshold, pushed as a violation. scan_vitals.check_contrast turns it into a
  fail whose text quotes the real heading ("... <hero text> (1.0:1, needs 3:1)"), so
  the docx states a specific accessibility failure that is false - fabricating a
  measurement against a background it could not read, which the charter forbids.
  Found by the P21-run replenishment partial audit (capture correctness); the P16-run
  audit noted this as a heuristic limit but it produces a definitive false claim, so
  it is filed. Fix: in bgOf, when an ancestor has a background-image (and no opaque
  backgroundColor is found) treat the element's background as unknown and skip it
  (inconclusive) rather than assuming white. Accept: an element whose only background
  is an ancestor background-image produces no contrast violation; a genuine
  dark-on-light element still does; suites green.
  Done: bgOf now returns null when an ancestor has a background-image or gradient
  (painted above any color, no single color to measure), and the loop skips such
  elements, counting them as inconclusive instead of grading them against an assumed
  white. check_contrast surfaces the skipped count in its note. Verified in a real
  JS engine (node): text over a background image -> inconclusive, no violation; a
  gradient likewise; a genuine gray-on-white -> violation; white on solid black ->
  measurable pass. Two tests: test_contrast_reports_inconclusive_skips (Python) and
  test_contrast_js_skips_background_image_elements (node-gated, skips where node is
  absent). Scanner 327 -> 329; exec-report 32 and report-charts 8 green; README
  resynced to 329/361 (guard exit 0). Closes the last capture-tier Medium.

- [x] **P25 (done, M)** http_fetch presents a capped or looping redirect chain as a
  success, yielding a false canonicalization "pass" for a host that never serves
  content. common.py http_fetch ran `for _ in range(max_redirects + 1)`, `continue`d
  on every 3xx+Location, and when the chain exceeded the cap (or looped) the loop
  exhausted without a terminal response and fell through to the success builder,
  setting ok=True, error=None, final_status=the last un-followed 3xx, body=None. So a
  looping host read as reachable. scan_crawl.check_host_canonicalization then keyed
  "reachable" off final_status is not None (a 3xx passes), so an apex->www with www
  looping to itself graded verdict "pass" "apex and www converge on www.example.com".
  Reproduced against the real code (stubbed opener): the loop fetch returned
  ok=True/final_status=301/body=None and canonicalization returned pass. Found by the
  P24-run replenishment partial audit (common.py HTTP core; trends/report_charts and
  the rest of common.py verified correct). Fix: http_fetch uses a for/else that raises
  TooManyRedirects when the loop exhausts on a redirect (the outer except turns it
  into ok=False with hops/final_status preserved); check_host_canonicalization filters
  reachable by r.get("ok") not final_status. Note: also completed in the P24 iteration
  (a deviation from one-task-per-iteration, but fully verified). Accept: the loop
  reproduction no longer verdicts pass (info: only one live host variant), and
  http_fetch on a looping URL returns ok=False with a redirect error, not ok=True.
  Done: implemented as above; a normal single redirect still succeeds (ok=True,
  final 200, body present). Two tests: test_over_cap_redirect_chain_is_not_a_success
  (http_fetch ok=False, redirect error, max_redirects+1 hops recorded) and
  test_looping_host_is_not_a_converged_pass (canonicalization info, no canonical_host).
  Scanner 329 -> 331; exec-report 32 and report-charts 8 green; README resynced to
  331/363 (guard exit 0).

- [x] **P26 (done, M)** JSON-LD @graph structured data is not detected, so a page
  rich in structured data is reported as having none. htmlmeta._collect_jsonld
  (htmlmeta.py:199-203) reads @type only from the top-level object (or top-level
  list members) and never descends into @graph, which is the dominant real-world
  shape (Yoast, RankMath, WordPress core all emit `{"@context":..,"@graph":[{...}]}`).
  Reproduced: parse_html of a script with `{"@graph":[{"@type":"Article",...}]}`
  yields jsonld_types == [], and scan_seo (scan_seo.py:135-138) then grades info
  "No JSON-LD structured data." on a page that has it - a confidently-wrong report
  statement that also drops a pass from the SEO grade. Found by the P11-run
  replenishment partial audit (parser correctness). Fix: in _collect_jsonld, for
  each dict node also expand node.get("@graph") when it is a list, reading @type
  from each member. Accept: parse_html('<script type="application/ld+json">
  {"@graph":[{"@type":"Article","headline":"h"}]}</script>')["jsonld_types"] ==
  ["Article"]; a top-level @type still works; scanner suite green.
  Done: _collect_jsonld now builds a node list of the top-level nodes plus each
  node's @graph members (when @graph is a list of dicts) and reads @type from all of
  them, so the wrapper shape {"@context":.., "@graph":[{...}]} is covered while
  top-level @type, a top-level list, and @type-as-list all still work. New test
  test_jsonld_graph_types_are_detected. Scanner 333 -> 334; README resynced to
  334/368 (guard exit 0); no builder change.
- [x] **P27 (done, M)** The same-site domain filter escapes to third-party
  registrants on unlisted multi-label public suffixes - a scope/authorization
  charter breach. common.registrable_domain (common.py:73-86) knows only 13
  multi-label suffixes (MULTI_SUFFIXES), so for any other multi-label suffix
  (com.sg, co.in, com.hk, co.kr, com.tr, co.id, com.tw, com.co, ...) it collapses
  the host to the suffix itself. Both crawler._eligible (crawler.py:54) and
  discover_pages (discover_pages.py:137) use registrable_domain as the same-site
  gate. Reproduced: registrable_domain("www.acme.com.sg") == "com.sg" ==
  registrable_domain("rivalbank.com.sg"), and _eligible("https://rivalbank.com.sg/
  login", "com.sg") == True. Consequence: on a target sitting on such a suffix,
  discover_pages (the default scoping helper) PROPOSES unrelated same-suffix
  registrants into proposed_review_set, and an opt-in --crawl FETCHES them -
  violating "only assess sites you own or are authorized to". .com.sg / .co.in etc.
  are major markets, so the trigger is realistic. Found by the P11-run replenishment
  partial audit (traversal scope). Fix: adopt a Public Suffix List for
  registrable_domain; minimal stopgap - expand MULTI_SUFFIXES to the common ccTLD
  second-levels AND require a candidate X.<2-letter-tld> host to share its last
  three labels with the target before admitting it as same-site. Accept:
  registrable_domain("rivalbank.com.sg") != registrable_domain("acme.com.sg") (or
  _eligible returns False for a different registrant on the same suffix); the
  existing .co.uk / .com cases still work; suites green.
  Done: added SECOND_LEVEL_LABELS ({com, co, org, net, gov, edu, ac, mil, gob, go,
  ne, or}) and treat a two-letter alpha ccTLD preceded by one of them as a
  multi-label public suffix, so registrable_domain returns the last three labels
  for com.sg / co.in / com.hk / gov.tw / com.co etc. Different registrants on such a
  suffix now differ, so _eligible/discover_pages reject a third party; a real
  subdomain of the same registrant stays same-site. Chose the pattern over a full
  Public Suffix List to keep the project stdlib-only; over-inclusion of a
  second-level label errs toward too-conservative same-site (a coverage miss),
  never a scope escape. New test
  test_registrable_domain_keeps_multilabel_cctld_registrants_apart; the existing
  .com/.co.uk cases still pass. Scanner 334 -> 335; README resynced to 335/369
  (guard exit 0); no builder change. Closes the last Medium.

- [x] **P32 (done, M)** Mixed `rank` types in recommendations crash the entire
  build. build_exec_report.py:963 sorts `data.get("recommendations", [])` by
  `key=lambda r: r.get("rank", 999)`; the default is the int 999, so if any
  recommendation carries a string rank ("1", "2" - a natural slip in the
  hand-distilled exec_report_data.json) while another is an int or omits rank, the
  comparison raises and the only deliverable dies. Reproduced (both in isolation and
  via a real build of the SAMPLE dict with recommendations=[{"rank":"2",...},
  {...no rank...}]): TypeError "'<' not supported between instances of 'int' and
  'str'". findings (integer SEVERITY_ORDER key) and action_plan (unsorted) are safe.
  Found by the P29-run replenishment partial audit (builder mechanics). Fix: coerce
  the sort key to numeric, non-numeric last (a (0, float(rank)) / (1, 0.0) tuple).
  Accept: build with recommendations ranked "10", 2, none, "1" succeeds and orders
  one, two, ten, none; suites green.
  Done: the recommendations sort now uses a _rank_key that returns (0, float(rank))
  or, on TypeError/ValueError (a non-numeric or missing rank), (1, 0.0), so numeric
  ranks order first and a string/absent rank sorts last without a str-vs-int
  comparison. New test test_mixed_rank_types_sort_numerically_without_crashing builds
  a doc with ranks "10"/2/none/"1" and reads back the table order (one, two, ten,
  none). Builder 34 -> 35, exec-report green; scanner 338 and report-charts 8
  unaffected; README resynced to 373 total (guard exit 0).
- [x] **P33 (done, M)** A UTF-8 BOM defeats TARGET.txt and .env reads, silently
  disabling target auto-resolution and the first credential. common.read_target_file
  (common.py:522) reads TARGET.txt with encoding="utf-8" and matches
  line.strip().lower().startswith("http"); '﻿'.isspace() is False, so a BOM
  survives strip() and the first line becomes '﻿https://...', failing the test.
  common.env_value (common.py:354) has the same defect: a BOM makes the first key
  '﻿SERPER_API_KEY=' fail startswith. Windows Notepad saves UTF-8 with a BOM by
  default and this project's platform is Windows, and TARGET.txt/.env are the
  documented, hand-edited primary inputs, so both silently fail. Reproduced: a
  b'\xef\xbb\xbf' prefix makes both reads miss the first line; encoding="utf-8-sig"
  fixes both. Found by the P29-run replenishment partial audit (common utilities).
  Fix: read both (and any other hand-edited text file) with encoding="utf-8-sig".
  Accept: TARGET.txt / .env with a leading BOM resolve their first line; a normal
  file still works; suites green.
  Done: read_target_file and env_value now read with encoding="utf-8-sig" (which
  strips a leading BOM and otherwise reads as utf-8; env_value keeps
  errors="replace"). New TestHandEditedFileReads: TARGET.txt and .env with a BOM
  resolve their first line, a normal file still works. The suite stubs env_value
  offline, so the test captures the real reader (_REAL_ENV_VALUE) before the stub.
  Scanner 338 -> 340; builder 35 and report-charts 8 unaffected; README resynced to
  340/375 (guard exit 0). Closes the last Medium.

- [x] **P38 (done, M)** add_key_dates_panel crashes the whole report on a non-string
  key-date label - a missed spot in the P35 non-string-scalar class.
  build_exec_report.py:607 calls item.get("label", "").upper() on the raw value,
  while the sibling value field on the next line is str()-guarded. A present-but-non-
  string label aborts the only deliverable. Reproduced: build with
  key_dates={"items":[{"label":None,"value":"2026-01-01"}]} -> AttributeError
  'NoneType' has no attribute 'upper' (also 123, a dict); a missing label is already
  safe (.get -> ""); "Cert expiry" builds fine. exec_report_data.json is hand-edited
  and "label": null is valid JSON, so the trigger is realistic. Found by the P35-run
  replenishment partial audit (builder rendering). Fix: str(item.get("label") or
  "").upper(), matching the value field's guard. Accept: the three non-string-label
  builds succeed; a normal label still renders; suites green.
  Done: the label now reads str(item.get("label") or "").upper(), matching the
  value field's str() guard; the sibling detail was already safe (it goes through
  the now-coercing add_run). Extended test_non_string_scalars_do_not_crash_the_build
  with key_dates label None/123. Verified a normal "Cert expiry" still renders as
  "CERT EXPIRY" in the panel table cell. Builder 37 (extended test), exec-report
  green; scanner 342 and report-charts 8 unaffected; guard exit 0.

- [x] **P40 (done, M)** cookie_consent false-PASSes on substring-matched consent
  markers, suppressing a real "trackers without consent" warning. scan_privacy
  _consent_detected (scan_privacy.py:301) tests each CONSENT_MARKERS entry as a raw
  substring of body.lower(); "truste" (scan_privacy.py:209) is a substring of the
  everyday words trusted / trustee / trustees, and "cookie-policy" (:208) matches a
  plain footer link href="/cookie-policy" - neither is a consent mechanism.
  Reproduced: _consent_detected("we are a trusted vendor") -> True, and a page with
  a Google Analytics script, no consent banner, and the copy "trusted by thousands"
  grades cookie_consent pass (should be warn), inflating the privacy band from 0.5
  to 1.0. The substring-on-structured-data class (like SPF -all / robots content=none
  / CSP directive) applied to consent detection. Found by the P36-run replenishment
  partial audit (scanner grading decisions). Fix: drop the bare "truste" marker
  (truste.com/trustarc.com are already in the CMP_HOSTS list) and drop "cookie-policy"
  (a policy-page link is not a consent mechanism); the remaining hyphenated/brand
  markers do not collide with prose. Accept: _consent_detected("a trusted vendor")
  and _consent_detected('<a href="/cookie-policy">') return False; a page with a real
  cookie-consent/onetrust marker still detects True; the GA + trusted + no-CMP page
  grades cookie_consent warn; scanner suite green.
  Done: dropped "truste" and "cookie-policy" from CONSENT_MARKERS (16 -> 14 markers;
  TrustArc still detected via trustarc.com in CMP_HOSTS) and documented that every
  remaining marker must be specific enough not to collide with prose. Verified
  "trusted"/"trustee"/a cookie-policy link no longer detect, while a cookie-consent
  class, onetrust, trustarc.com host, usercentrics, and cmplz still do. New test
  test_consent_markers_do_not_substring_match_prose. Scanner 343 -> 344; README
  resynced to 344/381 (guard exit 0; CMP_HOSTS count unchanged at 20); no builder
  change.

- [x] **P44 (done, M)** Multiple SPF records grade pass, missing a permerror that
  makes SPF non-functional. scan_dns_email.check_spf (scan_dns_email.py:50) selects
  the first `v=spf1` record and grades only it, never counting them. Per RFC 7208
  sec 3.2/4.5 a domain publishing more than one v=spf1 TXT record MUST yield
  permerror - receivers ignore SPF and DMARC-via-SPF alignment breaks. Reproduced:
  records ["v=spf1 include:_spf.google.com -all", "v=spf1 include:mailgun.org ~all"]
  -> verdict pass (should fail). Two SPF records is a classic slip (a vendor include
  added as a second record). Found by the P41-run replenishment partial audit
  (scanner grading decisions). Fix: if more than one record starts with v=spf1,
  return fail "Multiple SPF records (permerror; receivers ignore SPF)". Accept: two
  v=spf1 records yield verdict != pass; a single record stays pass; scanner suite
  green.
  Done: check_spf now counts v=spf1 records after confirming one is present, and
  returns fail "Multiple SPF records published: a permerror..." when more than one
  exists; a single record (even with unrelated TXT records alongside) still grades
  by its all-mechanism. New test test_multiple_spf_records_are_a_permerror. Scanner
  346 -> 347; README resynced to 347/384 (guard exit 0); no builder change.
- [x] **P45 (done, M)** Referrer-Policy: no-referrer-when-downgrade grades pass, but
  it leaks full URLs (path+query) to every cross-origin HTTPS destination.
  scan_http_security.check_referrer_policy (scan_http_security.py:98-101) flags only
  unsafe-url; every other value passes. Per the W3C Referrer Policy spec / MDN,
  no-referrer-when-downgrade sends the full URL on same-or-more-secure requests -
  the same leak the check already warns about for unsafe-url, and the reason the web
  default moved to strict-origin-when-cross-origin. Reproduced:
  no-referrer-when-downgrade -> pass; strict-origin-when-cross-origin -> pass;
  unsafe-url -> warn. Found by the P41-run replenishment partial audit. Fix: also
  warn when the effective (last) token is no-referrer-when-downgrade, with the same
  full-URL-leak note. Accept: no-referrer-when-downgrade -> warn; strict-origin-
  when-cross-origin / origin-when-cross-origin / same-origin stay pass; suite green.
  Done: check_referrer_policy now grades the effective (last) token of the
  comma-separated fallback list, warning when it is unsafe-url OR
  no-referrer-when-downgrade (both leak full URLs cross-origin); the modern
  origin-based policies pass. Also fixes a latent substring quirk (unsafe-url as a
  non-last fallback token no longer false-warns). Extended test_matrix with the
  no-referrer-when-downgrade / origin-based / fallback-list cases. Scanner 347
  (extended test); README total 384 unchanged (guard exit 0); no builder change.
- [x] **P46 (done, M)** The canonical check passed on any value, so a cross-host
  canonical (a page de-indexing itself) graded clean. scan_seo canonical check
  (scan_seo.py:117-119) was `pass if parsed["canonical"] else info` and never compared
  the href to the page URL, though base = res["final_url"] is in scope. A canonical
  pointing to a different host, or pointing every page at the homepage, tells Google
  to drop this page in favor of the target - a damaging misconfiguration. Reproduced
  against https://example.com/products/widget: canonical https://evil-other.com/ ->
  pass "Canonical set."; a self canonical -> pass. Found by the P41-run replenishment
  partial audit. Fix: resolve the href against base; if its registrable host differs
  from the page host, fail ("canonical points off-host"). Accept: a cross-host
  canonical yields fail; a self/same-host canonical stays pass; scanner suite green.
  Done: extracted _canonical_check(canonical, base) in scan_seo.py - it resolves the
  href against base with urljoin, then compares registrable_domain(host_of(resolved))
  to registrable_domain(host_of(base)); a different registrable domain fails ("points
  off-host to <host>; tells search engines to index that domain instead"), while a
  self, apex-vs-www, subdomain, or relative canonical stays pass and an absent one is
  info. Same registrable-domain same-site model the crawler/discovery already share,
  so www/subdomain variants are not false-failed. New test test_canonical_check
  (cross-host + protocol-relative off-host -> fail; self/www/subdomain/relative ->
  pass; none -> info). Scanner 347 -> 348; README resynced to 348/385 (guard exit 0);
  no builder change. Closes the last Medium of the P41-run replenishment.

#### Replenishment from the P48-run partial audit (2026-07-05, orchestration + report layer)
The Low tail dropped the open count below three, so a partial audit targeted the
least-recently-scored dimensions (the P41 run swept scanner grading logic): the
orchestration/scope tools (run_review, discover_pages, crawler) and the report/trend
builder (trends, report_charts, draft_report_data). A general-purpose auditor swept
them read-only; I reproduced each finding myself before filing. crawler.py, trends.py,
report_charts.py, and run_review.py had no reproducible defect. Two Medium found.
- [x] **P51 (done, S)** discover_pages fetches off-domain hosts named by the target's
  own robots.txt / sitemap index, with no same-domain guard - a scope-boundary gap
  (the default scoping helper contacts hosts the operator never named). discover_pages
  _collect_sitemap_urls (discover_pages.py:57 and :65) fetches the robots.txt Sitemap:
  URL and every <loc> inside a <sitemapindex> via common.http_fetch with no eligibility
  check, while the sibling _internal_nav_links (:84) already drops any absolute URL
  whose registrable_domain != the target domain. Reproduced: with a stubbed http_fetch,
  a target on target.example whose robots.txt advertises
  Sitemap: https://attacker-controlled.test/sitemap.xml (a <sitemapindex> pointing at
  https://third-party.test/child.xml) makes the tool fetch BOTH off-domain hosts
  (sitemaps_read lists them). Same scope-filter class as P27 (rated Medium); this one
  is on the default path and fetches immediately, and the sitemap URL is
  attacker-influenceable (an SSRF-flavored angle: a hostile target could name an
  internal address), though the response body is only parsed for <loc> and never
  reflected. Found by the P48-run replenishment partial audit. Fix: before fetching
  start and each child, skip any URL whose registrable_domain(host_of(url)) != the
  target's registrable domain (reuse the crawler's _eligible model); the charter's
  "a coverage miss is acceptable, a scope escape is not" governs the cross-CDN-sitemap
  tradeoff. Accept: a test with a stubbed http_fetch and an off-domain robots Sitemap
  asserts the tool fetches no host other than the target's registrable domain; a
  same-domain (incl. www/subdomain) sitemap is still fetched; suites green.
  Done: _collect_sitemap_urls now takes the target domain and fetches only same-
  registrable-domain sitemaps via a shared _same_site(url, domain) helper - it filters
  the robots.txt Sitemap: candidates to on-domain ones (falling back to the
  conventional same-domain /sitemap.xml when none is on-domain, so an off-domain
  advertised sitemap degrades to a coverage miss, not a scope escape) and skips any
  off-domain sitemapindex <loc> child. _internal_nav_links now reuses the same helper
  (DRY). New test test_sitemap_collection_never_fetches_off_domain (off-domain robots
  Sitemap + a third-party child -> zero off-domain fetches; the www child on the same
  registrable domain is still read). Scanner 352 -> 353; README resynced to 353/390
  (guard exit 0); no builder change.
- [x] **P52 (done, S)** The CEO report claims "Core Web Vitals all in the Good range"
  from a lab capture (whose third metric is TBT, not a Core Web Vital) and even from a
  single partial metric - a misleading claim in the deliverable. draft_report_data
  _assessment (draft_report_data.py:165-166) inserts that strength whenever every
  measured vitals metric rates Good, but the lab branch of _web_vitals (:240-247)
  measures LCP, CLS, and TBT (TBT is a lab proxy; the interactivity CWV is INP, never
  in lab), and _vitals_metrics (:218-226) includes only measured metrics, so a partial
  set (e.g. LCP alone) satisfies all(). Reproduced: a scan with a lab vitals capture
  LCP/CLS/TBT all Good -> strengths == ["Core Web Vitals all in the Good range"]; a
  scan with only field_lcp/lcp measured and Good -> same string. Secondary effect:
  bottom_line derives the "strongest area" from strengths[0], emitting the overstated
  phrase. Medium: an SEO/ranking-weighted claim in the CEO report asserting a
  real-user CWV pass on evidence that did not measure all three CWV. Found by the
  P48-run replenishment partial audit. Fix: insert the CWV strength only when
  source == "field" and all three of LCP, CLS, INP are present and Good; for a lab
  capture, phrase it as lab performance metrics, not Core Web Vitals. Accept: a lab
  all-Good scan and a partial-field all-Good scan do NOT yield the "Core Web Vitals all
  in the Good range" strength; a field capture with all three Good still does; suites
  green.
  Done: _web_vitals now returns a complete flag (len(metrics) == 3, so all expected
  metrics for the source were measured), keeping the "what is the full set" knowledge
  where the specs live. _assessment inserts the strength only when complete AND all
  metrics rate Good, and phrases it by source: "Core Web Vitals all in the Good range"
  for a field (CrUX) capture, "Lab performance metrics all in the Good range" for a lab
  capture (whose TBT is not a CWV). A partial field capture (e.g. LCP only) is not
  complete, so it makes no all-Good claim. New test
  test_cwv_strength_requires_a_complete_field_capture (field all-3 -> CWV string;
  partial field -> no claim; lab all-Good -> lab phrasing, not CWV). Scanner 353 -> 354;
  builder 37 green (consumes the web_vitals dict with the new key); README resynced to
  354/391 (guard exit 0). Note: bottom_line's "strongest area" reads slightly awkwardly
  for the field case but is no longer false and sits in explicitly-DRAFT text, so not
  filed.

#### Replenishment from the P52-run partial audit (2026-07-05, parser + builder + capture)
The Low tail dropped the open count below three, so a partial audit targeted the
least-recently-scored surfaces: the HTML parser (htmlmeta), the docx builder
(build_exec_report), and the rendered-capture tier (capture_rendered, scan_vitals). A
general-purpose auditor swept them read-only; I reproduced every finding myself before
filing. scan_vitals had no reproducible defect. Two Medium and one Low found (the Low,
P55, is in the Later section).
- [x] **P53 (done, M)** An unclosed <title> makes the parser swallow the rest of the
  document, so every heading/anchor/image/landmark after it is dropped and the false
  "no H1 / no links / no images" verdicts ship as MEASURED facts. Python 3.13 parses
  <title> as RCDATA, so a missing </title> sends the remaining markup into title text;
  handle_starttag never fires for the following tags. htmlmeta.py: the title fallback
  (~:298-303) recovers the title string but not the lost body, and render_assessment
  sees a word-heavy page as sparse=False, so it does NOT mark the page inconclusive -
  defeating the very safeguard meant to stop an unread body being reported clean.
  Reproduced: the same body with a closed title -> headings=1 anchors=1 images=1; with
  an unclosed <title> -> headings=0 anchors=0 images=0, client_rendered=False (shipped
  as measured). Medium: malformed-but-real input (a truncated response, a broken
  template concat, a CMS bug) yields confidently-wrong findings across the SEO and
  accessibility scanners, on HTML the operator does not control. Found by the P52-run
  replenishment partial audit. Fix: detect the unterminated-RCDATA case (title started
  and never closed at parse end) and reparse the body, or re-feed the swallowed
  remainder, so structural extraction is not lost; alternatively mark the page
  inconclusive when the title consumed the body. Accept: a page with a real body and an
  unclosed <title> yields the same headings/anchors/images as the closed-title version
  (or is marked inconclusive), not a false zero graded as measured; the closed-title
  case is unchanged; suites green.
  Done: parse_html now detects the unclosed-title case (title None with a non-empty
  RCDATA _title_buf), recovers the real title as the text before the first "<", then
  reparses the swallowed markup (from that "<" onward) with a fresh _Extractor and folds
  it in via a new _merge_extractors helper. The merge extends the structural lists
  (metas/links/anchors/headings/images/form_controls/roles/jsonld_types) and unions the
  sets (labels_for/landmarks/ids) and counters; it leaves word_count to the first parse
  (which already counted the swallowed text as RCDATA data, so adding the reparse would
  double it) - the body was never interpreted in the first parse, so the collections
  combine without overlap. New test test_unclosed_title_does_not_swallow_the_body (a
  closed and an unclosed title yield identical title/lang/headings/anchors/images/
  landmarks/jsonld; a title unclosed at EOF still works). Verified the closed-title,
  empty-title, and no-title cases are unchanged. Scanner 354 -> 355; builder 37 green;
  README resynced to 355/392 (guard exit 0).
- [x] **P54 (done, S)** Two remaining non-string scalar spots crash the whole build
  (the sole deliverable) on a hand-edited exec_report_data.json - the P35 class, two
  sites the coercion sweep missed. (a) build_exec_report.py:923: a scorecard row with a
  numeric score feeds detail straight into re.sub(...) with no str() -> "TypeError:
  expected string or bytes-like object, got 'int'" when detail is non-string. (b)
  build_exec_report.py:301: (data.get("report_label") or "EXECUTIVE REPORT").upper()
  calls .upper() on the raw value -> "AttributeError 'int' object has no attribute
  'upper'" for a numeric/boolean report_label. Reproduced both against the real build():
  detail=2024 and report_label=2024 each abort before the docx is written. Sibling
  paths (:514, :607) already str()-wrap. Medium: a crash kills the only deliverable,
  though both triggers require a hand-edit. Found by the P52-run replenishment partial
  audit. Fix: coerce both - str(row.get("detail", "")) before the regex, and
  (str(data.get("report_label") or "") or "EXECUTIVE REPORT").upper(). Accept: a build
  with a numeric scorecard detail and a numeric report_label both succeed (no crash); a
  normal string detail/label still renders; builder suite green.
  Done: coerced both spots with the codebase str(... or "") idiom - detail = str(row.get
  ("detail") or "") at the assignment (so both the re.sub and the cell-render paths get
  a string), and label = (str(data.get("report_label") or "") or "EXECUTIVE REPORT")
  .upper(). Verified both crash inputs now build, a string report_label still uppercases
  to the gold badge, and a detail's "(score N)" suffix is still stripped. Extended
  test_non_string_scalars_do_not_crash_the_build with the numeric detail and numeric
  report_label cases. Builder 37 (extended an existing test, count unchanged), exec-
  report green; scanner 355 and README total 392 unaffected (guard exit 0). This closes
  the last member of the P35 non-string-scalar-crashes-the-builder class found so far,
  and the last Medium of the P52-run replenishment.

#### Replenishment from the P49-run partial audit (2026-07-05, network core + remaining scanners)
The Low tail dropped the open count below three, so a partial audit targeted the
least-recently-swept surfaces: the shared network/parse core (common) and the scanners
the P41 grading sweep did not deeply cover (scan_tls, scan_accessibility, scan_links,
scan_design, scan_readability). A general-purpose auditor swept them read-only; I
reproduced every finding myself before filing. common and scan_readability were clean.
Four Medium and one Low found - four are the presence-not-value / raw-text-match class
in files the earlier sweep never reached. The Low (P60) is in the Later section.
- [x] **P56 (done, S)** The mixed-content scan fabricates an active-mixed-content
  security FAIL on commented-out markup - a vulnerability that does not exist, graded,
  in the CEO report. scan_links._mixed_content runs MIXED_RE.findall over the raw
  response body (scan_links.py:38-40, ~:116), so an http:// script/iframe reference
  inside an HTML comment (never fetched by any browser) is reported as active mixed
  content and graded fail. Reproduced: _mixed_content('<!-- legacy: <script
  src="http://legacy.example/x.js"></script> -->', is_https=True) -> verdict fail, 1
  active item. Commenting out legacy tracker/script tags is common. Medium: fabricates a
  graded security vulnerability, a direct charter violation ("do not fabricate
  vulnerabilities; never report an unmeasured thing as fail"). Found by the P49-run
  replenishment partial audit. Fix: strip HTML comments (and ideally <template> and
  <noscript> bodies) from the html before matching, or match on parsed elements. Accept:
  an http script/iframe only inside an HTML comment on an https page -> mixed_content
  pass (not fail); a real uncommented http script still fails; suite green.
  Done: _mixed_content now strips HTML comments (via a new _strip_comments helper)
  before running MIXED_RE and the <link> scan, so a resource referenced only inside
  <!-- ... --> is not counted. _strip_comments is a LINEAR string scan (find "<!--" then
  "-->"), deliberately NOT a lazy <!--.*?--> regex - I measured that regex at 37s on 50k
  unclosed "<!--" (a ReDoS, the N6 class). Scoped to comments (the reproduced case);
  left <template>/<noscript> alone (rarer and more arguable, especially noscript which a
  no-JS user does render) to avoid over-reach. New test
  test_mixed_content_ignores_commented_out_markup (commented http script -> pass; a
  comment does not hide a real script after it -> fail; 20k unclosed "<!--" stays under
  1s). Scanner 355 -> 356; README resynced to 356/393 (guard exit 0); no builder change.
- [x] **P57 (done, S)** A dangling aria-labelledby (or aria-describedby / label[for])
  reference counts as a real accessible name, so an effectively-unlabeled control grades
  "all controls labeled". scan_accessibility._accessible_name (scan_accessibility.py:31)
  returns "aria-labelledby" whenever the attribute is present and never checks the
  referenced id exists (the parsed ids set is passed in but unused for this branch).
  Reproduced: _accessible_name({'aria_labelledby':'ghost', ...}, set()) -> "aria-
  labelledby" though no id="ghost" exists, so form_labels grades pass "All form controls
  have a programmatic label". Realistic (id typos, dynamically generated ids). Medium:
  assistive tech gets no name, yet the report says every control is labeled - presence-
  not-value. Found by the P49-run replenishment partial audit. Fix: for aria-labelledby
  / aria-describedby verify each referenced token is in parsed["ids"], and for label[for]
  that the id is targeted, before crediting the name. Accept: a control whose
  aria-labelledby points at a non-existent id is NOT counted as labeled (form_labels not
  pass); a control pointing at a real id still passes; suite green.
  Done: _accessible_name now takes the page ids set and credits aria-labelledby only
  when at least one referenced id (it is a space-separated id list) exists on the page;
  a dangling reference falls through to the next name source (title/alt) or None. Scoped
  to aria-labelledby, the only reference-based name source here: aria-label is a literal
  string (valid as-is), label[for] was already validated (line 29 checks the control's
  id is in labels_for), and aria-describedby is a description, not a name, so
  _accessible_name never used it. _form_check passes set(parsed["ids"]). Updated
  test_accessible_name (new 3rd arg + valid/dangling/title-fallback cases) and
  test_form_check (added the ids key to the hand-built fixtures + a dangling-then-
  resolved end-to-end case). Scanner 356 (extended tests, count unchanged); README total
  393 unaffected (guard exit 0); no builder change.
- [x] **P58 (done, S)** The image-dimension (layout-shift) check accepts any "width"
  substring in a style attribute, so responsive images that reserve no vertical space get
  a false "declares dimensions" pass. scan_design.check_image_dimensions via STYLE_DIM_RE
  (scan_design.py:43, ~:171) treats a style containing the substring width - including
  max-width or a bare width:100% with no height - as declaring dimensions. Reproduced:
  three <img style="max-width:100%"> -> verdict pass, missing_dimensions 0; width:100%
  (no height) -> also pass. max-width:100%/height:auto responsive images are ubiquitous
  and cause CLS, so the check reports a clean bill on the exact pattern it exists to
  catch. Substring-on-structured-data. Medium: a wrong layout-shift verdict in the
  report. Found by the P49-run replenishment partial audit. Fix: parse the inline style
  declarations and require BOTH a width (or aspect-ratio) and a height, excluding
  max-width/min-width. Accept: <img style="max-width:100%"> counts as missing dimensions
  (warn if most images are like that); <img style="width:800px;height:600px"> and a
  width/height attribute pair still pass; suite green.
  Done: replaced the substring-matching STYLE_DIM_RE with STYLE_ATTR_RE (captures the
  style value) plus a _style_reserves_space helper that parses the declarations by
  property NAME and reserves space only on aspect-ratio, or an explicit width AND height
  - so max-width/min-width (distinct property names) and a bare percentage width no
  longer count. The width/height HTML-attribute branch is unchanged. New test
  test_style_dimensions_grade_properties_not_a_width_substring (max-width:100% /
  min-width / width:100% / height:auto -> warn; width+height / aspect-ratio /
  aspect-ratio+width -> pass). Scanner 356 -> 357; README resynced to 357/394 (guard exit
  0); no builder change.
- [x] **P59 (done, S)** Any CAA record grades "pass: CAA restricts certificate
  issuance", even a record that restricts nothing. scan_tls.check_caa (scan_tls.py:93-96)
  grades pass on the presence of any CAA answer; a record carrying only an iodef property
  (an incident-reporting contact, no issue/issuewild) does not restrict issuance, yet is
  reported as restricting it. Reproduced (stubbed doh_query): a single record
  '0 iodef "mailto:sec@example.com"' -> verdict pass, note "CAA restricts certificate
  issuance". Medium: a misleading security-posture claim - a domain with an iodef-only
  CAA still lets any public CA issue, but the report says issuance is restricted.
  Presence-not-value on structured DNS. Found by the P49-run replenishment partial audit.
  Fix: parse each record's property tag and grade pass only when an issue/issuewild
  property is present; treat iodef-only as info (any CA may still issue). Accept: an
  iodef-only CAA -> info (not pass); a record with issue "letsencrypt.org" -> pass; no
  CAA -> info as now; suite green.
  Done: added _restricts_issuance(record) - it reads the tag (second token of the
  "<flags> <tag> <value>" presentation format) and returns True only for issue/issuewild.
  check_caa now grades pass only when at least one record restricts issuance (and the
  note lists only the restricting records); a CAA set with no issue/issuewild (iodef- or
  contactemail-only) grades info "present but no issue/issuewild, any public CA may still
  issue"; no CAA stays info. New test test_caa_iodef_only_does_not_restrict_issuance
  (iodef-only -> info; iodef+issue -> pass naming the issue record); the existing
  issue-record pass and absent/lookup-failure info tests still hold. Scanner 357 -> 358;
  README resynced to 358/395 (guard exit 0); no builder change. Closes the last Medium of
  the P49-run replenishment.

#### Replenishment from the P50-run partial audit (2026-07-05, docs + tests + orchestration)
The Low tail dropped the open count below three, so a partial audit targeted the
least-recently-scored DIMENSIONS (the prior four rounds swept the code): documentation
accuracy (SKILL.md, README, CAPTURE.md, CLAUDE.md vs code), test-suite integrity, and
the aggregator/CLI orchestration (scan_site, run_review, check_readme_counts). A
general-purpose auditor swept them read-only; I reproduced every finding myself. The
orchestration layer and the doc counts/defaults were clean (359+37+8 tests, 14 scanners,
10 categories, all counts match). One Medium and two Low found (the Low, P62/P63, are in
the Later section).
- [x] **P61 (done, S)** test_exec_report errors instead of skipping when python-docx is
  absent, contradicting its own docstring ("Skipped entirely when python-docx is not
  installed", test_exec_report.py:8). TestBuildMainInputGuard (test_exec_report.py:497)
  lacks the @unittest.skipUnless(HAVE_DOCX, ...) decorator its three sibling classes
  carry, and its 5 tests reference ber, which is bound only under `if HAVE_DOCX:` (:31),
  so without docx they raise NameError: name 'ber' is not defined. Reproduced (docx
  import blocked): loadTestsFromName("test_exec_report.TestBuildMainInputGuard") ->
  errors 5, skipped 0, first error "NameError: name 'ber' is not defined"; every
  guarded class skips correctly. Masked in CI (ci.yml installs requirements first), so it
  only bites a contributor working on the stdlib scanners without the optional builder
  dep. Medium: misleading documentation plus a broken skip path that turns a clean skip
  into a FAILED run. Found by the P50-run replenishment partial audit. Fix: decorate
  TestBuildMainInputGuard with @unittest.skipUnless(HAVE_DOCX, "python-docx not
  installed") like its siblings. Accept: with docx import blocked, that class's tests
  SKIP (not error); with docx present they still run and pass; builder suite green.
  Done: decorated TestBuildMainInputGuard with @unittest.skipUnless(HAVE_DOCX,
  "python-docx not installed"), matching TestExecReport/TestTrendSection/TestReportLabel.
  Verified with the docx import blocked: the class's 5 tests SKIP (errors 0, skipped 5),
  no NameError; with docx present the full builder suite runs and passes (37). The
  docstring's "Skipped entirely" is now true for the build tests (TestBuilderDependencies
  is intentionally dep-independent - it reads requirements.txt to assert the deps are
  declared, so it must run regardless). Builder 37 (decorator, no count change); scanner
  359 and README total 396 unaffected (guard exit 0).

#### Replenishment from the P60-run partial audit (2026-07-05, scorecard + trend numeric core)
The Low tail dropped the open count below three, so a partial audit targeted the
cross-cutting NUMERIC/aggregation logic - the scorecard rollup (common.grade,
scan_site.build_scorecard), the band thresholds, and the trend/delta math (trends,
diff_issues) - where a wrong number becomes a wrong deliverable. A general-purpose
auditor swept it read-only; I reproduced every finding myself. The medians (even/odd/
empty), quarter bucketing and order-independence, the grouped multi-page diff identity,
and every guarded division were sound. Two Medium and one Low found (the Low, P66, is in
the Later section).
- [x] **P64 (done, S)** A crashed scanner leaves the overall posture "Strong / 1.0" and
  the crash is dropped from the CEO deliverable entirely - a clean headline for a site
  whose whole category went unmeasured. build_scorecard (scan_site.py:212-217) forces the
  errored CATEGORY to Not measured (P7) but grades the OVERALL band purely from the
  surviving categories' verdicts and only bolts on an errors key (:216) without
  downgrading or caveating it; draft_report_data.draft (draft_report_data.py:_scorecard/
  bottom_line) then drops scanner_errors and both the per-category and overall errors keys,
  so the exec-report data has no trace of which scanner crashed. Reproduced: with the
  tls-category scanner ok=False (no verdicts) and every other host tool passing,
  build_scorecard overall band=Strong score=1.0 errors=['scan_tls'], tls category Not
  measured; draft() -> report overall "Strong", crashed tool name absent, no errors key.
  A single-scanner crash is realistic (a DoH/CrUX timeout, a malformed cert crashing TLS
  parse). Medium: a Strong CEO headline for an unmeasured category, with the reason
  suppressed - the charter's "never report an unmeasured thing as clean" at the overall
  level. Found by the P60-run replenishment partial audit. Fix: propagate
  overall.errors / scanner_errors into the report data (a visible caveat) and caveat the
  overall headline when a category errored, mirroring the per-category Not measured
  treatment. Accept: with a crashed scanner, the exec-report data names the errored
  scanner (or carries a scanner-error caveat) and the overall headline is not an
  uncaveated Strong; the no-crash path is unchanged; suites green.
  Done: fixed in the data layer (draft_report_data), which the builder already renders.
  _scorecard now carries scan["scanner_errors"] into the report data as
  scorecard.scanner_errors (naming each errored tool/scope/error), and bottom_line - the
  executive callout the builder already renders verbatim - gains a caveat clause when any
  scanner errored: "N scanner(s) could not measure their category (<tools>), so this
  posture covers only the measured categories". So the CEO headline is no longer an
  uncaveated Strong and the crash is named, without a new builder element (the per-
  category Not-measured row from P7 already shows in the table). New test
  test_scanner_crash_is_surfaced_and_caveats_the_headline (crash -> scorecard.scanner_errors
  names scan_tls and bottom_line caveated; base SCAN -> empty errors, no caveat). Scanner
  361 -> 362; builder 37 green (the new key is inert to the builder); README resynced to
  362/399 (guard exit 0).
- [x] **P65 (done, S)** A defect that worsens warn->fail is counted as BOTH 1 resolved and
  1 new, and named as "resolved" in the CEO progress section though it got worse.
  scan_site.diff_issues (scan_site.py:123) keys the grouped identity on
  (scan_label, check, verdict) - verdict is part of the key - so the same scanner+check
  changing warn->fail yields two distinct keys: the fail is "new" and the warn is
  "resolved". Reproduced: prev warn / curr fail for a11y:contrast -> new
  [('contrast','fail')], resolved [('contrast','warn')]; trends.build_trend then lists the
  contrast defect by name as resolved (a false improvement claim) while also counting it
  new. A defect degrading across quarters is common; the trend section (2+ quarters) makes
  a concrete wrong claim. Medium. Found by the P60-run replenishment partial audit. Fix:
  key diff_issues on (scan_label, check) only and treat a verdict change as a persistence
  (or a distinct "worsened"/"improved" bucket), not a resolved+new pair. Accept: a defect
  changing warn->fail is neither counted as resolved nor listed as a resolved finding (it
  persists, optionally flagged worsened); a genuinely gone defect is still resolved and a
  genuinely new one still new; suites green.
  Done: diff_issues now keys the grouped identity on (scan_label, check) only - the
  verdict is deliberately dropped from the key, so a defect that worsens (warn->fail) or
  eases (fail->warn) is the same persistent defect and is neither new nor resolved.
  Chose the minimal key change over adding a "worsened" bucket (KISS); the docstring now
  states why the verdict is excluded. New test
  test_diff_issues_treats_a_verdict_change_as_persistence (warn->fail and fail->warn ->
  0 new / 0 resolved; a genuinely gone defect -> 0/1; a genuinely new one -> 1/0). The
  existing new/resolved and defects-not-pages diff tests still pass (they key on distinct
  checks). Scanner 362 -> 363; README resynced to 363/400 (guard exit 0); no builder
  change. Closes the last Medium of the P60-run replenishment.

### Later (Low)
- [x] **P5 (done, S)** Own-fetch checks that grade off a failed/partial probe
  (the P1 class, lower impact). Three same-class instances, all where the fetch
  did not complete (not res["ok"]) but final_status is a recorded redirect code
  (not None), so the is-None info guard is skipped and a warn is emitted for an
  I/O failure that could not be measured:
  (a) scan_crawl.check_robots_txt (:54-68) - warn "No usable robots.txt";
  (b) scan_crawl.check_sitemap (:71-82) - the sitemap warn;
  (c) scan_design.check_favicon (scan_design.py:69) - warn "No favicon: ...
      absent" though the favicon may exist behind the failed redirect.
  Reproduced for robots (a 301 whose target fails at connect -> warn). Low:
  warns, not fails, and a well-known path behind a failing redirect is rare.
  Found by the P4-run own-fetch sweep (scan_links is already correct: a
  connection failure classifies as "unreachable", not "broken"; security_txt and
  mta_sts already degrade to info). Fix: in each, when not res["ok"] return info,
  not warn. Accept: a test with an ok=False fetch whose last hop is a 301 asserts
  info (not warn) for robots and favicon; a real 404 still warns as before;
  scanner suite green.
  Done: all three guards changed from `final_status is None` to `not res["ok"]`
  in scan_crawl.py (:51 robots, :74 sitemap) and scan_design.py (:66 favicon).
  test_partial_redirect_failure_is_info_not_warn (TestCrawl) and
  test_favicon_partial_redirect_failure_is_info (TestDesign) pin info for the
  ok=False+301 shape and warn for a real 404. Scanner suite 313 tests green.
- [x] **P6 (done, S)** The RDAP, CrUX, and DoH JSON reads have no byte cap.
  common.py: _http_get_json (RDAP), http_post_json (CrUX), and doh_query all do
  resp.read()/json.load(urlopen(...)) with a timeout but no size limit, unlike
  http_fetch's MAX_BODY_BYTES. Lower risk than P4 because these hit trusted
  first-party endpoints (IANA bootstrap, Google DNS/CrUX) selected by TLD or
  fixed host, not by the target's own server, but a misbehaving endpoint could
  still send an oversized body. Fix: read at most a fixed cap before json.loads.
  Accept: each of the three reads at most a bounded number of bytes; a normal
  response still parses; scanner suite green.
  Done: added MAX_JSON_BYTES = 5 MB and a shared _read_json_capped(resp) that does
  resp.read(MAX_JSON_BYTES) before json.loads. All three readers funnel through it
  (_http_get_json, http_post_json incl. its HTTPError-detail branch, and doh_query,
  which also moved to a `with urlopen(...)` block, closing a latent socket leak
  from passing urlopen straight to json.load). An oversized body truncates and
  fails to parse, which every caller already handles. New TestCappedJsonRead:
  normal body parses with read capped to MAX_JSON_BYTES; a tiny-cap oversized body
  pulls only the cap and raises; doh_query wired through the cap (stubbed urlopen).
  Scanner 315 -> 318; exec-report 32 and report-charts 8 unchanged; README resynced
  to 318/350 (guard exit 0).
- [x] **P8 (done, S)** scan_crux.py module docstring names the wrong API key.
  Line 8 says "Needs a GOOGLE_API_KEY (environment or repo-root .env)", but the
  code prefers CRUX_API_KEY: scan_crux.py:65 reads
  `common.env_value("CRUX_API_KEY") or common.env_value("GOOGLE_API_KEY")` and the
  user-facing note (line 68) already says "no CRUX_API_KEY or GOOGLE_API_KEY".
  README.md:85 and SKILL.md:41 document both keys; only this docstring omits the
  preferred one, so a reader who trusts it sets the fallback key. Found by the
  P5-run replenishment partial audit (documentation dimension). Fix: reword the
  docstring to "Needs a CRUX_API_KEY or GOOGLE_API_KEY". Accept:
  `grep CRUX_API_KEY scan_crux.py` matches inside the module docstring.
  Done: the docstring now reads "Needs a CRUX_API_KEY or GOOGLE_API_KEY
  (environment or repo-root .env; the dedicated CRUX_API_KEY wins when both are
  set)", matching the line-65 preference and the line-68 note. Verified via
  scan_crux.__doc__: both keys present, CRUX first. Compile clean, crux tests
  green; docstring-only, so counts unchanged (guard exit 0).
- [x] **P9 (done, S)** The "charts from three quarters" wording undersells the
  trend charts. README.md:98, SKILL.md:100, and CLAUDE.md:30 all say the trend
  section shows "charts from three quarters", but trends.build_trend (trends.py:135)
  returns every quarter in the ledger, build_exec_report.py:469 only gates chart
  rendering at `>= 3` quarters, and report_charts.render_trend_charts plots the
  whole list uncapped - so a site with 4+ quarters renders 4+ quarters, not three.
  "Three quarters" describes the minimum-to-appear threshold, not the rendered
  window. Found by the P5-run replenishment partial audit (documentation dimension).
  Fix: reword to "charts appear once three quarters of history exist" (all three
  docs), or slice quarters[-3:] if a fixed three-quarter window is actually
  intended. Accept: the three docs no longer imply a fixed three-quarter window
  (they say "three or more" / "once three quarters exist"), or build_trend caps to
  the last three quarters with a test asserting <= 3 plotted; suites green.
  Done: chose the doc reword (the code's own comments at build_exec_report.py:21
  and :451 already say "three or more quarters of history", so showing all quarters
  once three exist is the intended design, not a bug to cap). SKILL.md:100 and
  CLAUDE.md:30 now read "charts added once three or more quarters of history exist
  and then plot every quarter in the ledger". Correction to the filed finding: the
  README.md:98 citation was stale - README does not contain the "three quarters"
  phrase (its trend mention is the digest's "last five runs", which is accurate),
  so it needed no edit and none was fabricated. Verified: the old phrasing is gone,
  the new wording is present, both edited lines are dash-free. Docs-only, no code/
  test/count change.
- [x] **P11 (done, S)** The report/capture CLI entry points give a raw traceback
  on a structurally wrong input JSON, unlike the scan layer. build_exec_report.main
  (build_exec_report.py:1057) json.loads the data file and hands it straight to
  build() (build_exec_report.py:821), which calls data.get(...) immediately.
  Reproduced: build_exec_report.build([], "x.docx") -> AttributeError: 'list'
  object has no attribute 'get'. exec_report_data.json is partly hand-authored (per
  CLAUDE.md the human distills findings and writes recommendations/quick_wins), so a
  top-level structural slip (wrapping the object in [], say) yields a raw traceback
  instead of a clear message. Same shape in draft_report_data.main
  (draft_report_data.py:408) and capture_rendered.main (capture_rendered.py:636),
  which consume tool-generated files. The scan layer already guards this class
  (read_history/attach_delta), so this is a consistency gap, not a wrong result
  (loud crash) - hence Low. Found by the P6-run replenishment partial audit
  (error-handling dimension). Fix: in each main(), after json.loads, `if not
  isinstance(data, dict): print(...); sys.exit(1)`. Accept: feeding a top-level-list
  JSON to build_exec_report prints a message and exits nonzero instead of a
  traceback; a valid dict still builds; suites green.
  Done: added an `if not isinstance(...dict): print(...); sys.exit(1)` guard right
  after json.loads in all three mains (build_exec_report.py, draft_report_data.py,
  capture_rendered.py), each naming the offending type. Tests: in test_exec_report,
  TestBuildMainInputGuard (a top-level list exits 1 with "must be a JSON object"; a
  valid dict still builds a docx); in test_review_tools, TestMainInputGuards covers
  the draft and capture mains. Scanner 331 -> 333, builder 32 -> 34, report-charts 8
  green; README resynced to 333/367 (guard exit 0).
- [x] **P12 (done, S)** One JSON-over-HTTP read is still uncapped.
  capture_rendered._devtools_json (capture_rendered.py:330) does
  `json.loads(resp.read().decode("utf-8"))` - the only remote-JSON read in the
  project not bounded by a byte cap after P6 added common._read_json_capped for
  exactly the "do not stream an unbounded body into memory" invariant. Honest
  caveat: this is the localhost DevTools HTTP port of a Chrome instance the tool
  itself launched, so there is no realistic adversarial input and no reproducible
  misbehavior - a consistency/robustness note, not an exploitable defect (hence
  Low). Found by the P6-run replenishment partial audit (unbounded-read sweep).
  Fix: `resp.read(MAX_DEVTOOLS_BYTES)` (e.g. 2 MB) before json.loads. Accept: a
  normal /json/new response still parses; the read is bounded to the cap; suites
  green.
  Done: added MAX_DEVTOOLS_BYTES = 2 MB and changed _devtools_json to
  resp.read(MAX_DEVTOOLS_BYTES) before json.loads, so no remote-JSON read in the
  project is unbounded. New test test_devtools_json_read_is_capped (stubbed urlopen:
  a normal /json/new body parses; read is called with the cap). Scanner 335 -> 336;
  README resynced to 336/370 (guard exit 0); no builder change.
- [x] **P28 (done, S)** An icon button whose only accessible name is a child
  `<img alt>` is flagged as having no accessible text (false warn). The anchor path
  records a wrapped image's alt (htmlmeta.py:89-93), but the button path
  (handle_endtag for button, htmlmeta.py:171-174) checks only button text and
  aria-label, so `<button><img src=s.svg alt="Search"></button>` yields
  buttons_empty == 1 and scan_accessibility (scan_accessibility.py:201-205) warns
  "1 button(s) have no accessible text". The presence-not-value class (like P13).
  Found by the P11-run replenishment partial audit. Fix: in handle_starttag for
  img, capture alt when _cur_button is not None and treat it as satisfying the
  button in handle_endtag. Accept: parse_html('<button><img src=s.svg
  alt="Search"></button>')["buttons_empty"] == 0; a truly empty button still counts;
  suites green.
  Done: added a _button_img_alt state mirroring the anchor's _anchor_img_alt - the
  img handler records a child img's alt when inside a button, and the button-close
  check treats text OR aria-label OR that img alt as an accessible name. New test
  test_button_accessible_name_from_child_img_alt (img-alt button -> 0, alt-less-image
  button -> 1, text button -> 0). Scanner 336 -> 337; README resynced to 337/371
  (guard exit 0); no builder change.
- [x] **P29 (done, S)** A heading interrupted by another heading or left unclosed is
  dropped, yielding a false "No H1". handle_endtag emits a heading only on a matching
  close with _cur_heading == level (htmlmeta.py:152-154); an open heading is never
  flushed when an interrupting heading/block opens or the tag is left unclosed.
  Reproduced: parse_html('<h1>Outer <h2>Inner</h2> tail</h1>')["headings"] loses the
  h1, and '<h1>Welcome<p>Body</p>' yields [] - both flip scan_seo._heading_checks to
  fail "No H1 on the page." though a browser renders the h1. Trigger requires invalid
  HTML (nested/unclosed headings), hence Low, but the consequence is a confidently
  wrong graded FAIL. Found by the P11-run replenishment partial audit. Fix: on a
  heading start (or interrupting block-level start) while _cur_heading is set, flush
  the current heading before opening/resetting. Accept: the nested reproduction
  yields both level 1 and level 2; suites green.
  Done: added a _flush_heading() helper (emit the open heading and clear state) and
  a HEADING_BREAKERS set of block-level tags that cannot sit inside a heading. It is
  called on a heading start (an interrupting heading is flushed first), on a
  HEADING_BREAKERS start (a block element closes an unclosed heading), on a heading
  close (matched or mismatched), and in an overridden close() (an unclosed heading
  at end of document). Inline children (span/b/em) are unaffected. New test
  test_interrupted_or_unclosed_heading_is_not_dropped covers nested, unclosed+block,
  unclosed-at-EOF, and the inline-children case. Scanner 337 -> 338; README resynced
  to 338/372 (guard exit 0); no builder change.
- [x] **P30 (done, S)** A multi-token `role` value is not matched to landmark roles.
  htmlmeta.py:96-97 stores the raw role string; scan_accessibility._landmark_check
  (scan_accessibility.py:138-140) tests token membership against whole strings, so
  role="navigation menubar" yields roles == {"navigation menubar"} and "navigation"
  is not found - a page with a navigation role (and no <nav>) reports warn "Missing
  landmark(s): nav." Rare (multi-token roles are uncommon), hence Low. Found by the
  P11-run replenishment partial audit. Fix: split role on whitespace into individual
  tokens when populating roles. Accept: "navigation" is in the roles set for the
  input above; suites green.
  Done: the role handler now does self.roles.extend(a["role"].split()) instead of
  append, so each fallback token is matchable and role="navigation menubar"
  satisfies the navigation landmark. New test test_multi_token_role_is_split_into_
  tokens. Scanner 340 -> 341; README resynced to 341/376 (guard exit 0); no builder
  change.
- [x] **P31 (done, S)** A cross-subdomain crawl uses only the target host's
  robots.txt. crawler.crawl loads robots once from the target (crawler.py:86,
  _load_robots(target)) and applies rp.can_fetch to every URL, while _eligible
  (crawler.py:50-57) admits any same-registrable-domain host including other
  subdomains (blog.example.com for target example.com). The subdomain's own
  robots.txt is never fetched, so a path blog.example.com/robots.txt disallows can be
  crawled if the apex robots permits it. Per RFC 9309 robots is per-authority, so
  this is a politeness/charter gap; trigger requires a same-registrable subdomain
  link with a stricter robots than the apex, hence Low. Found by the P11-run
  replenishment partial audit. Fix: key RobotFileParser instances by fetched origin
  (scheme+host) and consult the matching one per URL. Accept: a URL on a subdomain
  whose robots disallows it is counted in skipped_by_robots, not collected; suites
  green.
  Done: crawl now keys RobotFileParser instances by origin (scheme+host) via a
  robots_for(url) cache and consults the matching parser for can_fetch on every URL;
  the per-page sleep is max(base wait, that origin's crawl-delay) so a stricter
  subdomain delay is honored too. Added _origin/_crawl_delay helpers. New test
  test_subdomain_robots_are_honored_per_origin: a blog.acme.example/secret link
  disallowed by the subdomain's own robots is skipped (skipped_by_robots >= 1, never
  fetched) while /ok is collected. Scanner 341 -> 342; README resynced to 342/377
  (guard exit 0); no builder change.
- [x] **P34 (done, S)** A progress-only executive summary renders an orphaned strip
  with no heading. build_exec_report.py:883 `if progress and not trend:` renders the
  "Since the previous review..." strip, but section_titles adds no "Executive
  summary" heading when there is no bottom_line/assessment/trend, so on
  progress-only data the strip floats under the glance tiles with no section title
  or contents entry. Cosmetic, unusual data combo. Found by the P29-run replenishment
  partial audit (builder mechanics). Fix: gate the strip behind the same heading, or
  emit the Executive summary heading when only progress exists. Accept: with only
  progress present, the strip renders under an Executive summary heading; suites
  green.
  Done: computed progress/trend before section_titles and introduced
  has_exec_summary = bottom_line or assessment or (progress and not trend); both the
  section_titles entry and the rendered heading now gate on it, so a progress-only
  report gets an Executive summary heading, a contents entry, and the strip under
  it. New test test_progress_only_renders_under_an_executive_summary_heading.
  Builder 35 -> 36, exec-report green; scanner 342 and report-charts 8 unaffected;
  README resynced to 378 total (guard exit 0).
- [x] **P35 (done, S)** Non-string scalars where a string is contracted crash the
  build. site as null -> TypeError in add_running_header (build_exec_report.py:386,
  " | ".join([None,...])); scorecard.overall as a number -> AttributeError at
  add_cover:325 (overall.upper()); a non-string quick_wins/assessment item ->
  add_run(123) "int not iterable". These need type-invalid input (the contract is
  string), so Low, but the deliverable dies on a hand-authoring slip. Found by the
  P29-run replenishment partial audit. Fix: str()-coerce those three sites. Accept:
  building with site/overall/a quick_win as a number succeeds; suites green.
  Done: add_run now renders "" for None and str(x) for any other scalar (covers
  quick_wins/assessment/strengths items); add_cover and add_glance_tiles coerce the
  scorecard overall band to str (handles a number or a stray dict); the running
  header joins str(b) for b in bits (handles a non-string site). New test
  test_non_string_scalars_do_not_crash_the_build covers site/overall/quick_win as a
  number, overall as a dict, an int assessment item, and site as null. Builder
  36 -> 37, exec-report green; scanner 342 and report-charts 8 unaffected; README
  resynced to 379 total (guard exit 0).
- [x] **P36 (done, S)** env_value keeps an inline comment and rejects `export`.
  common.py:357 returns line.split("=",1)[1].strip().strip('"').strip("'") with no
  comment handling, so `SERPER_API_KEY=abc123 # note` returns "abc123 # note" (a
  wrong secret), and `export NAME=...` fails the startswith match. Minor (only
  dotenv-style inline comments / export). Found by the P29-run replenishment partial
  audit. Fix: strip an unquoted trailing #comment and tolerate a leading `export `.
  Accept: env_value on `K=v # c` returns "v"; `export K=v` returns "v"; a value
  containing a literal # inside quotes is preserved; suites green.
  Done: env_value now strips a leading `export ` before matching the key; for the
  value, a leading quote makes it keep everything up to the closing quote (a literal
  # and interior spaces preserved, anything after the closing quote dropped), and an
  unquoted value ends at the first inline # comment. New test
  test_env_value_strips_comments_and_tolerates_export (K=v # c -> v; export K=v -> v;
  K="ab#cd" -> ab#cd; K="quoted" # note -> quoted; K= -> None). Scanner 342 -> 343;
  README resynced to 343/380 (guard exit 0); no builder change.
- [x] **P37 (done, S)** normalize_url misreads a scheme-less host:port. common.py:49
  uses urlparse(url).scheme to decide whether to prepend https://, but
  urlparse("example.com:8080").scheme == "example.com" (a dotted string is a valid
  URI scheme), so no scheme is added and host_of/slug_of then return "" (the
  deliverable would be named "_Executive_Report.docx"). Only a scheme-less host:port
  target triggers it; the documented paths carry a scheme, so Low. Found by the
  P29-run replenishment partial audit. Fix: detect a `host:port` shape (or check for
  "://" rather than urlparse().scheme) and prepend the scheme. Accept:
  normalize_url("example.com:8080") yields an https URL whose host_of is
  "example.com"; suites green.
  Done: normalize_url now keys on the "://" separator (`if "://" not in url`) rather
  than urlparse().scheme, so a bare host:port gets https:// prepended and host_of
  returns the host; a real scheme (http://, https://) and a bare host are unchanged.
  New test test_normalize_url_handles_scheme_less_host_port. Scanner 344 -> 345;
  README resynced to 345/382 (guard exit 0); no builder change.
- [x] **P39 (done, S)** The evidence appendix crashes on a non-string code or image.
  build_exec_report.py:778 does code.split("\n") - item.get("code") is not None lets
  a numeric code through to .split (AttributeError) - and :1050 does
  Path(img).exists() where a numeric truthy image reaches Path(123) (TypeError). A
  null code/image is already handled (code falls through, image is falsy); only a
  present non-string crashes. Low realism (snippets/paths are strings) but the same
  P35 coercion gap. Reproduced: evidence=[{"caption":"c","code":123}] and
  [{"caption":"c","image":123}] both crash the build. Found by the P35-run
  replenishment partial audit. Fix: str() the code before split; gate image on
  isinstance(item.get("image"), str). Accept: both cases build without raising; a
  normal code/image exhibit still renders; suites green.
  Done: add_code_block now iterates str(code).split (a non-string snippet
  stringifies), and the image branch gates on isinstance(item.get("image"), str) so
  a non-string path is skipped rather than Path()'d. Extended
  test_non_string_scalars_do_not_crash_the_build with evidence code=123 / image=123;
  a normal code snippet and a missing image path still render. Builder 37 (extended
  test), exec-report green; scanner 345 and report-charts 8 unaffected; guard exit 0.
- [x] **P41 (done, S)** The form-action downgrade check misses the HTML5 formaction
  override. scan_page_security.check_form_actions (scan_page_security.py:87-106)
  scans only `<form action=...>`, but a submit button/input can override it with
  formaction="http://..." and submit over plain HTTP while the form's own action is
  secure. Reproduced: `<form action="/submit">...<button type=submit
  formaction="http://insecure.example/steal">Send</button></form>` grades pass - a
  real (if uncommon) downgrade vector graded clean. Found by the P36-run replenishment
  partial audit. Fix: also extract formaction from button/input[type=submit|image]
  and apply the same http:// test. Accept: the fixture returns fail; a formaction over
  https stays pass; scanner suite green.
  Done: added FORMACTION_RE (with the same (?<![-\w]) lookbehind so it stays distinct
  from action= and data-formaction) and check_form_actions now also collects any
  http:// formaction from the body into the insecure list; the note names both form
  action and button formaction. New test test_http_formaction_override_fails (a
  secure form + an http formaction -> fail with the URL listed; a data-formaction ->
  pass). Scanner 345 -> 346; README resynced to 346/383 (guard exit 0); no builder
  change.
- [x] **P42 (done, S)** An empty integrity="" was counted as SRI present, a false
  pass. scan_page_security INTEGRITY_RE (scan_page_security.py:42) matched
  `integrity\s*=` regardless of value, so a cross-origin `<script src=...
  integrity="">` (empty metadata = no protection) graded pass instead of warn.
  Reproduced: `<script src="https://cdn.other-site.example/lib.js" integrity="">`
  -> pass, vs warn with the attribute absent. Low prevalence (author error). Found by
  the P36-run replenishment partial audit. Fix: require a non-empty integrity value
  (a sha256-/sha384-/sha512- token). Accept: the empty-value fixture returns warn; a
  real sha256- integrity stays pass; scanner suite green.
  Done: INTEGRITY_RE now requires a real hash token -
  `integrity\s*=\s*["']?\s*sha(?:256|384|512)-` (case-insensitive, quote optional,
  leading whitespace allowed), so integrity="" and a non-hash value no longer count
  as protection while a genuine sha256/384/512- value still passes. The (?<![-\w])
  lookbehind keeps it off data-integrity=. New test test_sri_empty_integrity_value_
  warns (empty and non-hash -> warn; real sha512- -> pass; data-integrity decoy ->
  warn). Scanner 348 -> 349; README resynced to 349/386 (guard exit 0); no builder
  change.
- [x] **P43 (done, S)** Legacy Expires/s-maxage-only assets got a false "uncached"
  warn. scan_performance._measure (scan_performance.py:88-91) recorded only
  cache-control, and _asset_caching_check treated an asset as cached only via
  max-age>0/immutable, so an asset whose freshness is a bare Expires: header (Apache
  mod_expires) or s-maxage only was scored uncached; if more than half the assets are
  like that the check warns "repeat visits redownload them" - factually wrong.
  Reproduced: two 200 assets with cache_control=None (Expires-set) -> warn. Modern
  CDNs send Cache-Control so prevalence is low today (rises against a legacy target).
  Found by the P36-run replenishment partial audit. Fix: capture Expires in _measure
  and treat a future Expires (or s-maxage) as a caching lifetime. Accept: two assets
  with a future Expires and no Cache-Control return pass; scanner suite green.
  Done: _measure now captures the Expires header; _asset_caching_check credits an
  asset with a usable lifetime when it is immutable, has max-age>0, has s-maxage>0, OR
  carries a still-future Expires (parsed via email.utils.parsedate_to_datetime and
  compared to now; a past date or Expires: 0 is stale, so not credited), while
  Cache-Control no-store/no-cache still override any Expires (browser precedence).
  Refactored _cache_max_age onto a shared _cc_seconds(cc, directive) helper (DRY;
  a (?<![-\w]) lookbehind keeps max-age and s-maxage distinct). New test
  test_expires_and_s_maxage_count_as_caching_lifetime (future Expires / s-maxage ->
  pass; past Expires, Expires: 0, and no-store+Expires -> warn). Scanner 349 -> 350;
  README resynced to 350/387 (guard exit 0); no builder change.
- [x] **P47 (done, S)** A revoked DKIM key (empty p=) was counted as a published key.
  scan_dns_email._is_dkim_record (scan_dns_email.py:116) returned True on any p= tag
  including an empty value, but RFC 6376 sec 3.6.1 says an empty p= means the key is
  revoked. Reproduced: _is_dkim_record("v=DKIM1; p=") -> True, so a revoked key on a
  common selector grades pass "DKIM key published". Edge (revoked keys usually sit on
  rotated random selectors). Found by the P41-run replenishment partial audit. Fix:
  treat a p= whose value is empty/whitespace as revoked, not present. Accept:
  _is_dkim_record("v=DKIM1; p=") is False; a real p=<key> stays True; suite green.
  Done: _is_dkim_record now scans every tag (rather than returning on the first) and
  returns False the moment it sees a p= with an empty/whitespace value, so a revoking
  p= vetoes a preceding v=DKIM1 or k= (order-independent); a non-empty p=/k=/v=DKIM1
  still marks a published key. New test test_dkim_empty_p_is_revoked_not_published
  (six _is_dkim_record cases incl. p-before-v and k=+empty-p, plus end to end: a
  selector answering only a revoked key grades info, not pass); the existing
  substring-decoy test still passes. Scanner 350 -> 351; README resynced to 351/388
  (guard exit 0); no builder change.
- [x] **P48 (done, S)** Missing Permissions-Policy graded a hard fail (over-strict
  false fail that deflated the security band). scan_http_security.py:308-310 routed
  an absent Permissions-Policy through check_simple_header's fail path (:87), scoring
  0.0 - equal weight to missing HSTS. Mozilla HTTP Observatory (the de facto scorer)
  does not score Permissions-Policy at all; it is an advanced/optional header most
  hardened sites omit. Reproduced: {} -> fail. Opposite-direction from the dangerous
  class (deflates rather than inflates) but can push a category from Adequate to Weak
  in the CEO report. Found by the P41-run replenishment partial audit. Fix: grade its
  absence info (or warn), not fail. Accept: no Permissions-Policy -> info/warn, not
  fail; a present policy still grades; suite green.
  Done: added an absent_verdict parameter to check_simple_header (default "fail", so
  X-Content-Type-Options and every other caller are unchanged) and the
  permissions_policy registry entry passes "info" with a note that it is an advanced,
  optional header major scorers do not penalize. New test
  test_absent_permissions_policy_is_info_not_fail (end to end: absent Permissions-
  Policy -> info while absent X-Content-Type-Options still -> fail; a present policy
  still passes). Scanner 351 -> 352; README resynced to 352/389 (guard exit 0); no
  builder change.
- [x] **P49 (done, S)** The version-banner check false-warned on a CDN node id.
  scan_http_security.py:269 had has_version = any(ch.isdigit() for ch in val), so any
  digit read as a version. Reproduced: Server: ECAcc (nyd/D179) (an Akamai edge node
  id) -> warn "Version banners present". Minor (warn not fail; the string is disclosed
  either way). Found by the P41-run replenishment partial audit. Fix: require a
  version-shaped token (regex \b\d+(\.\d+)+\b or name/digits) before flagging. Accept:
  a bare node id like ECAcc (nyd/D179) does not warn; nginx/1.25.3 still warns; suite
  green.
  Done: added VERSION_RE = re.compile(r"\b\d+(?:\.\d+)+\b") (a dotted numeric token,
  two-plus components) and check_disclosure now sets reveals_version =
  bool(VERSION_RE.search(val)), so a bare integer in a CDN node id or build hash no
  longer reads as a version while nginx/1.25.3, Apache/2.4.52, Microsoft-IIS/10.0,
  PHP/8.1.2, and x-aspnet-version 4.0.30319 still warn (added import re). Extended
  test_disclosure with the Akamai node id (info, reveals_version False), IIS/10.0
  (warn), and ASP.NET name (info). Scanner 355 (extended test, count unchanged); README
  total 392 unaffected (guard exit 0); no builder change.
- [x] **P50 (done, S)** A non-responsive viewport passed as mobile-friendly.
  scan_seo.py:120-123 passed on any non-empty viewport content, but Google's
  mobile-friendly requirement is width=device-width; a fixed-width viewport
  (content="width=1024") is not responsive. Reproduced: content="width=1024" -> pass
  "Mobile viewport set". Uncommon in practice. Found by the P41-run replenishment
  partial audit. Fix: pass only when the content contains width=device-width;
  otherwise warn. Accept: width=1024 -> warn; width=device-width -> pass; suite green.
  Done: extracted _viewport_check(viewport) - absent -> fail (unchanged); content with
  width=device-width (space-insensitive, case-insensitive) -> pass "Responsive viewport
  set"; present but without it (width=1024, or a width-less value) -> warn "set but not
  responsive". New test test_viewport_check (device-width incl. uppercase -> pass;
  width=1024 and initial-scale-only -> warn; None/"" -> fail). Scanner 358 -> 359; README
  resynced to 359/396 (guard exit 0); no builder change.
- [x] **P55 (done, S)** Rendered snapshot filenames churn every run, orphaning old
  snapshot files (a determinism smell and a small disk leak in the evidence tree).
  capture_rendered.py:534 seeds taken from the existing manifest, which already holds
  the URL's own current filename, so snapshot_filename (:456, called at :554) allocates
  a NEW name for a URL merely being refreshed instead of reusing its slot; the manifest
  is repointed (:557), leaving the prior snapshot orphaned. Reproduced across three runs
  of one page: home.html -> home-2.html -> home.html (oscillates), both files left on
  disk. Low: scan_site.py:83 reads only the manifest-referenced file, so the deliverable
  stays correct - this is internal evidence hygiene, not a wrong report. Found by the
  P52-run replenishment partial audit. Fix: if url already has a manifest entry, reuse
  manifest["pages"][url]["file"]; call snapshot_filename only for a URL new to the
  manifest. Accept: capturing the same DOM page twice reuses one filename (no
  home-2.html), and two distinct pages still get distinct names; the capture test(s)
  green.
  Done: the DOM-snapshot branch now reuses manifest["pages"][url]["file"] when the URL
  already has an entry, and only calls snapshot_filename for a URL new to the manifest -
  so a refresh keeps its slot instead of being pushed to a new name by taken (which is
  seeded from the manifest, including the URL's own file). New test
  test_refreshing_a_dom_page_reuses_its_snapshot_filename (capture the same page 3 times:
  one stable filename, exactly one .html on disk, no orphan); the distinct-page and
  manual-merge tests still pass, so genuinely new URLs still get distinct names. Scanner
  359 -> 360; README resynced to 360/397 (guard exit 0); no builder change.
- [x] **P60 (done, S)** A far-future cert notAfter crashes the whole TLS scan on Windows.
  scan_tls.py:121 calls time.strftime("%Y-%m-%d", time.gmtime(expiry_epoch)) after
  _parse_not_after (scan_tls.py:51-61); on Windows time.gmtime raises OSError [Errno 22]
  for any epoch past ~year 3000, uncaught inside _scan, aborting the TLS category with no
  result. Reproduced: _parse_not_after("Dec 31 23:59:59 9999 GMT") then gmtime ->
  OSError; boundary is year 3000 ok, 3001 crash. Low: tls_info validates the chain first
  and a publicly-trusted leaf never carries notAfter beyond ~398 days, so a live
  handshake reaching this path is very unlikely (the 99991231235959Z no-expiry sentinel
  is a CA-cert convention, not a presented leaf), but it is a genuine uncaught crash.
  Found by the P49-run replenishment partial audit. Fix: guard the gmtime/strftime
  conversion (clamp far-future epochs or wrap in try/except) so a pathological date
  degrades to an info note, not an aborted scan. Accept: a stubbed far-future notAfter
  (year 9999) yields a graded TLS result (the expiry check degrades, not raises), not an
  aborted scan; a normal expiry still formats; suite green.
  Done: wrapped the time.strftime(time.gmtime(expiry_epoch)) call in try/except
  (OSError, ValueError, OverflowError); on failure expires_on is set to None (the display
  date is dropped, never fabricated) and days_left - plain arithmetic in _parse_not_after,
  not gmtime - still drives the expiry verdict. New test
  test_far_future_cert_expiry_does_not_abort_the_scan (notAfter year 9999 -> scan ok,
  expiry pass, expires_on None; a 2027 cert still formats expires_on "2027-08-29"). Scanner
  360 -> 361; README resynced to 361/398 (guard exit 0); no builder change.
  Follow-up (CI portability): the first version of the test asserted expires_on IS None on
  the far-future case, which only holds on Windows (gmtime raises past ~year 3000); on
  Linux gmtime formats the date, so the Ubuntu CI legs failed. Rewrote the test to force
  the raising-gmtime branch explicitly (stub tls.time.gmtime to raise -> expires_on None,
  deterministic on any platform) and to accept expires_on None-or-str on the real
  far-future date. The production guard was already correct cross-platform; only the test
  over-asserted a Windows detail. All three suites green locally on Windows.
- [x] **P62 (done, S)** Two inaccurate statements in README.md. (a) README.md:239 said
  "Network primitives are stubbed suite-wide so no test can ever reach a real network or
  read a real key", but only http_post_json, env_value, and rdap_domain are stubbed at
  module import; http_fetch, tls_info, and doh_query are patched per-test (try/finally),
  so a new test that forgets to patch could reach the live network - the "no test can
  ever" guarantee is not enforced by the mechanism described. Reproduced: after importing
  test_review_tools, common.http_fetch/tls_info/doh_query are unchanged (not stubbed)
  while http_post_json/env_value/rdap_domain are. (b) README.md:261 says "ci.yml  Both
  test suites" but CI runs THREE (test_review_tools, test_exec_report, test_report_charts)
  plus check_readme_counts, inconsistent with README:241 ("all three suites"). Low:
  misleading docs, no product impact. Found by the P50-run replenishment partial audit.
  Fix: (a) reword to name what is stubbed suite-wide (CrUX POST, key reader, RDAP) vs
  per-test (HTTP/TLS/DoH); (b) change "Both test suites" to "all three test suites +
  README-count guard". Accept: README no longer claims suite-wide stubbing of
  http_fetch/tls_info/doh_query, and the ci.yml line says three suites; guard exit 0.
  Done: (a) README.md:239 now reads "The CrUX API call, the credential reader, and RDAP
  are stubbed suite-wide at import; the HTTP fetch, TLS, and DoH primitives are stubbed
  per test, so the suite reaches no real network and reads no real key" - accurate to the
  mechanism (http_post_json/env_value/rdap_domain suite-wide, http_fetch/tls_info/doh_query
  per-test), dropping the overstated "no test can ever". (b) README.md:261 now says "All
  three test suites + README-count guard" - verified ci.yml runs test_review_tools,
  test_exec_report, test_report_charts, and check_readme_counts.py. Documentation-only; the
  count guard is still in sync (400 total, prose edits do not touch counts).
- [ ] **P63 (todo, S)** test_cover_contents_list_names_rendered_sections_in_order does
  not check order. test_exec_report.py:144-151 asserts only assertIn(name, listing)
  membership within a 600-char slice, so a regression that reordered the cover's contents
  list would still pass though the test name promises order. Low: the invariant holds
  today (cover and headings both derive from the same section_titles list), so the risk
  is small, but the test does not guard what it claims. Found by the P50-run replenishment
  partial audit. Fix: assert the found positions are monotonically increasing (or compare
  the extracted ordered names to the expected sequence). Accept: the test fails if the
  contents-list order is shuffled relative to the section order; builder suite green.
- [ ] **P66 (todo, S)** The scorecard band is computed from the unrounded score but the
  ROUNDED score is displayed, so at every band boundary the shown number contradicts the
  band label. common.grade (common.py:578-581) derives band from the exact score, then
  returns round(score, 2); draft_report_data._scorecard renders "<band> ... (score 0.85)"
  plus a numeric score bar. Reproduced: 9 pass / 4 warn (raw 0.84615) -> displayed_score
  0.85, band Adequate, though 0.85 is the Strong cutoff; 5 pass / 12 warn (raw 0.64706) ->
  0.65 displayed, band Weak (0.65 is the Adequate cutoff); 0 pass / 19 warn / 5 fail (raw
  0.39583) -> 0.4 displayed, band Poor (0.40 is the Weak cutoff). Low: the band (from the
  true score) is the honest posture, so it misleads the eye, not the verdict - a
  wrong-looking number, not a flipped band. Found by the P60-run replenishment partial
  audit. Fix: make label and number agree - display the score at enough precision that it
  does not round onto a boundary (or floor rather than round), keeping the band as the
  source of truth; do NOT compute the band from the rounded score (that would inflate a
  just-below-boundary site by a band). Accept: no scorecard row shows a displayed score
  that sits in a different band's range than its label; suites green.

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
- [x] **O8 (done, S)** Hardening (not a current bug): the README's collection
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
  Done: readme_mismatches and fixed_readme gained trackers/cmp_hosts/dkim params;
  main derives them from len(scan_privacy.KNOWN_TRACKERS / CMP_HOSTS) and
  len(scan_dns_email.DKIM_SELECTORS) and adds three needles ("N documented tracker
  domains", "M CMP hosts", "K documented selector families"); --fix rewrites them
  too. Verified: editing 154 -> 153 or 20 -> 21 in the README makes the guard exit
  1 naming the drifted count; correct values exit 0; test_wrong_collection_count_
  is_reported plus the updated fixtures cover it. Runs in the existing ci.yml
  check_readme_counts step (no workflow change). Scanner 306 -> 307, builder 32,
  report-charts 8, all green; README resynced to 307/339. Closes the numeric part
  of the unguarded-doc-count class (O2/O6 prose remain unguardable by count).

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
- (re-opened as Phase P P4) the common._decompress decompression-bomb was
  declined in Phase O on the reasoning that MAX_BODY_BYTES caps the body; that is
  wrong (it caps the compressed read, not the decompressed output) and did not
  account for triage's unknown-domain sweep, so the Phase P audit re-opened it.
- scan_design.check_font_families fetches up to 5 stylesheets serially rather
  than via the bounded pool (Phase P audit): bounded (MAX_STYLESHEETS=5,
  per-request timeout) and cache-deduped across pages, so a worst-case slow page,
  not a defect worth the added concurrency.
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
- draft_report_data._scorecard (:253) does (sc.get("overall") or {}).get("band")
  and would AttributeError if scorecard.overall were a plain string (P35-run audit):
  unreachable from real data - scan_site.build_scorecard always emits overall as a
  common.grade dict, and the scan JSON is machine-written, so only a hand-edited
  scan file (not a supported input, unlike exec_report_data.json) triggers it.

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
