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

CATEGORY = "privacy"
SCOPE = "page"
MAX_LIST = 12

# Curated, explicit reference lists. A match is a factual observation that a
# known host or marker appears in the static HTML, not a score or benchmark.
# Entries are registrable domains (or tracking-specific subdomains) whose
# function is publicly documented in the common tracker datasets
# (EasyPrivacy, DuckDuckGo Tracker Radar, Ghostery/WhoTracksMe). Matching is
# exact-or-subdomain via _host_matches; see PLAN.md section 25.
KNOWN_TRACKERS = {
    # -- analytics ---------------------------------------------------------
    "google-analytics.com": "analytics",
    "googletagmanager.com": "analytics",
    "analytics.google.com": "analytics",
    "segment.com": "analytics",
    "segment.io": "analytics",
    "mixpanel.com": "analytics",
    "amplitude.com": "analytics",
    "heapanalytics.com": "analytics",
    "heap.io": "analytics",
    "kissmetrics.io": "analytics",
    "statcounter.com": "analytics",
    "chartbeat.com": "analytics",
    "parsely.com": "analytics",
    "plausible.io": "analytics",
    "matomo.cloud": "analytics",
    "piwik.pro": "analytics",
    "getclicky.com": "analytics",
    "woopra.com": "analytics",
    "gosquared.com": "analytics",
    "pendo.io": "analytics",
    "posthog.com": "analytics",
    "scorecardresearch.com": "analytics",
    "quantserve.com": "analytics",
    "quantcount.com": "analytics",
    "mc.yandex.ru": "analytics",
    "mc.yandex.com": "analytics",
    "hm.baidu.com": "analytics",
    "cnzz.com": "analytics",
    "umeng.com": "analytics",
    "omtrdc.net": "analytics",          # Adobe Analytics
    "demdex.net": "advertising",        # Adobe Audience Manager
    "2o7.net": "analytics",             # Adobe (legacy)
    "adobedtm.com": "analytics",
    "adobedc.net": "analytics",
    "webtrends.com": "analytics",
    "nr-data.net": "analytics",         # New Relic browser agent
    "newrelic.com": "analytics",
    "bugsnag.com": "analytics",
    "sentry.io": "analytics",
    # -- advertising and ad-tech ------------------------------------------
    "doubleclick.net": "advertising",
    "googlesyndication.com": "advertising",
    "googleadservices.com": "advertising",
    "adservice.google.com": "advertising",
    "2mdn.net": "advertising",
    "adnxs.com": "advertising",         # Xandr / AppNexus
    "rubiconproject.com": "advertising",
    "pubmatic.com": "advertising",
    "openx.net": "advertising",
    "criteo.com": "advertising",
    "criteo.net": "advertising",
    "taboola.com": "advertising",
    "outbrain.com": "advertising",
    "amazon-adsystem.com": "advertising",
    "adsrvr.org": "advertising",        # The Trade Desk
    "casalemedia.com": "advertising",   # Index Exchange
    "indexww.com": "advertising",
    "smartadserver.com": "advertising",
    "adform.net": "advertising",
    "yieldlab.net": "advertising",
    "teads.tv": "advertising",
    "moatads.com": "advertising",       # Oracle Moat verification
    "doubleverify.com": "advertising",
    "adsafeprotected.com": "advertising",  # IAS verification
    "serving-sys.com": "advertising",   # Sizmek
    "innovid.com": "advertising",
    "flashtalking.com": "advertising",
    "media.net": "advertising",
    "revcontent.com": "advertising",
    "mgid.com": "advertising",
    "sharethrough.com": "advertising",
    "triplelift.com": "advertising",
    "spotxchange.com": "advertising",
    "fwmrm.net": "advertising",         # FreeWheel
    "bidswitch.net": "advertising",
    "crwdcntrl.net": "advertising",     # Lotame
    "bluekai.com": "advertising",       # Oracle Data Cloud
    "exelator.com": "advertising",      # Nielsen
    "eyeota.net": "advertising",
    "tapad.com": "advertising",
    "rlcdn.com": "advertising",         # LiveRamp
    "liadm.com": "advertising",         # LiveIntent
    "id5-sync.com": "advertising",
    "agkn.com": "advertising",          # Neustar
    "mathtag.com": "advertising",       # MediaMath
    "turn.com": "advertising",          # Amobee
    "simpli.fi": "advertising",
    "stackadapt.com": "advertising",
    "yieldmo.com": "advertising",
    "gumgum.com": "advertising",
    "33across.com": "advertising",
    "lijit.com": "advertising",         # Sovrn
    "sovrn.com": "advertising",
    "sonobi.com": "advertising",
    "zemanta.com": "advertising",
    "bat.bing.com": "advertising",
    "ads.linkedin.com": "advertising",
    "snap.licdn.com": "advertising",
    "ads-twitter.com": "advertising",
    "analytics.tiktok.com": "advertising",
    "ct.pinterest.com": "advertising",
    "alb.reddit.com": "advertising",
    "q.quora.com": "advertising",
    "ads.yahoo.com": "advertising",
    "sp.analytics.yahoo.com": "advertising",
    # -- social widgets ----------------------------------------------------
    "connect.facebook.net": "social",
    "facebook.com": "social",
    "platform.twitter.com": "social",
    "platform.linkedin.com": "social",
    "addthis.com": "social",
    "sharethis.com": "social",
    "addtoany.com": "social",
    "disqus.com": "social",
    "vk.com": "social",
    # -- session replay ----------------------------------------------------
    "hotjar.com": "session-replay",
    "clarity.ms": "session-replay",
    "fullstory.com": "session-replay",
    "mouseflow.com": "session-replay",
    "crazyegg.com": "session-replay",
    "smartlook.com": "session-replay",
    "inspectlet.com": "session-replay",
    "luckyorange.com": "session-replay",
    "sessioncam.com": "session-replay",
    "logrocket.com": "session-replay",
    "lr-ingest.io": "session-replay",
    "quantummetric.com": "session-replay",
    "contentsquare.net": "session-replay",
    "decibelinsight.net": "session-replay",
    # -- marketing automation and attribution ------------------------------
    "hs-analytics.net": "marketing",    # HubSpot
    "hs-scripts.com": "marketing",
    "track.hubspot.com": "marketing",
    "marketo.net": "marketing",
    "mktoresp.com": "marketing",
    "pardot.com": "marketing",
    "en25.com": "marketing",            # Oracle Eloqua
    "klaviyo.com": "marketing",
    "braze.com": "marketing",
    "appboycdn.com": "marketing",       # Braze CDN
    "customer.io": "marketing",
    "intercom.io": "marketing",
    "drift.com": "marketing",
    "chimpstatic.com": "marketing",     # Mailchimp
    "onesignal.com": "marketing",
    "bounceexchange.com": "marketing",  # Wunderkind
    "branch.io": "attribution",
    "appsflyer.com": "attribution",
    "adjust.com": "attribution",
    "kochava.com": "attribution",
    "impactradius-event.com": "attribution",
    "awin1.com": "attribution",
    "shareasale.com": "attribution",
    "linksynergy.com": "attribution",   # Rakuten
    # -- A/B testing and personalization ------------------------------------
    "optimizely.com": "ab-testing",
    "visualwebsiteoptimizer.com": "ab-testing",  # VWO
    "abtasty.com": "ab-testing",
}

CMP_HOSTS = (
    "cookiebot.com", "cookielaw.org", "onetrust.com", "osano.com",
    "trustarc.com", "usercentrics.eu", "usercentrics.com", "iubenda.com",
    "cookieyes.com", "termly.io", "quantcast.com",
    "didomi.io", "privacy-center.org", "consentmanager.net",
    "sp-prod.net", "consensu.org", "cookiehub.com", "cookiefirst.com",
    "cookie-script.com", "civiccomputing.com",
)

# Class/id/script markers of a real consent mechanism. Matched as substrings of the
# page, so every entry must be specific enough not to collide with prose: the bare
# "truste" (hits trusted/trustee) and "cookie-policy" (a plain policy-page link, not
# a consent widget) were dropped - TrustArc is still caught via trustarc.com in
# CMP_HOSTS, and the rest are hyphenated/brand tokens that do not occur in copy.
CONSENT_MARKERS = (
    "cookie-consent", "cookie-banner", "cookie-notice", "cookieconsent",
    "onetrust", "ot-sdk", "gdpr-consent", "consent-banner", "cookie-bar",
    "didomi", "usercentrics", "cmplz", "borlabs-cookie", "iubenda",
)

SCRIPT_RE = common.tag_attrs_re("script")
IFRAME_RE = common.tag_attrs_re("iframe")
IMG_RE = common.tag_attrs_re("img")
# (?<![-\w]) not \b: data-src / data-width lazy-load attributes must not
# satisfy the real attribute's regex (\b matches after a hyphen).
SRC_RE = re.compile(r"""(?<![-\w])src\s*=\s*["']([^"']+)["']""", re.I)
WIDTH_RE = re.compile(r"""(?<![-\w])width\s*=\s*["']?\s*(\d+)""", re.I)
HEIGHT_RE = re.compile(r"""(?<![-\w])height\s*=\s*["']?\s*(\d+)""", re.I)
LINK_RESOURCE_RELS = ("stylesheet", "preconnect", "dns-prefetch", "prefetch", "preload")


def _collect_resource_urls(body, parsed, base):
    """Absolute http(s) URLs of external resources referenced by the static HTML."""
    urls = []

    def _add(ref):  # skip a malformed URL rather than abort the scan
        u = common.safe_urljoin(base, ref)
        if u is not None:
            urls.append(u)

    for attrs in SCRIPT_RE.findall(body):
        m = SRC_RE.search(attrs)
        if m:
            _add(m.group(1))
    for attrs in IFRAME_RE.findall(body):
        m = SRC_RE.search(attrs)
        if m:
            _add(m.group(1))
    for img in parsed["images"]:
        if img.get("src"):
            _add(img["src"])
    for link in parsed["links"]:
        rel = (link.get("rel", "") or "").lower()
        href = link.get("href")
        if href and any(r in rel for r in LINK_RESOURCE_RELS):
            _add(href)
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
        domain = common.registrable_domain(urlparse(u).hostname or "")
        if domain and domain != page_domain and domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out


def _host_matches(host, key):
    """True when host IS the tracker domain or a subdomain of it. A plain
    substring test would also match unrelated hosts like notfacebook.com."""
    return host == key or host.endswith("." + key)


def _match_trackers(urls):
    """Known-tracker hosts present among the resource URLs, tracker domain -> category."""
    found = {}
    for u in urls:
        host = (urlparse(u).hostname or "").lower()
        for key, category in KNOWN_TRACKERS.items():
            if _host_matches(host, key):
                found[key] = category
    return found


def _tracking_pixels(body, base):
    """<img> that are 1x1 / zero-dimension or load from a known-tracker host."""
    seen, out = set(), []
    for attrs in IMG_RE.findall(body):
        m = SRC_RE.search(attrs)
        if not m:
            continue
        src = common.safe_urljoin(base, m.group(1))
        if src is None or urlparse(src).scheme not in ("http", "https"):
            continue
        host = (urlparse(src).hostname or "").lower()
        w = WIDTH_RE.search(attrs)
        h = HEIGHT_RE.search(attrs)
        tiny = (w and int(w.group(1)) <= 1) or (h and int(h.group(1)) <= 1)
        tracker = any(_host_matches(host, key) for key in KNOWN_TRACKERS)
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
        page_domain = common.registrable_domain(common.host_of(base))
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

    tally = common.summarize(checks)

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
    return common.finalize(result, CATEGORY)


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
