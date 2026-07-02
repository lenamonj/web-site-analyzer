---
name: review-site
description: Analyze any website named in TARGET.txt or given in chat. Reviews content, design, accessibility, IA, SEO/technical, and passive security posture, then writes a full plan to planning/<slug>_GAMEPLAN.md and a CEO-level executive report to planning/<slug>_Executive_Report.docx.
---

# Website review skill

## Target resolution
1. If the user gave a URL in chat, use it. Otherwise read the first line beginning with `http` from `TARGET.txt` at the repo root.
2. Derive a slug from the host: drop the scheme and a leading `www.`, then replace dots with hyphens (example.com -> example-com). Use the slug to name both deliverables.
3. State the resolved target and the authorization assumption at the top of the gameplan.

## Deterministic evidence tools (run these first)
Before any subjective review, run the passive scanner suite. It produces hard, reproducible measurements so findings cite evidence instead of guesses. It is pure standard library (no install beyond Python) and strictly passive. From the repo root:

`python .claude/skills/review-site/tools/scan_site.py [url] [extra_page_url ...]`

With no url it reads `TARGET.txt`. Pass extra in-scope page URLs to scan them too. If `python` is not found, use `py`.

One-command alternative: `python .claude/skills/review-site/tools/run_review.py [url]` runs discovery, scans the whole proposed page set, and also writes `<slug>_exec_report_data.draft.json` in one step. Prefer it when the default scope rules apply; run the tools separately when you need to hand-pick the page set.

It writes:
- `planning/_evidence/<slug>_scan.json` - full structured results, one verdict (pass, warn, fail, info) and a note per check.
- `planning/_evidence/<slug>_scan_summary.md` - every failing check and warning in one list, ready to fold into the gameplan.

What it measures, passively, with a citable verdict per check:
- HTTP security: HTTPS redirect, HSTS, CSP, clickjacking protection, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, cookie flags, version banners, security.txt (RFC 9116).
- Page-level security hygiene: Subresource Integrity coverage on cross-origin scripts and stylesheets, forms posting to plain HTTP from an HTTPS page, inline event handlers (they block a strict CSP), target=_blank rel hygiene.
- TLS and transport: negotiated protocol, HTTP/2 support via ALPN, certificate issuer, days to expiry, hostname coverage, CAA issuance records, legacy TLS 1.0/1.1 probe.
- DNS email-auth and transport: SPF, DMARC policy, DKIM (common selectors), MX, DNSSEC, MTA-STS (record and policy mode), TLS-RPT, BIMI, over DNS-over-HTTPS.
- Crawlability (host-level, checked once per run): robots.txt presence and its sitemap references, site-wide Disallow detection (a production robots.txt blocking all crawlers is a fail), XML sitemap reachability, apex vs www canonicalization.
- SEO and on-page: title and meta-description length, canonical, viewport, robots meta, heading hierarchy, Open Graph, Twitter cards, JSON-LD structured data, hreflang, image alt.
- Accessibility (structural subset): document language and title, image alt, form labels, heading order, landmarks, link text, positive tabindex, empty buttons.
- Link health and mixed content: broken links (only 404, 410, and 5xx count as broken; 401/403/429 are reported as access-restricted, not broken), redirects, in-page anchors that point at no element id, and insecure http resources on an https page.
- Page weight and delivery: initial HTML transfer size, a static resource-weight floor, render-blocking head scripts, third-party origins, whether the HTML is served compressed (gzip/brotli), per-asset caching lifetimes, and redirect chains. JS-loaded resources are not counted, so the weight is a floor.
- Readability: Flesch Reading Ease, Flesch-Kincaid grade level, and average sentence length on the page's visible text (heuristic; inconclusive on client-rendered pages).
- Privacy and tracking (static-only): third-party resource origins, known tracker/analytics hosts, likely tracking pixels, and whether a cookie-consent mechanism is detectable in the markup.
- Design signals (static-only, complements the browser pass): favicon and theme-color declarations, deprecated presentational tags, inline-style density, distinct font families from inline and linked CSS, and images shipped without dimensions (layout-shift risk).

The scan JSON also carries a `scorecard`: each category rolled into a posture band (Strong, Adequate, Weak, Poor, or Not measured) from its own pass/warn/fail checks, plus an overall band. Use it to frame the executive summary and populate the report scorecard. It is an aggregation of measured checks, not a benchmark, so present it as such. When more than one page is scanned, the JSON also carries a `cross_page` block flagging titles or meta descriptions reused across pages. Each page is fetched and parsed once and shared across all page-level scanners, so a multi-page run stays light on the target.

Cite these results directly in findings (for example: `scan_http_security` reports CSP weakened by unsafe-inline, see `<slug>_scan.json`). Any single scanner can also be run alone, for example `python .claude/skills/review-site/tools/scan_tls.py <url>`.

Client-rendered pages: the suite detects when a page's body is injected by JavaScript and marks its structural checks inconclusive. Do not report an empty static body as a clean result.

Rendered DOM snapshots (browser pass, feeds the scanners): when a browser tool is available, upgrade those inconclusive verdicts to measured ones. For each page the scan flagged as client-rendered, load it in the browser, dismiss any cookie or region overlay, capture the full rendered document (outerHTML), and write:
- `planning/_evidence/rendered/<slug>/<name>.html` - one file per page.
- `planning/_evidence/rendered/<slug>/manifest.json` - `{"captured_with": "<tool>", "viewport": "1440px", "pages": {"<exact page url as scanned>": {"file": "<name>.html", "captured_at_utc": "<iso timestamp>"}}}`.
Then re-run `scan_site.py` (or `run_review.py`). The orchestrator picks the snapshots up automatically: every structural scanner runs against the rendered DOM (results carry `evidence_source: rendered_dom`), while performance keeps the static transfer numbers. The page url key must match the scanned url exactly. If no browser is available, say so in the gameplan; the static inconclusive verdicts stand and are never guessed.

## Scoping the review (optional helper)
To choose which pages to review, run the passive discovery tool. It reads the sitemap and homepage navigation and proposes a representative in-scope set (homepage, section landings, a couple of deep pages per section, and footer or legal pages). It fetches only the homepage and sitemaps, not the whole site.

`python .claude/skills/review-site/tools/discover_pages.py [url]`

Treat its `proposed_review_set` as a starting point, then apply the Scope rules in CLAUDE.md. Pass the chosen URLs to `scan_site.py` as extra page arguments.

## Process
1. Run the scanner suite above so the measured evidence exists before you interpret anything.
2. Fetch the target and the in-scope pages (see CLAUDE.md Scope). Use WebFetch for HTML and content; use Playwright MCP for anything visual and for screenshots at 1440px and 390px.
3. Interpret the scanner JSON for the security, TLS, DNS, SEO, and accessibility findings rather than re-deriving them by hand. Add subjective findings (content quality, visual design, IA) that the tools cannot measure.
4. Record additional evidence under `planning/_evidence/` (screenshots, page notes). Do not report Lighthouse or any measured number you did not actually measure.
5. Score every finding on two axes: Severity (Critical, High, Medium, Low) and Effort (S, M, L). Critical or High findings at S or M effort are quick wins.

## Security posture (passive only)
`scan_site.py` produces all of the following automatically. Interpret its JSON; only add manual checks it cannot make (for example mixed content, which needs a rendered page).
- HTTPS enforced, HTTP-to-HTTPS redirect, certificate validity, no mixed content.
- Security headers: HSTS, Content-Security-Policy, X-Content-Type-Options, X-Frame-Options or frame-ancestors, Referrer-Policy, Permissions-Policy.
- Cookie flags: Secure, HttpOnly, SameSite.
- Information disclosure: Server and X-Powered-By version banners, verbose error pages, source or config files linked from HTML.
- Email-auth DNS when DNS lookups are available: SPF and DMARC records present and sane.
Report only what you observed. Do not claim a specific CVE or version vulnerability unless verified against an authoritative source; otherwise flag it as unverified.

## Deliverable 1: gameplan
Write `planning/<slug>_GAMEPLAN.md` with exactly these sections:
1. Executive summary (10 lines max): the three to five things that matter most and why.
2. Scope reviewed: target, locale, date, tools used, full URL list, authorization assumption.
3. Findings by category (Content, Design, Accessibility, Navigation/IA, SEO/Technical, Security). Each finding as a row: page, observation, evidence reference, severity, effort.
4. Prioritized recommendations: ordered table (rank, recommendation, expected impact, effort, category).
5. Quick wins: the subset shippable in one sprint.
6. Strategic initiatives: larger items with dependencies.
7. Open questions and assumptions: anything needing a human decision or that you could not verify.

## Deliverable 2: executive report
1. Seed the data file mechanically, then apply judgement. Run
   `python .claude/skills/review-site/tools/draft_report_data.py planning/_evidence/<slug>_scan.json`
   (already done if you used run_review.py). It writes `<slug>_exec_report_data.draft.json` with the measured scorecard rows and fail/warn findings filled in and the judgement fields empty. Review the draft severities, rewrite the bottom line for a CEO, add recommendations and quick wins from the gameplan, and save the result as `planning/_evidence/exec_report_data.json` using this schema:
   {
     "site": "<display name, e.g. example.com>",
     "target_url": "<full URL>",
     "date": "<YYYY-MM-DD>",
     "bottom_line": "<one short paragraph, reads in under 30 seconds>",
     "scorecard": {
       "overall": "<Strong|Adequate|Weak|Poor>",
       "rows": [
         {"category": "<area, e.g. Security headers>", "band": "<Strong|Adequate|Weak|Poor|Not measured>", "detail": "<short measured detail>"}
       ]
     },
     "findings": [
       {"area": "<category>", "finding": "<what and where>", "evidence": "<page URL or _evidence ref>", "severity": "Critical|High|Medium|Low"}
     ],
     "recommendations": [
       {"rank": 1, "recommendation": "<fix>", "impact": "<expected impact>", "effort": "S|M|L"}
     ],
     "quick_wins": ["<item>", "<item>"],
     "evidence": [
       {"caption": "<what this proves>", "code": "<literal snippet>", "highlight": "<substring(s) to mark>"},
       {"caption": "<what this shows>", "image": "planning/_evidence/<screenshot>.png"}
     ]
   }
   `evidence` is optional: when present, the builder renders an appendix of captioned proof (a shaded code box with the problem substring highlighted, or an embedded screenshot). Use it only for the findings that most need showing, not for every row.
2. Run the builder from the repo root:
   `python .claude/skills/review-site/build_exec_report.py planning/_evidence/exec_report_data.json planning/<slug>_Executive_Report.docx`
   If `python` is not found, try `py`. If `python-docx` is missing, run `pip install python-docx` first.
3. Do not hand-write the docx. The builder owns formatting.

Keep the executive report tight. It should read in under two minutes: bottom line, the findings hurting the site, and the preferred fixes.

## Rules
- No em dashes or en dashes. Hyphens only.
- Every finding cites a specific page and element. No generic advice.
- Do not fabricate metrics, scores, competitor data, benchmarks, or vulnerabilities. If you did not measure it, say so.
- If visual design could not be observed, label that section structural-only in the gameplan and reflect the limitation in the executive report.
- The executive report content must be traceable to the gameplan. Do not introduce findings that are not in `planning/<slug>_GAMEPLAN.md`.
