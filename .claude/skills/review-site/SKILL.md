---
name: review-site
description: Analyze any website named in TARGET.txt or given in chat. Reviews content, design, accessibility, IA, SEO/technical, and passive security posture, then delivers one file, the CEO-level executive report at planning/<slug>_Executive_Report.docx.
---

# Website review skill

## Target resolution
1. If the user gave a URL in chat, use it. Otherwise read the first line beginning with `http` from `TARGET.txt` at the repo root.
2. Derive a slug from the host: drop the scheme and a leading `www.`, then replace dots with hyphens (example.com -> example-com). Use the slug to name both deliverables.
3. State the resolved target and the authorization assumption in chat when the review starts.

## Deterministic evidence tools (run these first)
Before any subjective review, run the passive scanner suite. It produces hard, reproducible measurements so findings cite evidence instead of guesses. It is pure standard library (no install beyond Python) and strictly passive. From the repo root:

`python .claude/skills/review-site/tools/scan_site.py [url] [extra_page_url ...]`

With no url it reads `TARGET.txt`. Pass extra in-scope page URLs to scan them too. If `python` is not found, use `py`.

One-command alternative: `python .claude/skills/review-site/tools/run_review.py [url]` runs discovery, scans the whole proposed page set, and also writes `<slug>_exec_report_data.draft.json` in one step. Prefer it when the default scope rules apply; run the tools separately when you need to hand-pick the page set.

Wide reviews (only when the user explicitly asks): add `--crawl N` to run_review to replace sampled discovery with a polite breadth-first crawl of up to N same-domain pages (robots.txt compliant including Crawl-delay, strictly serial with a per-request delay, hard 500-page ceiling, resumable via `<slug>_crawl_state.json`; `--fresh` discards saved state). The authorization rules apply unchanged.

It writes:
- `planning/_evidence/<slug>_scan.json` - full structured results, one verdict (pass, warn, fail, info) and a note per check.
- `planning/_evidence/<slug>_scan_summary.md` - every failing check and warning in one list, ready to fold into the report.

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
- Real-user field data (when GOOGLE_API_KEY is set): the origin's p75 LCP, CLS, and INP from the Chrome UX Report, graded against the published Core Web Vitals thresholds. Absent key, insufficient origin traffic, or an unauthorized API all degrade to labeled info, never a guess.

The scan JSON also carries a `scorecard`: each category rolled into a posture band (Strong, Adequate, Weak, Poor, or Not measured) from its own pass/warn/fail checks, plus an overall band. Use it to frame the executive summary and populate the report scorecard. It is an aggregation of measured checks, not a benchmark, so present it as such. When more than one page is scanned, the JSON also carries a `cross_page` block flagging titles or meta descriptions reused across pages. Each page is fetched and parsed once and shared across all page-level scanners, so a multi-page run stays light on the target.

Cite these results directly in findings (for example: `scan_http_security` reports CSP weakened by unsafe-inline, see `<slug>_scan.json`). Any single scanner can also be run alone, for example `python .claude/skills/review-site/tools/scan_tls.py <url>`.

Client-rendered pages: the suite detects when a page's body is injected by JavaScript and marks its structural checks inconclusive. Do not report an empty static body as a clean result.

Automated rendered capture (default): `run_review.py` performs the whole rendered-evidence pass by itself when a local Chrome or Edge is installed (PLAN.md section 34). After the first scan it runs `tools/capture_rendered.py`, which drives the browser headless over the DevTools protocol, refreshes a DOM snapshot for every client-rendered page, measures LCP/CLS/TBT and WCAG contrast for every scanned page (capped, dropped pages named), writes the manifest/metrics handoff files below, and re-scans so the same run consumes them. `--no-browser` skips it; when no browser is found the console says so and the static inconclusive verdicts stand. The automated capture does not dismiss cookie or region overlays; `captured_with` records that. Use the manual browser pass below when an overlay blocks the content or a page needs interaction before capture.

Rendered DOM snapshots (manual browser pass, same handoff): when a browser tool is available to you and the automated capture was not enough, upgrade inconclusive verdicts by hand. For each page the scan flagged as client-rendered, load it in the browser, dismiss any cookie or region overlay, capture the full rendered document (outerHTML), and write:
- `planning/_evidence/rendered/<slug>/<name>.html` - one file per page.
- `planning/_evidence/rendered/<slug>/manifest.json` - `{"captured_with": "<tool>", "viewport": "1440px", "pages": {"<exact page url as scanned>": {"file": "<name>.html", "captured_at_utc": "<iso timestamp>"}}}`.
Then re-run `scan_site.py` (or `run_review.py`). The orchestrator picks the snapshots up automatically: every structural scanner runs against the rendered DOM (results carry `evidence_source: rendered_dom`), while performance keeps the static transfer numbers. The page url key must match the scanned url exactly. If no browser is available, say so in chat and in the report's scope line; the static inconclusive verdicts stand and are never guessed.

Web vitals and contrast (browser pass, feeds scan_vitals): in the same browser session, run the measurement snippets in `tools/CAPTURE.md` (buffered PerformanceObserver for LCP/CLS/TBT; the computed-style WCAG contrast walk) and write `planning/_evidence/rendered/<slug>/metrics.json` per the schema there. The next scan grades them against the published Core Web Vitals and Lighthouse thresholds. Metrics are lab measurements of one load; scan_vitals labels them as such and reports "not captured" when absent.

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

## The deliverable: the executive report
The docx is the only deliverable. Everything else the run writes (scan JSON,
digest, draft data, history ledger, screenshots) is internal working material
under `planning/_evidence/`.

1. Seed the data file mechanically, then apply judgement. Run
   `python .claude/skills/review-site/tools/draft_report_data.py planning/_evidence/<slug>_scan.json`
   (already done if you used run_review.py). It writes `<slug>_exec_report_data.draft.json` with the measured scorecard, executive summary (strengths and weaknesses), web vitals, findings, and a prioritized action plan filled in from measured data. Review the draft severities, sharpen the bottom line for a CEO, replace the auto action plan with authored recommendations where judgement improves on it, attach evidence exhibits for the findings that most need proof, and save the result as `planning/_evidence/exec_report_data.json` using this schema:
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
- If visual design could not be observed, reflect that limitation in the executive report's scope line.
- Every report finding must be traceable to the scan JSON or to recorded evidence under `planning/_evidence/`. Do not introduce findings that have no measured or captured source.
