# Website Review Project

## Purpose
Point this at any website and produce a prioritized change plan plus an executive report. Two deliverables per run:
1. `planning/<slug>_GAMEPLAN.md` - the full, detailed working plan.
2. `planning/<slug>_Executive_Report.docx` - a CEO-level Word summary of the key findings hurting the site and the preferred recommendations to fix them.

`<slug>` is derived from the target host (drop scheme and leading `www.`, dots to hyphens), so runs against different sites never overwrite each other.

## Set the target (the only thing you normally change)
Open `TARGET.txt` at the repo root and put the URL to analyze on its own line. To analyze a different site, edit that single line and run again. You can also override per run by giving Claude Code the URL in chat ("run the review against https://example.com"), which takes precedence over the file.

## How to run
Invoke the skill: `/review-site`
Or ask directly: "Run the website review against the URL in TARGET.txt, write the gameplan, and build the executive report."

## Output contract
- Resolve the target from chat if a URL was given, else from `TARGET.txt` (first line beginning with `http`).
- Derive the slug and use it to name both deliverables.
- Write the full plan to `planning/<slug>_GAMEPLAN.md` (overwrite if it exists).
- Distill the top findings and recommendations into `planning/_evidence/exec_report_data.json`, then render `planning/<slug>_Executive_Report.docx` with the bundled builder.
- Keep raw evidence, notes, and screenshots under `planning/_evidence/`.
- Every finding cites the specific page URL and the exact element it refers to. No unsourced claims.
- Do not hand-write the docx formatting. The builder owns formatting so the report looks identical every run.

## Tooling reality (read before any design analysis)
- Deterministic scanner suite: `python .claude/skills/review-site/tools/scan_site.py` runs first and produces the passive, measured evidence (HTTP security headers and security.txt, page-level security hygiene like Subresource Integrity and form-action downgrades, TLS and CAA, DNS email-auth, robots/sitemap crawlability and apex/www canonicalization, SEO and on-page structure, static accessibility, link health and mixed content, page weight with per-asset caching and redirect chains, readability, third-party tracking/privacy, and static design signals like favicons, font families, and layout-shift risk) as `planning/_evidence/<slug>_scan.json` plus a `<slug>_scan_summary.md`. The one-command form `python .claude/skills/review-site/tools/run_review.py` additionally runs page discovery first and drafts the report data file at the end. The JSON also carries a `scorecard` that rolls each category into a posture band (Strong, Adequate, Weak, Poor, Not measured) from its own checks, plus an overall band; copy that into the executive report's scorecard field. Cite these measurements in findings rather than eyeballing headers or markup by hand. The suite is pure standard library and strictly passive, and it ships an offline unit-test suite (`python -m unittest test_review_tools` in the tools directory). See the skill's "Deterministic evidence tools" section for the full check list.
- The scanners detect client-rendered pages. When a page's body is injected by JavaScript, its structural SEO and accessibility checks are marked inconclusive. Do not report an empty static body as a clean result; capture the rendered page with the browser instead.
- `WebFetch` returns page HTML as text. Use it for content, copy, information architecture, and reading anything the scanners flagged. It does NOT render the page, so it cannot judge visual layout, color, typography, spacing, imagery, or responsive behavior.
- If a Playwright MCP browser is connected, use it to load pages, dismiss any cookie or region overlay, and capture screenshots at desktop (1440px) and mobile (390px) widths. Base all visual findings on those screenshots. For client-rendered pages, the browser is also how you get real content for the structural checks the static scanners could not complete.
- If no browser tool is available, say so in the gameplan and limit the design section to what is inferable from HTML, CSS, and the scanner JSON (semantic structure, heading order, ARIA, meta tags, declared breakpoints). Do not invent visual judgments.

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
Only run against sites you own or are authorized to assess. State the target and the authorization assumption at the top of the gameplan.

## Writing rules for all output
- Never use em dashes or en dashes. Use hyphens or rewrite the sentence.
- Be specific and evidence-based. Tie each recommendation to an observed problem.
- Any metric or benchmark you cite must be verifiable and sourced. Do not fabricate scores, competitor data, benchmarks, or vulnerabilities. If you did not measure it, say so.
