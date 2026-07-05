# Website Review Project

## Purpose
Point this at any website and produce one deliverable per run:
`planning/<slug>_Executive_Report.docx` - a CEO-level Word report with the
measured scorecard, an executive summary of strengths and weaknesses, the key
findings hurting the site, a prioritized plan of action, and evidence
exhibits. Everything else the run produces (scan JSON, digest, draft data,
history ledger, screenshots) is an internal working artifact under
`planning/_evidence/` and is not a deliverable.

`<slug>` is derived from the target host (drop scheme and leading `www.`, dots to hyphens), so runs against different sites never overwrite each other.

## Set the target (the only thing you normally change)
Open `TARGET.txt` at the repo root and put the URL to analyze on its own line. To analyze a different site, edit that single line and run again. You can also override per run by giving Claude Code the URL in chat ("run the review against https://example.com"), which takes precedence over the file.

## How to run
Invoke the skill: `/review-site`
Or ask directly: "Run the website review against the URL in TARGET.txt and build the executive report."

## Output contract
- Resolve the target from chat if a URL was given, else from `TARGET.txt` (first line beginning with `http`).
- Derive the slug and use it to name the deliverable.
- Distill the findings and recommendations into `planning/_evidence/exec_report_data.json` (start from the machine draft), then render `planning/<slug>_Executive_Report.docx` with the bundled builder. That docx is the only deliverable.
- Keep raw evidence, notes, and screenshots under `planning/_evidence/`.
- Every finding cites the specific page URL and the exact element it refers to. No unsourced claims.
- Do not hand-write the docx formatting. The builder owns formatting so the report looks identical every run.

## Tooling reality (read before any design analysis)
- Deterministic scanner suite: `python .claude/skills/review-site/tools/scan_site.py` runs first and produces the passive, measured evidence (HTTP security headers and security.txt, page-level security hygiene like Subresource Integrity and form-action downgrades, TLS and CAA, DNS email-auth, robots/sitemap crawlability and apex/www canonicalization, SEO and on-page structure, static accessibility, link health and mixed content, page weight with per-asset caching and redirect chains, readability, third-party tracking/privacy, and static design signals like favicons, font families, and layout-shift risk) as `planning/_evidence/<slug>_scan.json` plus a `<slug>_scan_summary.md`. The one-command form `python .claude/skills/review-site/tools/run_review.py` additionally runs page discovery first and drafts the report data file at the end. The JSON also carries a `scorecard` that rolls each category into a posture band (Strong, Adequate, Weak, Poor, Not measured) from its own checks, plus an overall band; copy that into the executive report's scorecard field. Cite these measurements in findings rather than eyeballing headers or markup by hand. Each run also appends numeric trend metrics to planning/_evidence/<slug>_history.jsonl and archives the full scan JSON under planning/_evidence/archive/; with two or more calendar quarters of ledger history the report gains a "Progress this quarter" trend section (charts are added once three or more quarters exist and then plot every quarter in the ledger), built from the latest run in each quarter. The suite is pure standard library and strictly passive, and it ships an offline unit-test suite (`python -m unittest test_review_tools` in the tools directory). See the skill's "Deterministic evidence tools" section for the full check list.
- The scanners detect client-rendered pages. When a page's body is injected by JavaScript, its structural SEO and accessibility checks are marked inconclusive. Do not report an empty static body as a clean result; the rendered capture upgrades those verdicts to measured ones.
- The rendered-evidence pass is automated: `run_review.py` finds a locally installed Chrome or Edge, drives it headless over the DevTools protocol (`tools/capture_rendered.py`, pure stdlib), refreshes DOM snapshots for client-rendered pages, measures LCP/CLS/TBT and WCAG contrast per page, and re-scans so the same run consumes the evidence. `--no-browser` skips it. When no browser is installed the run says so and the static inconclusive verdicts stand; nothing is guessed. The automated capture does not dismiss cookie overlays; use the manual browser pass (SKILL.md, tools/CAPTURE.md) when one blocks the content.
- `WebFetch` returns page HTML as text. Use it for content, copy, information architecture, and reading anything the scanners flagged. It does NOT render the page, so it cannot judge visual layout, color, typography, spacing, imagery, or responsive behavior.
- If a Playwright MCP browser is connected, use it to load pages, dismiss any cookie or region overlay, and capture screenshots at desktop (1440px) and mobile (390px) widths. Base all visual findings on those screenshots. For client-rendered pages, the browser is also how you get real content for the structural checks the static scanners could not complete.
- If no browser tool is available, state that limitation in the report's scope line and in chat, and limit design findings to what is inferable from HTML, CSS, and the scanner JSON (semantic structure, heading order, ARIA, meta tags, declared breakpoints). Do not invent visual judgments.

## Scope
Do not crawl the entire site by default. An opt-in polite crawl exists for
authorized deep reviews (`python .claude/skills/review-site/tools/run_review.py --crawl N`,
robots.txt compliant, serial with a per-request delay, hard 500-page cap);
use it only when the user explicitly asks for a wider surface. Otherwise
review this default set:
1. Homepage (the target URL)
2. Every top-level navigation destination
3. Two or three representative deep pages per major section (a product page, an article or insights page, an About or Careers page)
4. Footer utility pages (legal, privacy, contact)
If the site uses region routing or localized variants, fix on one locale (default: the version served to a US, English visitor) and state which one you reviewed.

To assemble that set, run the scoping helper `python .claude/skills/review-site/tools/discover_pages.py` first. It reads the sitemap and homepage navigation and proposes a representative set (it fetches only the homepage and sitemaps, not the whole site). Use its `proposed_review_set` as a starting point, then apply these rules.

All checks are passive. Do not attempt logins, form submissions, path brute forcing, port scanning, or any active probing.

## Authorization
Only run against sites you own or are authorized to assess. State the target and the authorization assumption in chat when the review starts.

## Writing rules for all output
- Never use em dashes or en dashes. Use hyphens or rewrite the sentence.
- Be specific and evidence-based. Tie each recommendation to an observed problem.
- Any metric or benchmark you cite must be verifiable and sourced. Do not fabricate scores, competitor data, benchmarks, or vulnerabilities. If you did not measure it, say so.
