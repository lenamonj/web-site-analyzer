# PLAN.md - Website Analyzer Design Spec

Source of truth for the analyzer's design. Amend this file; do not rewrite it
wholesale. No evaluation tool is built before it is specified here.

## 1. Standing goal
Point the analyzer at any website and produce a prioritized, evidence-backed
change plan plus a CEO-level report. The analyzer evaluates a site across
multiple independent dimensions (security, TLS, email-auth DNS, SEO, structural
accessibility, link health, page weight, readability, and later content and
visual design), rolls the measured results into a transparent scorecard, and
distills the findings into two deliverables per run:
1. `planning/<slug>_GAMEPLAN.md` - the full working plan.
2. `planning/<slug>_Executive_Report.docx` - the CEO summary.

The engineering objective of this repo (what the Ralph loop advances) is the
analyzer system itself: the passive scanner suite, the shared tool contract,
the central registry that makes tools discoverable, the orchestrator, and the
report builders. Design precedes implementation.

## 2. Design principles
- Passive only. Plain GET/HEAD, one TLS handshake, DNS-over-HTTPS. No logins,
  form posts, path brute forcing, port scans, or active probing.
- Scanners are pure Python standard library. No install beyond Python. The
  report builder may depend on `python-docx`; scanners may not.
- Deterministic and reproducible. Same input, same measured verdicts.
- No fabricated metrics. Every finding cites an observed fact. If a value was
  not measured, it is reported as unknown or inconclusive, never invented.
- Client-rendered pages are detected and their static-only checks marked
  inconclusive rather than reported as clean.
- No em dashes or en dashes anywhere in output. Hyphens only.
- Keep it simple. No speculative features, no defensive scaffolding for cases
  that cannot occur. One well-designed way to do each thing.

## 3. Current architecture (as-built)
Repo layout that matters to the analyzer:

- `TARGET.txt` - first `http` line is the default target.
- `.claude/skills/review-site/`
  - `SKILL.md` - the review process the agent follows.
  - `build_exec_report.py` - renders the docx from a JSON data file.
  - `tools/`
    - `common.py` - shared passive HTTP/TLS/DNS + IO helpers, slug and URL
      normalization, evidence dir resolution.
    - `htmlmeta.py` - one-shot page fetch, HTML parse, and client-render
      detection; the shared page snapshot every page scanner consumes.
    - `registry.py` - central tool registry (section 5).
    - `scan_http_security.py`, `scan_tls.py`, `scan_dns_email.py`,
      `scan_crawl.py` - host-scoped.
    - `scan_seo.py`, `scan_accessibility.py`, `scan_links.py`,
      `scan_performance.py`, `scan_readability.py`, `scan_privacy.py` -
      page-scoped.
    - `discover_pages.py` - passive scoping helper (sitemap + homepage nav).
    - `draft_report_data.py` - drafts exec_report_data from a scan JSON
      (section 8).
    - `run_review.py` - one-command pipeline: discover -> scan -> draft
      (section 10).
    - `scan_site.py` - orchestrator: runs host scans once and page scans per
      page, shares one fetch per page, rolls verdicts into a scorecard, runs
      cross-page checks, writes `<slug>_scan.json` and `<slug>_scan_summary.md`.
    - `test_review_tools.py` - offline unit suite (51 tests as of bootstrap).
- `planning/_evidence/` - scan JSON, summaries, screenshots, report data.

Data flow: `scan_site.run(target, extra_pages)` -> host scans + per-page scans
-> flat issue list (warn/fail) -> scorecard + cross-page -> combined result
dict -> JSON + markdown digest. The agent interprets that JSON to author the
gameplan, distills `exec_report_data.json`, then runs `build_exec_report.py`.

## 4. The shared tool contract (normative)
Every evaluation tool is a module under `tools/` that satisfies all of:

Interface
- Exposes `scan(...)` returning a dict and never raising. Failures are returned,
  not thrown. Two current shapes exist and are both valid:
  - page-scoped: `scan(url, page=None)` where `page` is a shared htmlmeta
    snapshot (`{"res","parsed","render"}`); when `None` the tool fetches once.
  - host-scoped: `scan(target)`.
- Runnable in isolation via `python scan_<x>.py <url>` with a `__main__` block.

Output on success (check-based tools)
```
{
  "tool":     "<tool id, e.g. scan_seo>", # required; equals the registry tool_id
  "target":   "<normalized url>",          # required (host tools use "host")
  "category": "<scorecard bucket>",        # stamped by the scan() wrapper (B1)
  "grade":    {"band": "...", "score": 0.0-1.0 | null, "pass": n, ...},
                                           # stamped by the scan() wrapper (B2)
  "ok":       true,                        # page tools + scan_tls emit this;
                                           # check-based host tools (http_security,
                                           # dns_email) omit it and denote success
                                           # by returning a non-empty "checks" map
  "checks": {                              # required for check-based tools
    "<check_name>": {
      "verdict": "pass" | "warn" | "fail" | "info",   # required per check
      "note":    "<one-line observed evidence>",       # required per check
      ...                                              # optional measured fields
    }
  },
  "summary": {"pass": n, "warn": n, "fail": n, "info": n}
}
```
A tool that cannot express per-check results (for example a failed TLS
handshake) may instead return a single top-level `"verdict"`.

Enforced (A2): `test_review_tools.TestToolContract` iterates the registry and
asserts, offline, that every tool returns a dict, matches its `tool_id`, has
valid per-check verdicts and notes (or a top-level verdict, or an `ok:false`
failure with a non-empty `error`), and never raises on a network failure. The
universal success invariant is "returns a non-empty `checks` map", not
"`ok:true`", because the two host check tools degrade to warn/fail verdicts
rather than failing hard.

Output on failure
```
{"tool": "<id>", "target": "<url>", "ok": false, "error": "<Type: message>"}
```

Findings and evidence: the warn and fail checks are the discrete findings; each
`note` is its evidence. Numeric grade: the posture band and 0.0-1.0 score are
derived from the measured verdicts (pass=1.0, warn=0.5, fail=0.0, info
ungraded).

Registration: the tool must be discoverable through the central registry
(section 5). The orchestrator must not hardcode tool lists.

### Contract gaps to close (drive the backlog)
1. ~~No central registry.~~ CLOSED (A1). `tools/registry.py` is the single source
   of tool discovery; `scan_site.py` builds its host set, `PAGE_SCANNERS`, and
   scorecard categories from it. Adding a tool no longer edits the orchestrator.
2. CLOSED (B1 + B2). Each scanner declares `CATEGORY`/`SCOPE` module constants;
   a thin public `scan()` wrapper stamps both `category` and its own `grade`
   (`common.grade(common.verdicts_of(result))`) onto every result, and the
   registry reads scope/category from the module. The band/score logic lives once
   in `common.grade`; `scan_site.build_scorecard` and every tool share it, so no
   band logic is duplicated. Tools are now fully self-describing per the contract
   (category + numeric grade + findings + evidence).
3. ~~The contract is not enforced by a test.~~ CLOSED (A2).
   `TestToolContract` enforces section 4 across the whole registry, offline.

## 5. Tool registry design (implemented in A1)
`tools/registry.py` is the single source of tool discovery:
- A declarative list of `ToolEntry` namedtuples, one per scanner, each carrying:
  `tool_id`, `key` (result key in the scan JSON), `module`, `scope` ("host" or
  "page"), `category` (scorecard bucket), and the short `label` used in issue
  lists. Helpers: `host_tools()`, `page_tools()`, `by_id()`.
- `scan_site.py` builds its host-scan set, `PAGE_SCANNERS`, and scorecard
  categories by reading the registry instead of importing and listing scanners
  by hand. (Done in A1.)
- Contract-conformance test (A2, done): `TestToolContract` iterates the registry
  and asserts every tool meets section 4 (callable `scan`, required keys, valid
  verdicts, surfaced category and grade, no raise on a canned page context).
Adding a dimension then means: write the scanner to the contract, add one
registry entry, add its tests. The orchestrator does not change.

## 6. Roadmap (phases)
Phase A - Foundation: central registry + contract-conformance test. Make the
existing suite conform to the standing-goal contract without changing measured
behavior. (Highest priority.)
Phase B - Self-describing tools: each tool declares its own `category` and
scope, and emits its own `grade` via a shared helper, so output is
self-contained. Registry reads metadata from the module.
Phase C - Expansion: new passive dimensions, each spec'd here first. First
dimension designed: `scan_privacy` (section 7 below; task C1 spec, C2 build).
Later candidates: basic content/IA structural checks, robots/sitemap depth.
Visual design remains a browser-assisted manual step per SKILL.md, not a scanner.
Phase D - Reporting automation: optionally generate a first-draft
`exec_report_data.json` directly from the scan JSON to cut manual transcription,
keeping the human-authored findings on top.

## 7. Design: scan_privacy (Phase C; spec C1, implemented C2)
Status: IMPLEMENTED (C2). `tools/scan_privacy.py` is registered as a page tool
(label "privacy") and appears in the scorecard as the "privacy" category. The
design below is the spec it was built to and remains the reference.
Purpose: passively surface third-party data-sharing and tracking exposure that is
visible in a page's static HTML. It answers: which third-party origins does the
page load resources from, which of those are known trackers, are there tracking
pixels, and is a cookie-consent mechanism present.

Contract conformance:
- `scope = "page"`, `CATEGORY = "privacy"`, registry `label = "privacy"`. Module
  constants `SCOPE`/`CATEGORY`; the public `scan()` wrapper stamps `category` and
  `grade` (B1/B2 pattern).
- `scan(url, page=None)`: reuse the shared htmlmeta snapshot; when `page` is None,
  fetch once via `htmlmeta.fetch_page`.
- Success returns `{tool:"scan_privacy", target, final_url, ok, render, summary,
  checks}`; fetch failure returns `{tool, target, ok:false, error}`. Register one
  page entry in `registry.py`.

Passive, static-only extraction (no JS execution, no calls to trackers):
- Resource hosts come from `<script src>` and `<iframe src>` (regex over
  `res["body"]`, the same technique as `scan_performance._script_resources`; add
  an iframe regex), plus `parsed["images"]` (src) and `parsed["links"]` (href
  where rel is in {stylesheet, preconnect, dns-prefetch, prefetch, preload}).
- `<img>` width/height are read by a small regex over the body to spot 1x1 or
  zero-dimension pixels; `parsed["images"]` does not carry dimensions, so the
  scanner owns this extraction rather than modifying the shared parser.
- Third-party = the resource host's registrable domain differs from the page's.
  Reuse `scan_dns_email.registrable_domain` (already reused by
  `scan_performance`); no Public Suffix List dependency.

Embedded reference lists (curated, small, explicit constants; a match is reported
as a factual observation, never as a fabricated score or benchmark):
- `KNOWN_TRACKERS`: map of tracker host substring -> category (analytics,
  advertising, social, session-replay), covering widely used endpoints
  (google-analytics.com, googletagmanager.com, doubleclick.net,
  connect.facebook.net, hotjar.com, segment.[io|com], mixpanel.com,
  fullstory.com, clarity.ms, bat.bing.com, and similar).
- `CMP_HOSTS`: known consent-manager hosts (cookiebot.com, cookielaw.org /
  onetrust, osano.com, trustarc.com, usercentrics, iubenda.com, cookieyes.com,
  termly.io, quantcast).
- `CONSENT_MARKERS`: id/class/text markers matched case-insensitively in the body
  ("cookie-consent", "cookie-banner", "cookie-notice", "onetrust", "cmp",
  "gdpr-consent", and similar).

Checks (each a discrete finding with a verdict and an evidence note):
1. `third_party_origins` (info): distinct third-party registrable domains found;
   note lists the count and the domains (capped). Verdict is info because a raw
   count has no authoritative threshold, so it is reported, not graded.
2. `known_trackers` (pass|warn): warn if any `KNOWN_TRACKERS` host is present,
   listing each matched host and its category; pass if none.
3. `tracking_pixels` (pass|warn): warn if any `<img>` is 1x1 / zero-dimension or
   loads from a `KNOWN_TRACKERS` host, with capped examples; pass if none. Note
   the static limitation: JS-injected pixels are not visible.
4. `cookie_consent` (pass|warn|info):
   - detected (CMP host or consent marker) -> pass, noting static detection
     cannot confirm the banner actually gates tracking before consent.
   - not detected while known trackers or third-party resources are present ->
     warn: trackers present without a detectable consent mechanism; review the
     consent obligation.
   - not detected and none present -> info.

Client-rendered pages: if `render.likely_client_rendered`, set the
resource-derived checks to info with a note that third-party resources load via
JS and are absent from static HTML (mirrors `scan_seo`/`scan_accessibility`). An
empty static body is never reported as privacy-clean.

Grade: the shared wrapper derives it from the check verdicts via `common.grade`,
so a page with known trackers and no consent grades lower, a clean page grades
Strong, and an all-info (inconclusive) page grades Not measured.

Tests (ship with C2): offline unit tests over inline HTML fixtures for
first-vs-third-party detection, known-tracker matching, 1x1 pixel detection,
CMP/marker detection, the `cookie_consent` verdict matrix, and the client-rendered
inconclusive path. `TestToolContract` covers `scan_privacy` automatically once it
is registered.

Non-goals: no JS execution, no network calls to trackers, no downloaded
blocklists, no attempt to verify actual cookie writes (a static scan cannot). The
tool reports what the static HTML reveals and labels the limitation.

## 8. Design: draft_report_data (Phase D; task D1)
Purpose: cut the manual transcription between the passive scan and the executive
report by drafting `exec_report_data.json` from `<slug>_scan.json`. It fills only
the mechanical, measured parts and leaves judgement to a human, so it never
fabricates severities, recommendations, or a narrative.

Tool: `tools/draft_report_data.py`, `draft(scan) -> dict` plus a CLI
`python draft_report_data.py <scan.json> [output.json]`. Default output is
`<slug>_exec_report_data.draft.json` in the evidence dir, a distinct name so it
never clobbers a hand-authored `exec_report_data.json`.

What it fills (all copied or derived from measured scan data):
- `site` = scan `host`; `target_url` = scan `target`; `date` = date part of
  `measured_at_utc`.
- `scorecard`: `overall` mapped to the band STRING (the builder expects a string,
  not the scan's nested dict), and one `row` per scorecard category with
  `{category, band, detail}` where detail is the measured `pass/warn/fail` counts
  and score.
- `findings`: from `issues.fail` then `issues.warn` (fails first, capped at
  MAX_FINDINGS). Each issue becomes `{area, finding, evidence, severity}`. Area
  and evidence are split from the issue's `scan` label ("label:url" -> area label
  + url; a host label -> area label + a `<slug>_scan.json` reference). Severity is
  a transparent DRAFT default (fail -> High, warn -> Medium) for a human to
  adjust; this is a stated mapping, not a fabricated score.
- `bottom_line`: a factual, measured one-liner explicitly prefixed "DRAFT
  (rewrite for the CEO)" so no invented narrative ships by accident.

What it leaves empty for the human: `recommendations` and `quick_wins` (both
`[]`). `build_exec_report.py` uses `data.get(...)` with defaults and skips empty
sections, so a draft renders cleanly and the human layers judgement on top.

Non-goals: no severity/priority inference beyond the stated fail/warn default, no
recommendation text, no competitor or benchmark data. The generator is a
transcription aid, not an analyst.

Tests (ship with D1): offline unit tests over a synthetic scan dict for the
top-level fields, the overall-band-as-string mapping, the findings severity and
evidence mapping and ordering, and schema completeness; plus a smoke run that
drafts from a real `<slug>_scan.json` and renders it through
`build_exec_report.py`.

## 9. Design: scan_crawl (host-scoped robots.txt and sitemap checks)
Problem: robots.txt and sitemap.xml are host-level facts, but their checks lived
inside the page-scoped `scan_seo`. A multi-page run therefore refetched both
files once per page (needless load on the target), repeated the identical
warning once per page in the issue list and digest, and let those repeated
verdicts skew the seo category grade by page count.

Tool: `tools/scan_crawl.py`, host-scoped (`SCOPE = "host"`), registered with
key `crawl` and label `crawl`. `CATEGORY = "seo"`: robots and sitemap remain
SEO facts, so their verdicts roll into the existing seo scorecard bucket. This
relies on the scorecard bucketing fix below.

Behavior: `scan(target)` resolves the final base URL with one redirect-following
fetch (HEAD-like, no body), then runs exactly the two checks that moved out of
`scan_seo`:
1. `robots_txt` (pass|warn|info): pass when /robots.txt answers 200 with a
   user-agent line; info when the fetch itself failed (network error is not
   evidence of a missing file); warn otherwise. Reports referenced sitemap URLs.
2. `sitemap` (pass|warn|info): pass when the first robots-referenced sitemap
   (or /sitemap.xml) is a 200 with a urlset or sitemapindex root; info on fetch
   failure; warn otherwise.
`scan_seo` drops its robots_txt and sitemap checks and no longer takes any
host-level action. Contract, wrapper stamping, registry entry, and tests follow
the section 4/5 pattern; `TestToolContract` covers it automatically.

Scorecard bucketing fix (orchestrator): `build_scorecard` previously bucketed
host tools by `category` but page tools by `key`, and a page bucket would
silently overwrite a host bucket with the same name. It now buckets both scopes
by `category` and merges verdict lists, so any number of tools can share a
scorecard category (as scan_crawl and scan_seo now share "seo").

## 10. Design: run_review (one-command pipeline)
Purpose: collapse the three manual steps (discover, scan, draft) into one
deterministic command so a full evidence pass is a single invocation:

`python tools/run_review.py [url]`  (no url: TARGET.txt)

Behavior: run `discover_pages.discover(target)`; take its
`proposed_review_set` (falling back to just the target when discovery fails or
proposes nothing); run `scan_site.run(target, extra_pages)`; write the scan
JSON and markdown digest exactly as `scan_site.main` does; then write
`<slug>_exec_report_data.draft.json` via `draft_report_data.draft`. Prints the
same console summary as scan_site plus the paths written. Judgement steps
(gameplan authoring, severity review, recommendations, final docx) remain with
the agent per SKILL.md. Not a scanner: it is not registered and has no
category; it only composes registered tools. An offline integration test stubs
the network primitives and asserts the pipeline writes all three artifacts.

## 11. Concurrency in fan-out scanners
`scan_links` (up to 30 link probes) and `scan_performance` (up to 40 resource
HEADs) previously ran their fan-out serially; with an 8s timeout a page with
dead links could take minutes. Both now run their batch through a bounded
`concurrent.futures.ThreadPoolExecutor` (max 8 workers, stdlib only).
`executor.map` preserves input order, so output ordering and verdicts stay
deterministic. Eight concurrent requests is comparable to a normal browser's
per-host connection pool, so the run remains polite to the target.

## 12. Design: executive report document design (task F1)
Directive (user, 2026-07-02): the executive report was visually weak; it must
look professional, board-ready. The builder owns all formatting (output
contract), so the redesign lives entirely in `build_exec_report.py` and the
JSON data contract is unchanged: the same keys (site, target_url, date,
bottom_line, scorecard{overall, rows}, findings, recommendations, quick_wins,
evidence) render in both hand-authored and machine-drafted form.

Document design system:
- One accent navy (0B1F3A) plus a muted, print-safe semantic palette:
  Strong/Low 1E7B4F, Adequate/Medium E2A800 (dark text for contrast),
  Weak CB6120, Poor B3261E, Critical 7F1D1D, Not measured 8A94A6. A thin gold
  rule (C9A227) under the masthead. Hairlines D8DEE9. Calibri body, Consolas
  code. No em or en dashes anywhere.
- Masthead: full-width navy banner (kicker, site name at 25pt, url | date
  line), built as a shaded 1x1 table so it renders identically everywhere.
- At-a-glance tile strip: four tiles (overall posture, findings count with a
  severity breakdown, recommendations count, areas measured), every value
  copied or counted from the data, nothing invented.
- Bottom line: shaded callout with a navy left bar.
- Tables: navy header row, horizontal hairlines only (no full grid), roomy
  cell margins via tblCellMar, vertical centering, header row repeats across
  pages, rows do not split. Posture and severity render as color chips.
- Footer: hairline rule, "<site> Website Review" left, "Page N" right via a
  real PAGE field.
- Evidence appendix: numbered exhibits ("Exhibit N."), full-width images,
  bordered code blocks with the exact problem substring highlighted.

Tests: `test_exec_report.py` (next to the builder; requires python-docx,
skips if absent) builds from a synthetic dict and asserts masthead, tile
counts, chip fills, severity ordering, rank ordering, footer PAGE field,
exhibit numbering, and that a minimal data dict renders without the optional
sections. Visual verification: render the two real evidence datasets and
inspect the PDF (Word COM export).

## 13. Design: security depth (task F2)
Purpose: close the gaps between the current header-only security view and what
a world-class passive analyzer reports. Three additions, all passive.

1. `security_txt` check added to `scan_http_security` (host scope): one GET to
   `/.well-known/security.txt` (RFC 9116, a standardized well-known URI like
   robots.txt, not path guessing). 200 with a `Contact:` line -> pass; fetch
   failure -> info (network failure is not evidence of absence); otherwise ->
   info noting it is not published (adoption is low, so absence is reported as
   an observation, not graded down).
2. New page-scoped tool `scan_page_security` (`CATEGORY = "security"`; the
   scorecard merges it with the host header checks since categories merge by
   name per section 9). Checks, all from static HTML:
   - `subresource_integrity` (pass|warn|info): cross-origin `<script src>` and
     `<link rel=stylesheet>` without an `integrity` attribute -> warn with
     counts and capped examples; all covered -> pass; none cross-origin or
     client-rendered -> info.
   - `insecure_form_action` (pass|fail|info): a `<form action="http://...">`
     on an HTTPS page -> fail (credentials or PII would leave over plaintext);
     none -> pass; no forms or client-rendered -> info.
   - `inline_event_handlers` (info): count of `on<event>=` attributes in the
     markup; reported because they block a strict CSP. Observation only.
   - `target_blank_rel` (pass|info): `<a target="_blank">` without
     `rel=noopener|noreferrer` -> info with count (modern browsers imply
     noopener, so this is hygiene, not a graded fault); otherwise pass.
   Client-rendered pages mark the markup-derived checks info (section 2 rule).
   Extraction reuses the existing regex approach over `res["body"]` plus
   `parsed` anchors/links; form/script/link attr regexes live in this module.
3. `caa` check added to `scan_tls` (host scope): one DoH query for the CAA
   record of the registrable domain (reuses `common.doh_query` and
   `scan_dns_email.registrable_domain`). Records present -> pass listing the
   authorized CAs; none -> info (absence is common and only an observation);
   query failure -> info.

Registration: one `_entry` for `scan_page_security` in the registry; the two
check additions ride inside existing tools. Tests: offline fixtures for SRI
present/absent/cross-origin-only, http form action on https page, inline
handler counting, target_blank rel matrix, security.txt parse, CAA
present/absent; `TestToolContract` picks up the new tool automatically.

## 14. Design: architecture and caching depth (task F3)
Purpose: measure the delivery-architecture facts a world-class analyzer should
report beyond raw page weight. Three additions, no new tool.

1. `asset_caching` check in `scan_performance` (page scope): `_measure`
   already HEADs each declared resource; it now also captures the resource's
   Cache-Control header. Static assets (scripts, stylesheets, images) that
   answered 200 are graded: an asset with no Cache-Control, no max-age, or
   max-age 0 is uncached. More than half of measured assets uncached -> warn
   with capped examples; otherwise pass with counts; nothing measured or
   client-rendered -> info. The HTML document's own caching stays the separate
   info-only `caching` check (no universal right answer for documents).
2. `redirect_chain` check in `scan_performance` (page scope): the shared page
   fetch already records every hop. Two or more redirects before the final
   URL -> warn (each hop adds a full round trip before first byte); one -> pass
   noting the hop; zero -> pass.
3. `host_canonicalization` check in `scan_crawl` (host scope, category seo):
   apex vs www duplicate-site risk. Applies only when the target host is the
   registrable apex or www.<apex>; anything else (a real subdomain site) is
   info not-applicable. Fetch both `https://<apex>` and `https://www.<apex>`
   (HEAD-style, no body): if both answer 200 on different final hosts with no
   redirect between them -> warn (two live versions of the site split link
   equity and confuse crawlers); if one side redirects to the other (or both
   land on one final host) -> pass; if one side is unreachable -> info (that
   variant does not resolve; not evidence of a fault).

Tests: cache-control parsing and the uncached-majority matrix, redirect-chain
verdicts from synthetic hop lists, and the canonicalization matrix (redirect,
both-live, unreachable variant, subdomain not-applicable) with stubbed
fetches. `TestToolContract` is unaffected (no new tool).

## 15. Design: static design-signal scanner (task F4)
Purpose: give the analyzer a measured "design" dimension from static HTML and
declared CSS, complementing (not replacing) the browser-based visual pass in
SKILL.md. New page tool `scan_design.py`, `CATEGORY = "design"`,
`SCOPE = "page"`, registered as the 12th tool; the scorecard gains a design
category. All checks are objective, countable facts; no aesthetic judgement is
fabricated.

Checks:
1. `favicon` (pass|warn|info): a `<link rel>` containing icon (icon, shortcut
   icon, apple-touch-icon) -> pass; none in a server-rendered page -> warn (a
   missing tab/bookmark icon is a visible polish gap); client-rendered ->
   info.
2. `theme_color` (pass|info): `<meta name=theme-color>` present -> pass, else
   info (observation only; mobile browser chrome tinting).
3. `deprecated_presentational_tags` (pass|warn): any `<font> <center>
   <marquee> <blink> <frameset> <frame> <big> <strike>` -> warn with per-tag
   counts (they defeat responsive, consistent styling); none -> pass.
4. `inline_style_density` (pass|warn|info): count of `style=` attributes; over
   30 on one page -> warn (styling is escaping the design system; consistency
   and maintenance risk); 1-30 -> pass with the count; zero -> pass.
5. `font_families` (pass|warn|info): distinct font-family stems declared in
   inline `<style>` blocks plus up to 5 declared same-page stylesheets
   (passive GET, body cap applies, failures skipped silently as info). Over 4
   distinct families -> warn (typographic inconsistency); 1-4 -> pass listing
   them; none found -> info. Generic families (serif, sans-serif, monospace,
   system-ui, inherit) and font stacks after the first name are not counted.
6. `image_dimensions` (pass|warn|info): `<img>` tags in static HTML missing
   both width/height attributes (and no style with width/height) shift layout
   as they load. More than half missing -> warn with capped examples;
   otherwise pass; no images or client-rendered -> info.

Client-rendered pages: all markup-derived checks -> info (section 2 rule).
Extraction: regex over the raw body for tags/attributes (same technique as
scan_privacy/scan_page_security), `parsed["links"]` for stylesheet hrefs and
icon rels, one bounded fetch loop for CSS. Tests: fixtures per check plus the
client-rendered path and a stubbed-CSS font-family extraction test;
`TestToolContract` covers the new tool automatically.

## 16. Design: per-run fetch cache (task F5)
Problem: within one multi-page run the same URL is fetched repeatedly - the
nav links that appear on every page are re-probed by scan_links per page, a
shared stylesheet or script is re-HEADed by scan_performance and re-read by
scan_design per page, and robots.txt is read by both discover_pages and
scan_crawl. That wastes runtime and puts needless load on the target,
violating the politeness principle.

Design: a process-wide memo cache inside `common.http_fetch`, explicitly
enabled per run.
- `common.enable_fetch_cache()` turns it on and clears it;
  `common.disable_fetch_cache()` turns it off and clears it. Off by default,
  so standalone single-scanner runs and existing tests see today's behavior
  unless they opt in.
- Key: `(method, normalized url, want_body)`. A GET with a body satisfies
  nothing else; HEAD and GET stay distinct entries (a HEAD hit must not stand
  in for a GET body request).
- Only successful, complete responses are cached (`final_status` not None).
  Failures are never cached, so a transient error on page A does not poison
  page B.
- Thread safe (a `threading.Lock` around the dict) because scan_links and
  scan_performance call http_fetch from a ThreadPoolExecutor.
- Bounded: at most 512 entries; when full, new results are returned uncached
  (no eviction complexity; a run never legitimately needs more).
- Callers: `scan_site.run` and `run_review.pipeline` enable it at start and
  disable it in a finally block. Nothing else changes; every tool transparently
  benefits.
- Staleness is not a concern: a run is one short observation window, and
  reusing one observation of an unchanged URL within it is exactly the
  "fetched and parsed once" principle already applied to pages.

Tests: cache hit returns the identical dict for a repeated GET; HEAD and GET
do not cross-satisfy; failures are not cached; disable clears; scan_site.run
leaves the cache disabled afterward.

## 17. Design: header analysis depth (task F6)
Purpose: the CSP and cookie checks in `scan_http_security` grade only the
shallowest signal. Deepen both with defensible, evidence-based verdicts; no
new tool, no new fetches.

1. `check_csp` parses the policy into directives and grades:
   - absent -> warn (unchanged).
   - delivered only as `Content-Security-Policy-Report-Only` -> warn: the
     policy is monitoring, not enforcing.
   - no `script-src` and no `default-src` fallback -> warn: scripts are
     unrestricted, which defeats the header's XSS purpose.
   - a wildcard `*` source (or `http:`/`https:` scheme-wide source) in
     `script-src` (or in `default-src` when script-src is absent) -> warn:
     any origin may serve script.
   - `unsafe-inline` / `unsafe-eval` in script-effective directives -> warn
     (existing behavior, now scoped to the script-effective directive rather
     than the whole header, so unsafe-inline in style-src alone downgrades to
     a note, not a warn).
   - otherwise pass, reporting the parsed script-src sources.
   Multiple findings combine into one warn with all reasons in the note.
2. `check_cookies` additionally treats a missing or `SameSite=None` cookie as
   a finding: missing SameSite -> the browser default (Lax) applies but the
   intent is undeclared; `SameSite=None` without `Secure` is rejected by
   browsers. Verdicts: any cookie missing Secure/HttpOnly stays warn (the
   stronger finding); otherwise cookies lacking SameSite -> warn with a
   distinct note; all cookies carrying Secure+HttpOnly+SameSite -> pass.

Tests: directive parsing (quoted policy strings), the report-only path, the
no-script-directive path, wildcard sources, unsafe-inline scoped to
script-src vs style-src, SameSite matrix including None-without-Secure.

## 18. Design: email transport posture (task F7)
Purpose: complete the dns_email dimension to the level of dedicated posture
tools. Three checks added to `scan_dns_email`, all passive:

1. `mta_sts` (pass|info): TXT lookup on `_mta-sts.<domain>` for `v=STSv1`;
   when present, one GET to `https://mta-sts.<domain>/.well-known/mta-sts.txt`
   (a standardized well-known URI) to confirm the policy file answers and
   report its mode (enforce/testing/none). Record plus readable policy in
   enforce mode -> pass; record with testing/none or an unreachable policy
   file -> info with the specific gap; no record -> info (adoption is
   minority; absence is an observation, consistent with security.txt/CAA).
2. `tls_rpt` (pass|info): TXT on `_smtp._tls.<domain>` for `v=TLSRPTv1` ->
   pass listing the rua; absent -> info.
3. `bimi` (pass|info): TXT on `default._bimi.<domain>` for `v=BIMI1` -> pass
   noting the logo URL presence; absent -> info.
All three are skipped with an info note when the domain has no MX records
(a domain that receives no mail has no transport posture to grade).

Tests: stubbed DoH/fetch for the record-present, policy-mode, and absent
paths, plus the no-MX skip.

## 19. Design: robots disallow-all and in-page anchor integrity (task F8)
1. `scan_crawl.check_robots_txt` additionally parses the `User-agent: *`
   group: a bare `Disallow: /` in that group (and no bare `Allow: /`) means
   the site tells every crawler to stay out entirely -> the check becomes
   fail with the offending lines quoted (on a production site this is an SEO
   catastrophe; presence-only checking missed it completely).
2. In-page anchor integrity, in `scan_links` (new check `anchor_fragments`):
   `htmlmeta` collects every element `id` (plus legacy `<a name>`) into
   `parsed["ids"]`; anchors whose href is `#fragment` (excluding bare `#`)
   are resolved against that set. Any unresolved fragment -> warn with capped
   examples (the link scrolls nowhere); all resolved -> pass; none or
   client-rendered -> info. Fragments in full URLs pointing at other pages
   are out of scope (cannot be verified without fetching the target's ids).

Tests: robots group parsing (global disallow, path-scoped disallow stays
warn-free, disallow in a non-* group ignored), id collection including
`<a name>`, and the fragment matrix (resolved, missing, bare `#`,
client-rendered).

## 20. Design: issue aggregation (task F9)
Problem: page-scoped checks emit one identical issue per affected page. A
site-wide template defect therefore repeats through the digest, and because
`draft_report_data` caps findings at 15, one such defect floods every slot
and crowds all other findings out of the executive draft.

Design: a pure `scan_site.group_issues(issues)` groups the flat issue list by
(tool label, check, verdict); the "label:url" convention already separates
label and page. Each group keeps the first note as representative, the list
of affected pages, and a page_count. Host issues pass through with no pages.
The combined JSON gains `issues_grouped` = {fail: [...], warn: [...]} while
the raw per-page `issues` stay for evidence fidelity; `totals` gains grouped
counts. The digest renders grouped entries ("note (on N pages: url1, url2,
+K more)"). `draft_report_data` consumes `issues_grouped` when present (raw
`issues` as fallback for old scan files), so one template defect is one
finding whose evidence names the affected pages.

Tests: grouping across pages, host pass-through, distinct verdicts kept
apart, representative note, digest rendering, draft consumption of grouped
issues plus the old-scan fallback.

## 21. Design: run-over-run delta (task F10)
Purpose: the tool's real usage loop is scan, fix, re-scan. Make the re-scan
state the change: which issues are new since the previous run and which were
resolved.

Design: a pure `scan_site.diff_issues(prev_result, result)` compares the
(scan, check, verdict) key sets of both runs' raw issues and returns
{previous_measured_at, new: [current issue dicts], resolved: [previous issue
dicts]}. The writers (`scan_site.main`, `run_review.pipeline`) load the
existing `<slug>_scan.json` before overwriting it and attach the diff as
`result["delta"]`; a first run has no delta. The digest gains a "Changes
since previous scan" section listing new and resolved issues. No history
archive: one previous run is the comparison window, deliberately simple.

Tests: the pure diff (new, resolved, unchanged, first-run None), and the
writer path attaching a delta when a previous JSON exists (tmp dir).

## 22. Design: HTTP/2 detection via ALPN (task F11)
Purpose: whether the server offers HTTP/2 is a real delivery-architecture
fact (multiplexing, header compression) and is visible passively in the TLS
handshake the analyzer already performs. `common.tls_info` offers
`["h2", "http/1.1"]` via ALPN and reports `alpn` = the negotiated protocol.
`scan_tls` gains a `http2` check: `h2` negotiated -> pass; anything else
(http/1.1 or no ALPN) -> warn, because requests then serialize per
connection. No extra network traffic: it rides the existing handshake.
Tests: stubbed tls_info with alpn h2 / http1.1 / absent.

## 23. Design: parallel DKIM selector probes (task F12)
`check_dkim` queries 14 selectors serially (14 round trips to the DoH
resolver on every scan). Run them through the same bounded
ThreadPoolExecutor pattern as the fan-out scanners (section 11), max 8
workers, `executor.map` preserving selector order so output stays
deterministic. Behavior unchanged; existing tests cover it.

## 24. Design: DKIM selector families (task G1)
Problem: the probe list covers provider-name selectors (selector1/2, google,
k1, s1...) but misses the date-based selectors large providers rotate, so a
domain signed only with a Google 20230601-style key reports "not found on
probed selectors".

Design: extend DKIM_SELECTORS with documented, published selector names only
(no invented guesses, no unbounded date generation):
- Google date rotation: 20230601, 20161025, 20120113.
- Yahoo key sizes: s1024, s2048.
- Fastmail: fm1, fm2, fm3.
- Proton Mail: protonmail, protonmail2, protonmail3.
- Zoho: zoho.
26 selectors total, still probed through the bounded parallel fan-out (F12),
so wall-clock stays flat. The absence note keeps its honest caveat (random
per-account selectors like Amazon SES tokens are unguessable by design) and
now names the probed families. Tests: the new selectors are present in the
probe list, a stubbed hit on a date selector is reported, and the absence
note still carries the caveat. Live verification: gmail.com publishes
20230601._domainkey and must be found.

## 25. Design: tracker list depth (task G2)
Problem: KNOWN_TRACKERS held about two dozen entries, so common trackers
(Criteo, Xandr, Adobe Analytics, Taboola, LiveRamp, session-replay vendors
beyond the top four) loaded without being named.

Design: expand the embedded constants to roughly 150 widely documented
tracker registrable domains, grouped and commented by function: analytics,
advertising/ad-tech (SSPs, DSPs, identity/data brokers, verification),
social widgets, session replay, marketing automation and attribution, and
A/B testing. Sources are the well-known public tracker datasets
(EasyPrivacy, DuckDuckGo Tracker Radar, Ghostery/WhoTracksMe classes of
list); only domains whose tracking function is publicly documented are
included, still explicit constants in the module, no downloads at runtime.
Matching stays exact-or-subdomain via _host_matches (no substring
lookalikes). A match remains a factual observation ("this known host is
referenced"), never a score. CMP_HOSTS gains the widely deployed consent
platforms (Didomi, Sourcepoint, consentmanager, IAB consensu.org,
CookieHub, CookieFirst, Cookie-Script, Civic) and CONSENT_MARKERS the
matching DOM markers (didomi, usercentrics, cmplz, borlabs-cookie, truste).

Tests: representative new entries match by exact and subdomain host, the
lookalike guard still rejects notfacebook.com-style hosts, expanded CMP and
marker detection, and a count floor so an accidental list truncation fails
the suite.

## 26. Design: rendered-evidence pipeline, part 1 (task G3)
Problem: on client-rendered pages the structural scanners honestly report
"inconclusive", which is correct but shallow: the browser-built DOM is
knowable when a browser tool is available to the agent.

Handoff format (capture side, performed by the agent per SKILL.md, not by
the scanners): for each page the scan flagged likely_client_rendered, the
agent captures the rendered document (outerHTML after load and overlay
dismissal) and writes:
- `planning/_evidence/rendered/<slug>/<file>.html` - one file per page.
- `planning/_evidence/rendered/<slug>/manifest.json` - {"captured_with":
  tool name, "viewport": "1440px", "pages": {"<page url>": {"file":
  "<file>.html", "captured_at_utc": "..."}}}.
The scanners never launch a browser (stdlib-only rule); when no snapshot
exists the static inconclusive verdicts stand. Nothing is ever inferred
about a page without a capture.

Tool-side consumption:
- `htmlmeta.page_from_snapshot(url, html, network_res)` builds a page
  context from the snapshot: network facts (status, headers, final_url) stay
  from the live fetch, the body is the rendered DOM, and the render
  assessment is stamped `source = "rendered_dom_snapshot"`.
- `scan_site.load_rendered_snapshots(slug)` reads the manifest and returns
  url -> rendered HTML (missing or unreadable manifest -> empty, silently:
  absence of snapshots is the normal case).
- In the per-page loop, when a page is likely_client_rendered AND a snapshot
  exists, every page scanner except scan_performance receives the snapshot
  context (performance numbers are network-transfer facts and stay static);
  each result produced from a snapshot is stamped
  `evidence_source = "rendered_dom"` and the page entry records
  `rendered_snapshot_used`. The digest header states how many pages used
  rendered evidence.

Tests: snapshot context construction, manifest loading (present, missing,
malformed), and an orchestrated run where a canned SPA shell plus a snapshot
yields measured seo verdicts stamped rendered_dom while performance stays
static. Live capture is the agent's step and is not simulated in tests.

## 27. Design: rendered-evidence pipeline, part 2 - web vitals and contrast (task G4)
Purpose: the static floor cannot see LCP, CLS, TBT, or color contrast. The
agent's browser pass can measure all four in the loaded page (the same
computed-style approach axe-core uses for contrast, and the standard
PerformanceObserver APIs for the vitals) and hand the numbers to a scanner.

Handoff (capture side, agent per SKILL.md and tools/CAPTURE.md):
`planning/_evidence/rendered/<slug>/metrics.json`:
{"captured_with": "<tool>", "viewport": "1440px", "pages": {"<url>": {
  "lcp_ms": int|null, "cls": float|null, "tbt_ms": int|null,
  "contrast": {"checked": int, "violations": [{"sample": "<text or
  selector>", "ratio": float, "required": float}]} | null,
  "captured_at_utc": "..."}}}
CAPTURE.md carries the exact JS snippets (buffered PerformanceObserver for
largest-contentful-paint, layout-shift excluding hadRecentInput, longtask
with the 50ms TBT subtraction; computed-style WCAG contrast walk). Metrics
are lab measurements of one load and are labeled as such.

Tool side: new registered page tool `scan_vitals.py` (13th tool,
CATEGORY = "performance" so it merges into the performance bucket, label
"vitals"). scan(url, page=None) derives the slug from the url host and reads
the metrics file; the page context is unused because the numbers come from
the capture. Checks, graded against the published Core Web Vitals and
Lighthouse thresholds (web.dev: LCP 2.5s/4.0s, CLS 0.1/0.25, TBT
200ms/600ms):
- lcp: pass <= 2500 ms, warn <= 4000, fail above; info when not captured.
- cls: pass <= 0.1, warn <= 0.25, fail above; info when not captured.
- tbt: pass <= 200 ms, warn <= 600, fail above; info when not captured.
- contrast (WCAG 1.4.3): violations present -> fail with count and capped
  examples; checked with zero violations -> pass; not captured -> info.
No capture file -> every check info ("run the browser pass"), grade Not
measured. Nothing is estimated; the tool only reports what the browser
measured. Tests: threshold matrix per metric, contrast pass/fail, the
not-captured path, slug/url lookup, and the registry census (9 page tools).

## 28. Open design questions
- Should `scan` signatures be unified to a single `scan(url, *, page=None,
  scope=...)` form, or is the host vs page split kept? (Leaning: keep the split,
  let the registry carry scope, avoid churn.)
- Where should per-tool `grade` live so the central scorecard stays the single
  aggregation point without duplicating the band logic? (Leaning: shared helper
  in `common.py` used by both tool and orchestrator.)
- Git has no remote. The loop commits locally; pushing is deferred until a
  remote is configured. Recorded so no iteration silently assumes a push
  succeeded.
