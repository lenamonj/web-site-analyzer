# Website Analyzer

> Point it at any website and get one boardroom-ready deliverable: a CEO-level Word report built entirely from measured evidence - a posture scorecard, real browser-measured Core Web Vitals, severity-ranked findings that cite the exact page and element, and a prioritized plan of action. Retargeting is a one-line change.

[![CI](https://github.com/lenamonj/web-site-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/lenamonj/web-site-analyzer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/lenamonj/web-site-analyzer)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/scanner%20dependencies-zero-2ea44f)
![Tests](https://img.shields.io/badge/tests-263%20passing-2ea44f)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Scope](https://img.shields.io/badge/scope-passive%20%26%20external-orange)
![Rendered evidence](https://img.shields.io/badge/rendered%20evidence-headless%20Chrome%20DevTools-blueviolet)
![Report](https://img.shields.io/badge/report-python--docx-informational)
[![Built with Claude Fable 5](https://img.shields.io/badge/built%20with-Claude%20Fable%205-D97757?logo=anthropic&logoColor=white)](https://www.anthropic.com/claude)
![Last commit](https://img.shields.io/github/last-commit/lenamonj/web-site-analyzer)

Website Analyzer is a professional site-assessment engine built as a Claude Code project. It combines a deterministic, pure-standard-library scanner suite (14 registered scanners, 10 scorecard categories, zero third-party dependencies) with an automated headless-browser evidence tier and a deterministic Word report builder. Every claim in the final report traces back to a measurement: a header that was actually fetched, a DNS record that was actually resolved, a paint metric a real browser engine actually recorded. Nothing is estimated, nothing is eyeballed, and anything the tool could not measure is labeled exactly that.

---

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [The measurement engine](#the-measurement-engine)
- [Automated rendered evidence](#automated-rendered-evidence)
- [Prospect triage: scoring many sites at once](#prospect-triage-scoring-many-sites-at-once)
- [Evidence discipline](#evidence-discipline)
- [Install](#install)
- [Usage](#usage)
- [Command-line reference](#command-line-reference)
- [Tests and CI](#tests-and-ci)
- [Scope and safety](#scope-and-safety)
- [Project structure](#project-structure)

---

## What you get

Every run produces one deliverable in `planning/`, named by the target's domain so runs against different sites never overwrite each other:

| File | What it is |
| --- | --- |
| `planning/<slug>_Executive_Report.docx` | The CEO-level Word report, designed as a board document: a cover page with the measured posture and contents, the bottom line as a quotable statement, an executive summary of strengths and weaknesses, a scorecard with per-category score bars, a Core Web Vitals panel, a Key dates panel (certificate and domain renewal dates, domain age), severity-ranked findings that enumerate every affected page, a prioritized plan of action, quick wins, and an evidence appendix with highlighted header snippets and screenshots. |

Working artifacts (scan JSON, digest, draft data, history ledger, rendered DOM snapshots, screenshots) land under `planning/_evidence/` and are internal, not deliverables.

`<slug>` is the host with the scheme and any leading `www.` removed and dots turned into hyphens (`example.com` becomes `example-com`).

The review covers Content, Design (measured signals plus browser evidence), Accessibility, Navigation and IA, SEO and Technical, Performance and delivery architecture, Privacy and tracking, and a passive Security posture pass at both the host level (TLS, security headers, cookie flags, email authentication, information disclosure) and the page level (Subresource Integrity, form-action downgrades, inline handlers).

---

## How it works

```
TARGET.txt ──> discovery ──> scanner suite ──> headless-browser capture ──> re-scan ──> draft ──> executive report
                (sitemap        (14 passive        (rendered DOM +           (consumes     (measured    (deterministic
                 + nav)          scanners)          vitals + contrast)        evidence)     data file)    docx builder)
```

One command (`run_review.py`) executes the whole evidence pass:

1. **Discovery** reads the sitemap and homepage navigation and proposes a representative review set (homepage, section landings, deep pages, legal pages). It fetches only the homepage and sitemaps, never the whole site.
2. **The scanner suite** measures every page and the host once, sharing a single fetch per URL across all scanners, and rolls the results into a per-category scorecard.
3. **Automated rendered capture** launches a locally installed Chrome or Edge headless, snapshots the browser-built DOM of every client-rendered page, and measures Largest Contentful Paint, Cumulative Layout Shift, Total Blocking Time, and WCAG 1.4.3 contrast on every scanned page.
4. **A re-scan** (near-free, inside the same per-run fetch cache) upgrades the inconclusive static verdicts to measured `rendered_dom` verdicts and grades the captured vitals against the published Core Web Vitals thresholds.
5. **The report data drafter** turns the scan JSON into a first-draft report data file: measured scorecard rows, aggregated findings, an auto-derived executive summary (strengths, weaknesses, bottom line) and a prioritized action plan, every item traceable to a check.
6. **The report builder** renders the final Word document. Formatting is owned entirely by the builder, so the report looks identical on every run regardless of the target or who invokes it.

The scorecard rolls each category into a posture band (Strong, Adequate, Weak, Poor, or Not measured) from its own pass/warn/fail checks, plus an overall band. It is a transparent aggregation of measured checks, not an invented benchmark, and the raw counts always travel with it.

---

## The measurement engine

The review never relies on a language model eyeballing headers or markup. A deterministic, strictly passive scanner suite runs first and writes its results to `planning/_evidence/<slug>_scan.json` (plus a readable `<slug>_scan_summary.md`). Each check carries a `pass`, `warn`, `fail`, or `info` verdict and a short note that findings cite directly. The suite is pure Python standard library: no requests, no BeautifulSoup, no Playwright, nothing to install.

| Tool | Measures (passively) |
| --- | --- |
| `scan_http_security.py` | HTTPS redirect, HSTS, CSP with full directive analysis (Report-Only delivery, wildcard script origins, script-scoped unsafe-inline/eval), clickjacking protection, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, cookie flags incl. SameSite, version banners, security.txt (RFC 9116) |
| `scan_tls.py` | Negotiated TLS protocol, HTTP/2 via ALPN on the same handshake, certificate issuer and days to expiry, hostname coverage, CAA issuance records, legacy TLS 1.0/1.1 probe |
| `scan_dns_email.py` | SPF, DMARC policy, DKIM across 26 documented selector families probed in parallel, MX, DNSSEC, MTA-STS (record plus policy mode), TLS-RPT, BIMI over DNS-over-HTTPS, plus domain registration and expiry dates via RDAP (the JSON successor to WHOIS) as ungraded conversation-starter facts |
| `scan_crawl.py` | robots.txt incl. site-wide Disallow detection, sitemap reachability, apex vs www canonicalization |
| `scan_crux.py` | Real-user field data from the Chrome UX Report API: origin p75 LCP, CLS, and INP graded against the published Core Web Vitals thresholds (needs `CRUX_API_KEY` or `GOOGLE_API_KEY`; reports honestly when absent or when the origin lacks traffic) |
| `scan_seo.py` | Title and meta-description length, canonical, viewport, robots meta, heading hierarchy, Open Graph, Twitter cards, JSON-LD, hreflang, image alt |
| `scan_accessibility.py` | Document language and title, image alt, form labels, heading order, landmarks, link text, positive tabindex, empty buttons, viewport zoom restrictions (WCAG 1.4.4) |
| `scan_links.py` | Broken links (404/410/5xx), redirects, access-restricted links, in-page anchors pointing at missing ids, mixed content |
| `scan_performance.py` | HTML transfer size, static resource-weight floor, render-blocking head scripts, third-party origins, gzip/brotli compression, per-asset caching lifetimes, redirect chains |
| `scan_readability.py` | Flesch Reading Ease, Flesch-Kincaid grade, average sentence length on visible text, with listing-page noise suppression |
| `scan_privacy.py` | Third-party origins, 154 documented tracker domains grouped by function, tracking pixels, cookie-consent platform detection (20 CMP hosts) |
| `scan_page_security.py` | Subresource Integrity coverage on cross-origin scripts and styles, forms posting to plain HTTP from HTTPS pages, inline event handlers, target=_blank rel hygiene |
| `scan_design.py` | Favicon and theme-color, deprecated presentational tags, inline-style density, font families from inline and linked CSS, images without dimensions (layout-shift risk) |
| `scan_vitals.py` | Browser-measured LCP, CLS, TBT and WCAG 1.4.3 contrast graded against the published Core Web Vitals and Lighthouse thresholds; reports "not captured" honestly when no browser evidence exists |

Supporting tools: `discover_pages.py` (scoping helper), `crawler.py` (opt-in polite crawler: robots.txt compliant including Crawl-delay, strictly serial with a per-request delay, hard 500-page ceiling, resumable state), `capture_rendered.py` (the automated browser tier, below), `draft_report_data.py` (scan JSON to report data), `run_review.py` (the one-command pipeline), and `build_exec_report.py` (the deterministic docx builder).

**Analyst-grade output handling.** Identical findings repeated across pages (a template-level defect) collapse into one entry naming every affected page, so the report says "missing landmarks on 12 pages" once instead of twelve times, and severe findings enumerate every affected URL with no truncation. Each run appends to a per-target history ledger, diffs itself against the previous run (new vs resolved issues), and the digest shows a trend of the last five runs with any overall-band movement, so a fix-and-rescan loop shows progress explicitly.

---

## Automated rendered evidence

Static analysis cannot see what JavaScript builds, and most modern sites build a lot. This is where site scanners usually either lie (reporting an empty SPA shell as a clean page) or give up. Website Analyzer does neither.

The suite detects client-rendered pages and marks their structural checks inconclusive rather than falsely clean. Then `capture_rendered.py` closes the gap automatically:

- It finds a locally installed Chrome or Edge (standard install paths, then PATH; `REVIEW_BROWSER` overrides) and drives it headless over the **Chrome DevTools Protocol**, using a minimal RFC 6455 WebSocket client written on raw standard-library sockets. Zero dependencies survives contact with a real browser.
- For every client-rendered page it captures the browser-built DOM, and the next scan runs every structural scanner against that rendered document, stamping the verdicts `evidence_source: rendered_dom`. A planted image without alt text that no static scanner on earth could see gets caught and cited.
- For every scanned page it measures **LCP, CLS, and TBT** with buffered PerformanceObserver entries and samples **WCAG 1.4.3 contrast** with a computed-style walk (the axe-core approach), grading everything against the published Core Web Vitals and Lighthouse thresholds. Real-user CrUX field data is preferred when available; lab capture fills in when it is not.
- `run_review.py` orchestrates it end to end: scan, capture, re-scan, draft, in one command, with the capture page set capped and every dropped page named. Snapshots refresh on every run, so rendered evidence never goes stale.
- No browser installed? The run says so, plainly, and the inconclusive verdicts stand. Nothing is guessed. Performance numbers always stay measured from the real network transfer, never simulated from a snapshot.

The manual capture path (`tools/CAPTURE.md`) remains available for pages where a cookie overlay must be dismissed before capture, and a manual capture is merged with, never clobbered by, the automated one.

---

## Prospect triage: scoring many sites at once

The full pipeline produces one deep report per site. The inverse job - sweeping many company sites to find the few worth a closer look - is what `tools/triage.py` does. It runs a static, homepage-only, strictly passive pass over a list of domains, ranks them worst-posture-first (a worse measured posture is a stronger candidate for a review), and gives each site a single measured "why to reach out" hook drawn from the same checks the full report uses.

```
# copy the template, add your domains, then run:
cp PROSPECTS.example.txt sales/prospects.txt
python .claude/skills/review-site/tools/triage.py

# or score domains directly:
python .claude/skills/review-site/tools/triage.py acme.com globex.com
```

It writes a ranked `sales/triage_results.csv` (for a spreadsheet or CRM) and a `sales/triage_results.md` (for a quick read), and prints the ranked table:

```
 #  Domain              Posture    Score  Door-opener
 1  neverssl.com        Weak        0.43  Missing baseline security headers (HSTS/CSP/clickjacking)
 2  example.com         Adequate    0.81  Homepage served over plain HTTP with no redirect to HTTPS
 3  www.python.org      Adequate    0.83  Weakest measured area: security headers (Weak)
```

The sweep is serial with a polite delay (one homepage visit per site), so it stays light on every target. Unreachable sites become a flagged row rather than aborting the batch. The `sales/` directory is git-ignored, so prospect lists and results never enter version control. The triage score and a site's eventual full-report score come from the identical scoring engine, so a triage sweep never contradicts the report you later hand the client.

---

## Evidence discipline

The rules that make the output trustworthy, enforced by code and tests rather than good intentions:

- **Every finding cites its evidence.** The page URL, the exact element or header, and the scanner check it came from. No unsourced claims survive into the report.
- **Nothing unmeasured is reported.** No fabricated scores, no invented benchmarks, no competitor numbers. A category with no evidence is "Not measured", not a guess.
- **Inconclusive is not clean.** A client-rendered page without a snapshot keeps its inconclusive verdicts, stated as such.
- **One scanner failing never aborts the run**, and a scanner that cannot reach its target reports that as its result instead of raising.
- **Honest degradation everywhere.** Missing CrUX key, origin absent from the dataset, no browser installed, a page that never fires its load event: each has an explicit, tested code path that names the limitation.
- **No silent truncation.** Capped lists (capture pages, findings) name what was dropped.

---

## Install

Requirements: Python 3.10+ and, for the Word report only, one package:

```
pip install python-docx
```

The scanner suite itself needs nothing beyond the standard library. The automated browser tier uses any locally installed Chrome or Edge; without one, everything else still runs.

Clone and enter:

```
git clone https://github.com/lenamonj/web-site-analyzer.git
cd web-site-analyzer
```

This is a Claude Code project: open Claude Code in the folder and the `review-site` skill, output contract, and permission allowlist are picked up automatically. The evidence pipeline also runs standalone from any terminal (see below), no Claude Code required.

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

   Or ask directly: "Run the website review against the URL in TARGET.txt and build the executive report."

3. Collect the deliverable from `planning/`.

To retarget, edit the one URL line in `TARGET.txt` and run again. A URL given in chat ("run the review against https://another.com") overrides `TARGET.txt` for that run.

### Standalone evidence pipeline

The full measured-evidence pass runs without Claude Code:

```
python .claude/skills/review-site/tools/run_review.py                       # reads TARGET.txt
python .claude/skills/review-site/tools/run_review.py https://example.com  # explicit target
```

This discovers pages, scans, captures rendered evidence when a browser is present, re-scans, and drafts the report data file. Any single scanner also runs alone, for example `python .claude/skills/review-site/tools/scan_tls.py example.com`.

---

## Command-line reference

| Command | Flags |
| --- | --- |
| `run_review.py [url]` | `--crawl N` use the polite crawler for discovery with an N-page budget, `--fresh` restart a resumable crawl, `--no-browser` skip the rendered capture |
| `capture_rendered.py [url]` | `--pages N` raise or lower the capture cap (default 15), `--browser PATH` explicit browser binary |
| `scan_site.py [url] [extra pages...]` | scan an explicit page set |
| `discover_pages.py [url]` | propose the in-scope review set |
| `build_exec_report.py <data.json> <out.docx>` | render the report from a data file |

Environment (via env or a git-ignored `.env` at the repo root): `CRUX_API_KEY` or `GOOGLE_API_KEY` for Chrome UX Report field data, `REVIEW_BROWSER` to pin the browser binary.

---

## Tests and CI

Two offline suites, 263 tests total, no network, run in about a second:

```
cd .claude/skills/review-site/tools
python -m unittest test_review_tools        # 242 tests: parsers, graders, tool contract, pipeline, capture
cd ..
python -m unittest test_exec_report         # 21 tests: the docx builder (needs python-docx)
```

The scanner suite drives the HTML parser, every grading function, the tool contract across the whole registry (every registered tool is swept for result shape, category stamping, and no-raise-on-network-failure), the full pipeline with stubbed network primitives, and the browser tier with crafted WebSocket bytes and a fake DevTools session (including the RFC 6455 accept-key test vector). Network primitives are stubbed suite-wide so no test can ever reach a real network or read a real key.

[GitHub Actions](https://github.com/lenamonj/web-site-analyzer/actions) runs both suites on every push across Ubuntu and Windows, on Python 3.10 and 3.13.

---

## Scope and safety

- The review is **passive and external**. It inspects what any browser or DNS resolver already receives: page HTML, response headers, cookies, TLS handshakes, and public DNS records. The browser tier loads pages exactly as a visitor would, strictly serially, with a delay between pages.
- It does **not** log in, submit forms, brute force paths, or port scan.
- Crawling is opt-in only, robots.txt compliant (including Crawl-delay), serial, and hard-capped at 500 pages.
- Only run this against sites you own or are authorized to assess. The review states the target and the authorization assumption when it starts.
- Sites behind a login wall or aggressive bot protection may return limited data; the report says so rather than guessing.

---

## Project structure

```
CLAUDE.md                                  Project context and output contract
TARGET.txt                                 The URL to analyze (edit this to retarget)
LICENSE                                    MIT
.github/workflows/ci.yml                   Both test suites, ubuntu + windows, py3.10 + 3.13
.claude/
  settings.json                            Permission allowlist for the skill
  skills/review-site/
    SKILL.md                               The review workflow and rules
    build_exec_report.py                   Deterministic python-docx report builder
    test_exec_report.py                    Builder test suite
    tools/                                 The evidence engine (pure standard library)
      common.py                            Shared fetch (cached, gzip-aware), DoH, TLS, grading
      htmlmeta.py                          Single-pass HTML extractor shared by all page scanners
      registry.py                          Central tool registry (single source of discovery)
      discover_pages.py                    Sitemap/nav page-discovery scoping helper
      crawler.py                           Opt-in polite crawler (robots-compliant, resumable)
      capture_rendered.py                  Automated headless-browser capture (DevTools protocol)
      scan_http_security.py ... scan_vitals.py   The 14 registered scanners (see table above)
      scan_site.py                         Orchestrator + scorecard, writes the evidence JSON
      draft_report_data.py                 Drafts report data incl. executive summary and action plan
      run_review.py                        One command: discover, scan, capture, re-scan, draft
      test_review_tools.py                 Offline scanner suite (242 tests)
      CAPTURE.md                           Manual browser-capture reference (fallback path)
planning/
  _evidence/                               Scan JSON, digests, ledgers, rendered snapshots (internal)
```

---

## Notes

- All generated output avoids em dashes and en dashes by design.
- To rebrand the Word report, change the single `ACCENT_HEX` constant near the top of `build_exec_report.py`.
- Findings never carry fabricated metrics, scores, or vulnerabilities. Anything not measured is labeled as such.

## License

[MIT](LICENSE)
