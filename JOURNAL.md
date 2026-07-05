# JOURNAL.md - Iteration record

Append-only. Newest entry at the bottom. One entry per Ralph iteration: what
changed, why, what was verified, and the single most useful next step.

---

## 2026-07-04 - P22: dedup the review set so one page is not scanned twice

**Task:** P22 (Medium). scan_site._run built page_urls as [target] + normalized
extras with no dedup, and normalize_url does not strip a trailing slash, so
https://example.com and https://example.com/ were scanned as two pages. Because a
homepage almost always links to /, group_issues then gave every homepage failure
pages=[both strings], page_count=2, and the report claimed "2 page(s)" listing the
same page twice; pages_scanned inflated the cover tile and the homepage's
vitals/weight double-entered the trend medians.

**What I did:** _run now dedups by a canonical key (scheme, netloc.lower(),
path or "/", query). Empty path and "/" share the key, so the homepage collapses;
distinct paths keep distinct keys. I deliberately did NOT strip trailing slashes on
non-root paths (/a vs /a/ can be different resources), collapsing only the
unambiguous empty-vs-"/" root case the bug is about.

**Files changed:** scan_site.py (urlparse import + dedup in _run),
test_review_tools.py (test_scan_set_is_deduplicated), README.md (counts 325 -> 326
via --fix), BACKLOG.md (P22 done), JOURNAL.md (this entry).

**Verification:** homepage + trailing-slash -> 1 page_scan; two distinct pages -> 3;
/a vs /a/ -> 3 (kept distinct); an exact duplicate collapses. Scanner 325 -> 326,
all green; README resynced to 326/358 (guard exit 0); no builder change.

**Learnings:** the fix belongs at the scan set, not each caller - run_review's crawl
filter and discovery both surface the /-variant, and fixing scan_site._run covers
every entry path at once. Choosing a precise canonical key (collapse only empty-vs-
"/") over a blunt rstrip("/") avoids over-merging genuinely distinct paths; a
correctness fix should not trade one wrong count for another.

**Next:** P23 (run-scope rendered metrics so stale evidence is not graded current),
P24 (contrast over background images), then P11/P12 (Low). Two Medium open, so not
converged. No promise.

## 2026-07-04 - JOURNAL rotation

**Task:** housekeeping. JOURNAL.md passed the 500-line rotation threshold, so
the oldest entries move to JOURNAL-archive.md and the last 10 stay here.

**What I did:** moved 4 entries verbatim to JOURNAL-archive.md:
- 2026-07-04 - P9: correct the trend-chart "three quarters" wording
- 2026-07-04 - P13: stop failing forms on their submit button; check image-input alt
- 2026-07-04 - P14: treat robots content=none as noindex (false PASS on a de-indexed page)
- 2026-07-04 - JOURNAL rotation

**Verification:** archive is append-only and unchanged above the move;
JOURNAL.md now holds the preamble, the last 10 substantive entries, and this
rotation note. No code or state logic touched.

**Next:** P23 (run-scope rendered metrics). No promise.

## 2026-07-05 - P23: run-scope rendered evidence so stale is not graded current

**Task:** P23 (Medium). scan_vitals.load_metrics read metrics.json unconditionally,
and metrics.json persists across runs, so a `--no-browser` run (or a page that fails
capture this run) graded a prior run's Core Web Vitals as a current "lab
measurement" - a stale Good masking a regression, the charter's forbidden
"unmeasured thing reported as a pass".

**What I did:** the metrics/manifest entries already carried captured_at_utc, so I
added a freshness boundary rather than clearing evidence - CAPTURE.md guarantees a
manual capture is merged, never clobbered, so clearing was not an option.
run_review.pipeline stamps run_start at the top and passes min_capture_utc to both
scan_site.run calls (the pre-capture scan and the post-capture rescan); scan_site
threads it to load_rendered_snapshots (drops a stale DOM snapshot) and onto each
page context; scan_vitals.load_metrics rejects an entry captured before the
boundary. Standalone scan_site.py and the manual pass pass None, so any on-disk
evidence is still used (backward compatible). ISO-8601 UTC stamps compare
lexicographically, so the check is a string compare.

**Files changed:** scan_vitals.py (load_metrics boundary + _scan reads it from
page), scan_site.py (load_rendered_snapshots filter, run/_run threading, ctx
injection), run_review.py (run_start stamp, both run calls, capture_and_rescan
param), test_review_tools.py (new boundary test; fixed a lambda-arity stub and a
fake_capture that stamped a fixed 2026-01-01), README.md (326 -> 327 via --fix),
BACKLOG.md (P23 done), JOURNAL.md (this entry).

**Verification:** stale metrics + a boundary after the stamp -> vitals info
(captured False); no boundary or a boundary before the stamp -> measured; the
capture+rescan pipeline test (fake capture now stamps now) still consumes the fresh
snapshot. Scanner 326 -> 327, exec-report 32, report-charts 8 all green; README
resynced to 327/359 (guard exit 0).

**Learnings:** the right boundary was the run's start, not the scan's own timestamp
- a scan's measured_at is AFTER a legitimately-just-captured file, so keying on it
would reject fresh evidence; keying on run_start (shared by the pre-capture scan and
the post-capture rescan) accepts this run's capture while rejecting last run's.
Making the boundary an explicit parameter that defaults to None kept the standalone
and manual-capture paths working unchanged - a freshness rule that only the
orchestrator, which knows where the run begins, gets to impose.

**Next:** P24 (contrast over background images fabricates a false violation), then
P11/P12 (Low). One Medium open, so not converged. No promise.

## 2026-07-05 - P24: do not fabricate a contrast violation over a background image

**Task:** P24 (Medium, false verdict). The contrast DOM walk's bgOf assumed white
whenever no ancestor had an opaque backgroundColor, ignoring background-image, so
light text over a dark hero image gave ratio 1.0 and was pushed as a WCAG 1.4.3
violation quoting the real heading - a false accessibility claim in the docx,
fabricating a measurement against a background it could not read.

**What I did:** bgOf now returns null when an ancestor has a background-image or
gradient (painted above any color, no single color to measure); the loop skips such
elements and counts them as inconclusive rather than grading them against an assumed
white. check_contrast surfaces the skipped count so the omission is visible.

**Files changed:** capture_rendered.py (CONTRAST_JS bgOf + loop), scan_vitals.py
(check_contrast inconclusive surfacing), test_review_tools.py (a Python test and a
node-gated JS test; added shutil/subprocess/time imports), README.md (327 -> 329),
BACKLOG.md (P24, P25 done), JOURNAL.md (this entry).

**Verification:** verified the JS in a real engine (node v22): text over a
background image or gradient -> inconclusive, no violation; a genuine gray-on-white
-> violation; white on solid black -> measurable pass. The node-gated test skips
where node is absent (CI stays green). Scanner 327 -> 329 -> 331, exec-report 32 and
report-charts 8 all green; README resynced.

**Replenishment (open at two after P24 - audited the last two un-swept areas: the
quarterly trend layer and common.py's HTTP core):** trends.py, report_charts.py and
draft's trend block came back CORRECT by reproduction (quarter selection, series
alignment with gaps, delta direction, chart axes honest/baseline-zero), as did the
fetch cache key, header folding, registrable_domain and the TLS/DoH shapes. One
Medium found and, this turn, also fixed (P25, a deviation from one-task-per-iteration
that I judged better than reverting verified work): http_fetch presented a capped or
looping redirect chain as ok=True (the loop exhausted on a 3xx and fell through to
the success builder with body=None), so check_host_canonicalization graded a
self-looping www host as a converged "pass". Fixed with a for/else that raises
TooManyRedirects into the existing error builder, plus keying reachability off
r.get("ok"); reproduced before and after.

**Learnings:** P24 and P25 are the same charter breach on opposite ends of the
stack - P24 fabricates a measurement (assumed-white background), P25 fabricates a
success (a redirect that never terminated). Both dressed an absence of data as data:
a computed 1.0 ratio, an ok=True with no body. The fix in both is to make the code
say "unknown" (inconclusive; ok=False) instead of inventing a confident answer. A
`for` loop that only sets success inside the body needs a `for/else` to handle the
"ran out without succeeding" path - the missing else was the whole bug in P25.
Process note: I completed P25 in the same iteration as P24 rather than only filing
it; verified and green, so kept, but flagged.

**Next:** P11 (guard the report/capture mains against a non-dict input), P12 (cap
the DevTools read). Two Low open, zero High, zero Medium. When the backlog clears,
the next full convergence audit can certify done. No promise.

## 2026-07-05 - P11: guard the report/capture CLIs against a non-dict input JSON

**Task:** P11 (Low). build_exec_report.main, draft_report_data.main and
capture_rendered.main json.loads their input and immediately call .get on it, so a
top-level-list JSON (a plausible hand-authoring slip, since exec_report_data.json is
partly hand-written) produced a raw AttributeError traceback instead of a clear
message - unlike the scan layer, which already guards this class.

**What I did:** added an `if not isinstance(...dict): print(...); sys.exit(1)` guard
right after json.loads in all three mains, each naming the offending type.

**Files changed:** build_exec_report.py, draft_report_data.py, capture_rendered.py
(the guards), test_exec_report.py (TestBuildMainInputGuard + contextlib/io/json
imports), test_review_tools.py (TestMainInputGuards + sys import), README.md
(counts via --fix), BACKLOG.md (P11 done; P26-P31 filed), JOURNAL.md (this entry).

**Verification:** a top-level list to each main exits 1 with "must be a JSON
object"; a valid dict still builds a docx. Scanner 331 -> 333, builder 32 -> 34,
report-charts 8 all green; README resynced to 333/367 (guard exit 0).

**Replenishment (open at one after P11 - audited the last foundational area not yet
swept for PARSING correctness, htmlmeta.py, plus a fresh deep look at
crawler/discovery):** the parser is CORRECT on well-formed input across every field
a scanner grades (title, charref decoding, meta attribution, label ordering, image
alt, the client-rendered heuristic), and the crawler's delay/cap/resume/dedup all
hold. Six findings filed. Two Medium: P26 (JSON-LD @graph - the dominant real-world
shape - is not read, so a structured-data-rich page reports "No JSON-LD" and loses
an SEO pass) and P27 (registrable_domain collapses unlisted multi-label suffixes
like com.sg/co.in to the suffix, so the same-site gate admits a DIFFERENT registrant
- a scope/authorization charter breach on such targets). Four Low: P28 (icon button
with a child img alt flagged empty), P29 (an interrupted/unclosed heading dropped ->
false No H1), P30 (a multi-token role not matched to a landmark), P31 (a
cross-subdomain crawl uses only the apex robots.txt).

**Learnings:** the parser being correct on well-formed input but wrong on @graph and
malformed headings is the through-line - htmlmeta grades what it fully understood and
silently drops what it did not, and a silent drop becomes a confident downstream
verdict ("No JSON-LD", "No H1"). P27 is the sharpest: a hardcoded 13-entry suffix
list is a latent scope breach on every ccTLD it omits, and scope breaches are the
one class where the consequence is not a wrong report but an unauthorized fetch. The
real fix is a Public Suffix List, not a longer hardcoded list.

**Next:** P26 (JSON-LD @graph) then P27 (suffix scope), then the Low P12/P28-P31.
Two Medium open, so not converged. No promise.

## 2026-07-05 - JOURNAL rotation

**Task:** housekeeping. JOURNAL.md passed the 500-line rotation threshold, so
the oldest entries move to JOURNAL-archive.md and the last 10 stay here.

**What I did:** moved 4 entries verbatim to JOURNAL-archive.md:
- 2026-07-04 - P15: grade <link> mixed content by rel, not by tag name
- 2026-07-04 - P16: grade clickjacking headers by value, not presence
- 2026-07-04 - JOURNAL rotation
- 2026-07-04 - P17: grade DNSSEC on the resolver AD flag, not DNSKEY presence

**Verification:** archive is append-only and unchanged above the move;
JOURNAL.md now holds the preamble, the last 10 substantive entries, and this
rotation note. No code or state logic touched.

**Next:** P26 (JSON-LD @graph detection). No promise.

## 2026-07-05 - P26: read JSON-LD types from @graph, not just the top level

**Task:** P26 (Medium, false info). _collect_jsonld read @type only from the
top-level object (or top-level list members), never from @graph, which is the
dominant real-world shape (Yoast, RankMath, WordPress core emit `{"@context":..,
"@graph":[{...}]}`). So a page rich in structured data reported jsonld_types == [],
and scan_seo graded info "No JSON-LD structured data." - a confidently-wrong report
line that also dropped a pass from the SEO grade.

**What I did:** _collect_jsonld now assembles a node list of the top-level nodes
plus each dict node's @graph members (when @graph is a list), then reads @type from
all of them. The wrapper's own @type (often absent) and the graph members are both
covered.

**Files changed:** htmlmeta.py (_collect_jsonld), test_review_tools.py
(test_jsonld_graph_types_are_detected), README.md (333 -> 334 via --fix), BACKLOG.md
(P26 done), JSON-LD is parser-level so no builder change; JOURNAL.md (this entry).

**Verification:** an @graph script yields its members' types; a top-level @type, a
top-level list, an @type-as-list, and a wrapper-with-both all still work; malformed
JSON stays []. Scanner 333 -> 334, all green; README resynced to 334/368 (guard
exit 0).

**Learnings:** the parser was correct for the shape it was written against and
silently blind to the more common one - the same "grades what it understood, drops
what it did not" pattern as the interrupted-heading case (P29). Structured data has
a standard container (@graph) that the flat-scan missed; parsing a nested standard
means following its standard nesting, not just its top level.

**Next:** P27 (registrable_domain suffix scope breach - the last Medium), then the
Low P12/P28-P31. One Medium open, so not converged. No promise.

## 2026-07-05 - P27: keep multi-label ccTLD registrants apart in the same-site gate

**Task:** P27 (Medium, scope breach). registrable_domain knew only 13 multi-label
suffixes, so any other multi-label ccTLD suffix (com.sg, co.in, com.hk, ...)
collapsed a host to the suffix itself; crawler._eligible and discover_pages then
treated different registrants on that suffix as the same site, so on such a target
the tool would propose or fetch a third party - a breach of "only assess sites you
are authorized to".

**What I did:** added SECOND_LEVEL_LABELS ({com, co, org, net, gov, edu, ac, mil,
gob, go, ne, or}) and treat a two-letter alpha ccTLD preceded by one of them as a
public suffix, so registrable_domain returns the last three labels for com.sg /
co.in / etc. Chose the pattern over bundling a full Public Suffix List to keep the
project stdlib-only. Over-including a second-level label errs toward
too-conservative same-site (a coverage miss), never a scope escape, so the safe
direction is the default.

**Files changed:** common.py (SECOND_LEVEL_LABELS + registrable_domain heuristic),
test_review_tools.py (test_registrable_domain_keeps_multilabel_cctld_registrants_
apart), README.md (334 -> 335 via --fix), BACKLOG.md (P27 done), JOURNAL.md (this
entry).

**Verification:** com.sg/co.in/com.hk/gov.tw/com.co now keep the registrant label,
so different registrants differ and _eligible rejects a third party while a real
subdomain stays same-site; the existing .co.uk/.com/.co cases are unchanged. Scanner
334 -> 335, all green; README resynced to 335/369 (guard exit 0); no builder change.

**Learnings:** for a scope/authorization gate the error directions are not
symmetric - too-aggressive collapsing fetches an unauthorized site (unacceptable),
too-conservative merely misses a same-org page (acceptable), so the heuristic should
lean conservative on purpose. A hardcoded enum of ccTLD suffixes is unmaintainable
and was the whole bug; a structural rule (2-letter ccTLD + known second-level label)
generalizes to the ones nobody listed. The complete fix is a PSL, but the pattern
closes the realistic breach without a dependency.

**Next:** the Low tail - P12 (cap the DevTools read), P28 (button child-img alt),
P29 (dropped heading), P30 (multi-token role), P31 (cross-subdomain robots). Zero
High, zero Medium open. When the Low clear, the next full convergence audit can
certify done. No promise.

## 2026-07-05 - P12: cap the DevTools HTTP JSON read

**Task:** P12 (Low). capture_rendered._devtools_json did
json.loads(resp.read().decode(...)) - the only remote-JSON read left unbounded
after P6 capped RDAP/CrUX/DoH. Localhost DevTools of a self-launched Chrome, so no
real threat, but the last gap in the "no unbounded remote-JSON read" invariant.

**What I did:** added MAX_DEVTOOLS_BYTES = 2 MB and read resp.read(MAX_DEVTOOLS_
BYTES) before json.loads.

**Files changed:** capture_rendered.py (constant + capped read), test_review_tools.py
(test_devtools_json_read_is_capped), README.md (335 -> 336 via --fix), BACKLOG.md
(P12 done), JOURNAL.md (this entry).

**Verification:** a stubbed /json/new body parses and read is called with the cap.
Scanner 335 -> 336, all green; README resynced to 336/370 (guard exit 0); no builder
change.

**Learnings:** none new - this closes the unbounded-read class completely (every
remote-JSON read in the project is now byte-bounded), which was the point of filing
it even though the endpoint is trusted: an invariant is worth more when it has no
exceptions to remember.

**Next:** P28 (button child-img alt), P29 (dropped heading), P30 (multi-token role),
P31 (cross-subdomain robots) - the parser/crawler Low tail. Zero High, zero Medium.
No promise.

## 2026-07-05 - P28: an icon button named by a child img alt is not empty

**Task:** P28 (Low, false warn). The button-empty check counted a button with no
text and no aria-label as empty, ignoring a child `<img alt>` - the accessible name
of an icon button. So `<button><img alt="Search"></button>` incremented
buttons_empty and scan_accessibility warned "1 button(s) have no accessible text".

**What I did:** added a _button_img_alt state mirroring the anchor's
_anchor_img_alt: the img handler records a child img's alt when _cur_button is set,
and the button-close check treats text OR aria-label OR that img alt as an
accessible name. A truly empty button (or one wrapping an alt-less image) still
counts.

**Files changed:** htmlmeta.py (_button_img_alt init/reset, img capture, close
check), test_review_tools.py (test_button_accessible_name_from_child_img_alt),
README.md (336 -> 337 via --fix), BACKLOG.md (P28 done), JOURNAL.md (this entry).

**Verification:** img-alt button -> 0, alt-less-image button -> 1, text button -> 0,
aria-label button -> 0, empty button -> 1. Scanner 336 -> 337, all green; README
resynced to 337/371 (guard exit 0); no builder change.

**Learnings:** the same accessible-name-sourcing lesson as P13, now for buttons -
the parser already had the pattern for anchors (_anchor_img_alt) and just needed
the parallel for buttons. An accessible name has several valid sources; a check that
knows only some of them false-warns on the rest.

**Next:** P29 (dropped interrupted/unclosed heading), P30 (multi-token role), P31
(cross-subdomain robots). Zero High, zero Medium. No promise.

## 2026-07-05 - JOURNAL rotation

**Task:** housekeeping. JOURNAL.md passed the 500-line rotation threshold, so
the oldest entries move to JOURNAL-archive.md and the last 10 stay here.

**What I did:** moved 5 entries verbatim to JOURNAL-archive.md:
- 2026-07-04 - P18: treat DMARC pct=0 as monitoring, not full enforcement
- 2026-07-04 - P19: stop CSP false-warning strict-dynamic/nonce policies
- 2026-07-04 - JOURNAL rotation
- 2026-07-04 - P20: name every finding in the deliverable, no silent truncation
- 2026-07-04 - P21: count new/resolved by defect, not by page

**Verification:** archive is append-only and unchanged above the move;
JOURNAL.md now holds the preamble, the last 10 substantive entries, and this
rotation note. No code or state logic touched.

**Next:** P29 (dropped interrupted/unclosed heading). No promise.

## 2026-07-05 - P29: do not drop an interrupted or unclosed heading

**Task:** P29 (Low, false verdict). handle_endtag emitted a heading only on a
matching close, so a heading interrupted by another (nested) reset the buffer and
lost the outer, an unclosed heading followed by a block swallowed the body into
its buffer and never emitted, and an unclosed heading at EOF was never emitted -
each flipping scan_seo to a false "No H1 on the page." fail on a browser-renderable
page.

**What I did:** added _flush_heading() (emit the open heading, clear state) and a
HEADING_BREAKERS set of block-level tags that cannot legally sit inside a heading.
It fires on a heading start (an interrupting heading is flushed first), on a
HEADING_BREAKERS start (a block closes an unclosed heading), on a heading close
(matched or mismatched), and in an overridden close() (an unclosed heading at end
of document). Inline children (span/b/em) are phrasing content, so they never
flush and a normal heading is unchanged.

**Files changed:** htmlmeta.py (HEADING_BREAKERS, _flush_heading, close override,
start/end wiring), test_review_tools.py
(test_interrupted_or_unclosed_heading_is_not_dropped), README.md (337 -> 338 via
--fix), BACKLOG.md (P29 done; P32-P37 filed), JOURNAL.md (this entry).

**Verification:** nested h1>h2 -> both; unclosed h1 + p -> the h1; unclosed at EOF
-> the h1; inline-children heading unchanged. Scanner 337 -> 338, all green; README
resynced to 338/372 (guard exit 0).

**Replenishment (open at two after P29 - audited the last thin surfaces: the
builder's docx-rendering mechanics and common.py's utility helpers):** the builder's
score-bar math, color-map fallbacks, and JSON-null tolerance are CORRECT, as are
grade/summarize/slug_of. Three Medium and four Low filed. Medium: P32 (a string
rank mixed with the int-999 default crashes the recommendations sort, killing the
only deliverable on hand-authored data), P33 (a UTF-8 BOM - Notepad's Windows
default - defeats the TARGET.txt and .env reads, silently disabling target
resolution and the first credential; fix is encoding="utf-8-sig"). Low: P34
(orphaned progress strip), P35 (non-string scalar contract crashes), P36 (env
inline comments / export), P37 (normalize_url misreads host:port).

**Learnings:** the parser-drop pattern recurs one last time - a heading, like
@graph and the button alt, was recorded only for the shape the code expected and
silently lost otherwise. P33 is the sharpest of the batch: the tool's own primary
inputs are hand-edited on Windows, where the default editor injects a BOM, so the
happy path can fail on the very first run for a reason nothing surfaces - a codec
choice, not a logic bug. When the input is authored by a human on a known platform,
match that platform's conventions.

**Next:** P32 (rank-sort crash) then P33 (BOM), then the Low P30/P31/P34-P37. Two
Medium open, so not converged. No promise.
