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
    - `scan_http_security.py`, `scan_tls.py`, `scan_dns_email.py` - host-scoped.
    - `scan_seo.py`, `scan_accessibility.py`, `scan_links.py`,
      `scan_performance.py`, `scan_readability.py` - page-scoped.
    - `discover_pages.py` - passive scoping helper (sitemap + homepage nav).
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

## 8. Open design questions
- Should `scan` signatures be unified to a single `scan(url, *, page=None,
  scope=...)` form, or is the host vs page split kept? (Leaning: keep the split,
  let the registry carry scope, avoid churn.)
- Where should per-tool `grade` live so the central scorecard stays the single
  aggregation point without duplicating the band logic? (Leaning: shared helper
  in `common.py` used by both tool and orchestrator.)
- Git has no remote. The loop commits locally; pushing is deferred until a
  remote is configured. Recorded so no iteration silently assumes a push
  succeeded.
