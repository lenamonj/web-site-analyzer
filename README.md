# Website Review

> Point Claude Code at any website and get two deliverables: a full prioritized gameplan and a CEO-level Word report. Retargeting is a one-line change.

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Scanners](https://img.shields.io/badge/scanners-zero%20dependencies-2ea44f)
![Tests](https://img.shields.io/badge/tests-unittest%20passing-2ea44f)
![Scope](https://img.shields.io/badge/scope-passive%20%26%20external-orange)
![Report](https://img.shields.io/badge/report-python--docx-informational)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

---

## What you get

Every run produces two files in `planning\`, named by the target's domain so runs on different sites never overwrite each other:

| File | What it is |
| --- | --- |
| `planning\<slug>_GAMEPLAN.md` | The full working plan: findings by category, prioritized recommendations, quick wins, strategic initiatives, open questions. |
| `planning\<slug>_Executive_Report.docx` | A one-to-two page CEO-level Word summary: bottom line, severity-ranked findings, preferred fixes, quick wins. |

`<slug>` is the host with the scheme and any leading `www.` removed and dots turned into hyphens (for example `example.com` becomes `example-com`).

The review covers Content, Design (measured signals plus the optional browser pass), Accessibility, Navigation and IA, SEO and Technical, Performance and delivery architecture, Privacy and tracking, and a passive Security posture pass at both the host level (TLS, security headers, cookie flags, email auth, information disclosure) and the page level (Subresource Integrity, form-action downgrades, CSP-blocking inline handlers).

---

## How it works

Claude Code reads `CLAUDE.md` and the `review-site` skill, resolves the target, then runs a bundled suite of passive evaluation tools that produce hard, reproducible measurements. It reads those measurements plus the in-scope page content, forms the findings, and writes both deliverables. The Word report's formatting is owned by a bundled `python-docx` builder, so the report looks identical on every run regardless of the target or who invokes it.

```
TARGET.txt  ->  scanner suite (measured evidence)  ->  gameplan  ->  executive report
                        |                                  ^
                   WebFetch + optional browser ------------+
```

---

## Evaluation tools

The review does not rely on the model eyeballing headers or markup. A pure standard-library, strictly passive scanner suite runs first and writes its results to `planning\_evidence\<slug>_scan.json` (plus a readable `<slug>_scan_summary.md`). Each check carries a `pass`, `warn`, `fail`, or `info` verdict and a short note that findings cite directly. Run it by hand any time:

```
python .claude\skills\review-site\tools\run_review.py                                (one command: discover, scan, draft)
python .claude\skills\review-site\tools\discover_pages.py                            (propose an in-scope page set)
python .claude\skills\review-site\tools\scan_site.py                                 (reads TARGET.txt)
python .claude\skills\review-site\tools\scan_site.py https://example.com https://example.com/about
```

| Tool | Measures (passively) |
| --- | --- |
| `discover_pages.py` | Reads the sitemap and homepage nav to propose a representative in-scope review set (scoping helper; fetches only the homepage and sitemaps) |
| `scan_http_security.py` | HTTPS redirect, HSTS, CSP, clickjacking protection, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, cookie flags, version banners, security.txt (RFC 9116) |
| `scan_tls.py` | Negotiated TLS protocol, HTTP/2 support via ALPN, certificate issuer, days to expiry, hostname coverage, CAA issuance records, legacy TLS 1.0/1.1 probe |
| `scan_dns_email.py` | SPF, DMARC policy, DKIM (common selectors), MX, DNSSEC, MTA-STS (record plus policy mode), TLS-RPT, BIMI, over DNS-over-HTTPS |
| `scan_crawl.py` | robots.txt presence and sitemap references, site-wide Disallow detection, XML sitemap reachability, apex vs www canonicalization (host-level, checked once per run) |
| `scan_seo.py` | Title and meta-description length, canonical, viewport, robots meta, heading hierarchy, Open Graph, Twitter cards, JSON-LD, hreflang, image alt |
| `scan_accessibility.py` | Document language and title, image alt, form labels, heading order, landmarks, link text, positive tabindex, empty buttons |
| `scan_links.py` | Broken links (404/410/5xx only), redirects, access-restricted links, in-page anchors pointing at missing ids, and insecure http resources on an https page (mixed content) |
| `scan_performance.py` | Initial HTML transfer size, static resource-weight floor, render-blocking head scripts, third-party origins, gzip/brotli compression, per-asset caching lifetimes, redirect chains |
| `scan_readability.py` | Flesch Reading Ease, Flesch-Kincaid grade level, average sentence length (heuristic, on visible text) |
| `scan_privacy.py` | Third-party resource origins, known tracker/analytics hosts, likely tracking pixels, cookie-consent detection (static HTML only) |
| `scan_page_security.py` | Subresource Integrity coverage on cross-origin scripts/styles, forms posting to plain HTTP from HTTPS pages, inline event handlers, target=_blank rel hygiene |
| `scan_design.py` | Favicon and theme-color, deprecated presentational tags, inline-style density, distinct font families from inline and linked CSS, images without dimensions (layout shift) |
| `scan_vitals.py` | Browser-captured LCP, CLS, TBT, and WCAG contrast, graded against the published Core Web Vitals and Lighthouse thresholds; reports "not captured" honestly when no browser pass ran (see `tools\CAPTURE.md`) |
| `scan_site.py` | Orchestrates all of the above across the target and extra pages, rolls the results into a per-category scorecard, writes the evidence JSON and digest |
| `draft_report_data.py` | Drafts the executive-report data file from the scan JSON: measured scorecard and findings filled in, judgement fields left empty |
| `crawler.py` | Opt-in polite crawler: breadth-first same-domain discovery, robots.txt compliant (including Crawl-delay), strictly serial with a per-request delay, hard 500-page ceiling, resumable state file |
| `run_review.py` | One command for the whole evidence pass: discovery (or `--crawl N` for the polite crawler), full scan of the page set, digest, and draft report data |

Issues are **aggregated**: an identical finding repeated across pages (a template-level defect) collapses into one entry naming the affected pages, so the digest and the drafted report state "missing landmarks on 12 pages" once instead of twelve times. Each run appends to a per-target **history ledger** (`planning\_evidence\<slug>_history.jsonl`), diffs itself against the previous run (new vs resolved issues), and the digest shows a **trend** of the last five runs with any overall-band movement, so the fix-and-rescan loop shows progress explicitly.

Each run also produces a **scorecard**: every category is rolled up into a posture band (Strong, Adequate, Weak, Poor, or Not measured) from its own pass/warn/fail checks, plus an overall band. It is a transparent aggregation of measured checks, not an invented benchmark, and the raw counts always travel with it. The executive report renders this scorecard when present. A multi-page run adds a **cross-page** check for titles or meta descriptions reused across pages. Each page is fetched and parsed once and shared across all page-level scanners, so scanning stays light on the target, and one scanner failing never aborts the run.

The scanners detect client-rendered (JavaScript) pages and mark their structural SEO, accessibility, and readability checks inconclusive rather than reporting an empty static body as clean. With the optional browser pass, the agent captures each such page's rendered DOM to `planning\_evidence\rendered\<slug>\` (files plus a small manifest) and the next scan runs the structural scanners against the browser-built DOM, labeling those verdicts `evidence_source: rendered_dom`; performance numbers always stay measured from the real network transfer. Without a browser, the inconclusive verdicts stand - nothing is guessed.

---

## Prerequisites

- Claude Code (this is a Claude Code project, not a standalone script).
- Python 3.10 or later on your PATH. Verify with `python --version`.
- The scanner suite needs nothing beyond the standard library.
- `python-docx`, for the Word report only (installed in the Install step below).
- Optional: Playwright MCP, for real visual and screenshot analysis. Without it the design section is limited to what is inferable from HTML and CSS (structural-only). Everything else still runs. Playwright MCP needs Node.js 18 or later.

---

## Install (Windows)

1. Extract the zip into a working folder, for example `website-review\`. It merges with any existing `planning\` folder rather than replacing it. Confirm the hidden folder landed with `dir /a` (you should see `.claude`).

2. Install the report dependency:

   ```
   pip install python-docx
   ```

3. Optional, for visual analysis. Requires Node.js 18 or later:

   ```
   claude mcp add playwright npx @playwright/mcp@latest
   claude mcp list
   ```

4. Open Claude Code in that folder:

   ```
   cd website-review
   claude
   ```

---

## Usage

1. Set the target. Open `TARGET.txt` and put your URL on the line beginning with `http`:

   ```
   https://www.example.com
   ```

2. Run the review inside Claude Code:

   ```
   /review-site
   ```

   Or ask directly: "Run the website review against the URL in TARGET.txt, write the gameplan, and build the executive report."

3. Collect the outputs from `planning\`.

If Claude Code stops after writing the gameplan on the first run, tell it explicitly to build the executive report.

---

## Run it on a different site

Edit the one URL line in `TARGET.txt` and run `/review-site` again. That is the only change needed to retarget.

To point at a site for a single run without editing the file, give Claude Code the URL in chat ("run the review against https://another.com"). A URL given in chat overrides `TARGET.txt` for that run.

---

## Tests

The scanner suite ships with an offline, zero-dependency regression suite (Python `unittest`, 126 tests). It drives the HTML parser, every pure grading function, the tool contract across the whole registry, and the full pipeline with inline fixtures and stubbed network primitives, so it needs no network and runs in well under a second:

```
cd .claude\skills\review-site\tools
python -m unittest test_review_tools
```

The report builder has its own suite (9 tests, requires `python-docx`, skipped when absent):

```
cd .claude\skills\review-site
python -m unittest test_exec_report
```

---

## Scope and safety

- The review is passive and external. It inspects what any browser or DNS resolver already receives: page HTML, response headers, cookies, TLS, and public DNS records.
- It does not log in, submit forms, brute force paths, or port scan.
- Only run this against sites you own or are authorized to assess. The gameplan states the target and the authorization assumption at the top.
- "Any website" is subject to that authorization and to the site not hard-blocking automated fetches. Pages behind a login wall or aggressive bot protection may return limited or no data, and the report will say so rather than guess.

---

## Project structure

```
CLAUDE.md                                    Project context and output contract
TARGET.txt                                   The URL to analyze (edit this to retarget)
README.md                                    This file
.claude\
  settings.json                              Permission allowlist for the skill
  skills\review-site\
    SKILL.md                                 The review workflow and rules
    build_exec_report.py                     Deterministic python-docx report builder
    test_exec_report.py                      Offline unit tests for the report builder
    tools\                                   Passive evaluation tools (pure standard library)
      common.py                              Shared fetch (gzip-aware), DoH, TLS, JSON helpers
      htmlmeta.py                            Single-pass HTML extractor (SEO and a11y share it)
      registry.py                            Central tool registry (single source of discovery)
      discover_pages.py                      Sitemap/nav page-discovery scoping helper
      scan_http_security.py                  Security-header and cookie posture
      scan_tls.py                            TLS and certificate posture
      scan_dns_email.py                      SPF, DMARC, DKIM, MX, DNSSEC
      scan_crawl.py                          robots.txt and sitemap (host-level, once per run)
      scan_seo.py                            On-page SEO and technical structure
      scan_accessibility.py                  Static accessibility checks
      scan_links.py                          Link health and mixed content
      scan_performance.py                    Page-weight and resource analysis
      scan_readability.py                    Readability metrics on visible text
      scan_privacy.py                        Third-party trackers, pixels, consent detection
      scan_page_security.py                  Page-level security hygiene (SRI, form actions)
      scan_design.py                         Static design signals (icons, fonts, inline styles)
      scan_site.py                           Orchestrator + scorecard, writes the evidence JSON
      draft_report_data.py                   Drafts exec report data from the scan JSON
      run_review.py                          One-command pipeline: discover, scan, draft
      test_review_tools.py                   Offline unit tests for the suite
planning\
  _evidence\                                 Scan JSON and digest, screenshots, notes, exec_report_data.json
    README.txt
```

---

## Notes

- If `python` is not found, the skill falls back to `py`.
- All generated output avoids em dashes and en dashes by design.
- To rebrand the Word report, change the single `ACCENT_HEX` constant near the top of `build_exec_report.py`.
- Findings never carry fabricated metrics, scores, or vulnerabilities. Anything not measured is labeled as such.
