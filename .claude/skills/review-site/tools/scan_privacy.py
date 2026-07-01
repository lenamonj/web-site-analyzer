#!/usr/bin/env python3
"""
Passive privacy and third-party tracking scanner.

From a page's static HTML only (no JS execution, no requests to trackers, no
downloaded blocklists), it surfaces third-party resource origins, known
tracker/analytics hosts, likely tracking pixels, and whether a cookie-consent
mechanism is present. Every finding is an observation of what the static markup
reveals; it fabricates no scores. Client-rendered pages are flagged so an empty
static body is not mistaken for a privacy-clean result. See PLAN.md section 7.

Usage:
    python scan_privacy.py <url> [output.json]
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common
import htmlmeta
import scan_dns_email as dns

CATEGORY = "privacy"
SCOPE = "page"
MAX_LIST = 12

# Curated, explicit reference lists. A match is a factual observation that a
# known host or marker appears in the static HTML, not a score or benchmark.
KNOWN_TRACKERS = {
    "google-analytics.com": "analytics",
    "googletagmanager.com": "analytics",
    "analytics.google.com": "analytics",
    "doubleclick.net": "advertising",
    "googlesyndication.com": "advertising",
    "googleadservices.com": "advertising",
    "connect.facebook.net": "social",
    "facebook.com": "social",
    "hotjar.com": "session-replay",
    "clarity.ms": "session-replay",
    "fullstory.com": "session-replay",
    "mouseflow.com": "session-replay",
    "crazyegg.com": "session-replay",
    "segment.com": "analytics",
    "segment.io": "analytics",
    "mixpanel.com": "analytics",
    "amplitude.com": "analytics",
    "bat.bing.com": "advertising",
    "ads.linkedin.com": "advertising",
    "snap.licdn.com": "advertising",
    "ads-twitter.com": "advertising",
    "analytics.tiktok.com": "advertising",
    "quantserve.com": "advertising",
    "scorecardresearch.com": "analytics",
}

CMP_HOSTS = (
    "cookiebot.com", "cookielaw.org", "onetrust.com", "osano.com",
    "trustarc.com", "usercentrics.eu", "usercentrics.com", "iubenda.com",
    "cookieyes.com", "termly.io", "quantcast.com",
)

CONSENT_MARKERS = (
    "cookie-consent", "cookie-banner", "cookie-notice", "cookieconsent",
    "onetrust", "ot-sdk", "gdpr-consent", "consent-banner", "cookie-bar",
    "cookie-policy",
)

SCRIPT_RE = re.compile(r"<script\b([^>]*)>", re.I)
IFRAME_RE = re.compile(r"<iframe\b([^>]*)>", re.I)
IMG_RE = re.compile(r"<img\b([^>]*)>", re.I)
SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I)
WIDTH_RE = re.compile(r"""\bwidth\s*=\s*["']?\s*(\d+)""", re.I)
HEIGHT_RE = re.compile(r"""\bheight\s*=\s*["']?\s*(\d+)""", re.I)
LINK_RESOURCE_RELS = ("stylesheet", "preconnect", "dns-prefetch", "prefetch", "preload")


def _collect_resource_urls(body, parsed, base):
    """Absolute http(s) URLs of external resources referenced by the static HTML."""
    urls = []
    for attrs in SCRIPT_RE.findall(body):
        m = SRC_RE.search(attrs)
        if m:
            urls.append(urljoin(base, m.group(1)))
    for attrs in IFRAME_RE.findall(body):
        m = SRC_RE.search(attrs)
        if m:
            urls.append(urljoin(base, m.group(1)))
    for img in parsed["images"]:
        if img.get("src"):
            urls.append(urljoin(base, img["src"]))
    for link in parsed["links"]:
        rel = (link.get("rel", "") or "").lower()
        href = link.get("href")
        if href and any(r in rel for r in LINK_RESOURCE_RELS):
            urls.append(urljoin(base, href))
    seen, out = set(), []
    for u in urls:
        if urlparse(u).scheme in ("http", "https") and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _third_parties(urls, page_domain):
    """Distinct third-party registrable domains among the resource URLs."""
    seen, out = set(), []
    for u in urls:
        domain = dns.registrable_domain(urlparse(u).hostname or "")
        if domain and domain != page_domain and domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out


def _match_trackers(urls):
    """Known-tracker hosts present among the resource URLs, host substring -> category."""
    found = {}
    for u in urls:
        host = (urlparse(u).hostname or "").lower()
        for key, category in KNOWN_TRACKERS.items():
            if key in host:
                found[key] = category
    return found


def _tracking_pixels(body, base):
    """<img> that are 1x1 / zero-dimension or load from a known-tracker host."""
    seen, out = set(), []
    for attrs in IMG_RE.findall(body):
        m = SRC_RE.search(attrs)
        if not m:
            continue
        src = urljoin(base, m.group(1))
        if urlparse(src).scheme not in ("http", "https"):
            continue
        host = (urlparse(src).hostname or "").lower()
        w = WIDTH_RE.search(attrs)
        h = HEIGHT_RE.search(attrs)
        tiny = (w and int(w.group(1)) <= 1) or (h and int(h.group(1)) <= 1)
        tracker = any(key in host for key in KNOWN_TRACKERS)
        if (tiny or tracker) and src not in seen:
            seen.add(src)
            out.append(src)
    return out


def _consent_detected(body):
    low = body.lower()
    return any(h in low for h in CMP_HOSTS) or any(m in low for m in CONSENT_MARKERS)


def _consent_verdict(detected, obligation_present):
    if detected:
        return {"verdict": "pass", "detected": True,
                "note": ("Cookie-consent mechanism detected in static HTML. Static "
                         "detection cannot confirm it blocks tracking before consent.")}
    if obligation_present:
        return {"verdict": "warn", "detected": False,
                "note": ("No cookie-consent mechanism detected while third-party trackers "
                         "or resources are present; review consent obligations.")}
    return {"verdict": "info", "detected": False,
            "note": "No cookie-consent mechanism detected and no third-party resources found."}


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_privacy", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    body = res["body"] or ""

    if render["likely_client_rendered"]:
        note = ("Page is client-rendered; third-party resources load via JS and are "
                "not in static HTML. Capture the rendered page to assess them.")
        checks = {
            "third_party_origins": {"verdict": "info", "note": note},
            "known_trackers": {"verdict": "info", "note": note},
            "tracking_pixels": {"verdict": "info", "note": note},
            "cookie_consent": _consent_verdict(_consent_detected(body), obligation_present=False),
        }
        third = []
    else:
        page_domain = dns.registrable_domain(common.host_of(base))
        urls = _collect_resource_urls(body, parsed, base)
        third = _third_parties(urls, page_domain)
        trackers = _match_trackers(urls)
        pixels = _tracking_pixels(body, base)

        if third:
            tp = {"verdict": "info", "count": len(third), "domains": third[:MAX_LIST],
                  "note": f"{len(third)} distinct third-party origin(s): {', '.join(third[:MAX_LIST])}."}
        else:
            tp = {"verdict": "info", "count": 0, "domains": [],
                  "note": "No third-party resource origins in the static HTML."}

        if trackers:
            listed = ", ".join(f"{h} ({c})" for h, c in trackers.items())
            kt = {"verdict": "warn", "trackers": trackers,
                  "note": f"Known tracking/analytics hosts present: {listed}."}
        else:
            kt = {"verdict": "pass", "trackers": {},
                  "note": "No known third-party tracking hosts in the static HTML."}

        if pixels:
            px = {"verdict": "warn", "count": len(pixels), "examples": pixels[:MAX_LIST],
                  "note": (f"{len(pixels)} likely tracking pixel(s) (1x1 or known-tracker <img>). "
                           "JS-injected pixels are not visible to a static scan.")}
        else:
            px = {"verdict": "pass", "count": 0, "examples": [],
                  "note": "No 1x1 or known-tracker tracking pixels in static markup."}

        cc = _consent_verdict(_consent_detected(body), obligation_present=bool(trackers or third))
        checks = {"third_party_origins": tp, "known_trackers": kt,
                  "tracking_pixels": px, "cookie_consent": cc}

    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1

    return {
        "tool": "scan_privacy",
        "target": url,
        "final_url": base,
        "ok": True,
        "render": render,
        "third_party_count": len(third),
        "summary": tally,
        "checks": checks,
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    result["category"] = CATEGORY
    result["grade"] = common.grade(common.verdicts_of(result))
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_privacy.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
