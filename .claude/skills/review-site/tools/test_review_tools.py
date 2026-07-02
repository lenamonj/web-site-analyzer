#!/usr/bin/env python3
"""
Offline regression tests for the passive evaluation tools.

Pure standard library (unittest). No network: every test drives a pure grading
function or the HTML parser with an inline fixture, so the suite is fast and
deterministic. Run from the tools directory:

    python -m unittest test_review_tools
    python test_review_tools.py
"""

import gzip
import io
import json
import struct
import tempfile
import unittest
import urllib.error
import zlib
from pathlib import Path

import capture_rendered as caprend
import common
import discover_pages as disco
import draft_report_data as drpt
import htmlmeta
import registry as reg
import run_review
import scan_accessibility as a11y
import scan_crawl as crawl
import scan_design as design
import scan_dns_email as dns
import scan_http_security as sec
import scan_links as links
import scan_page_security as psec
import scan_performance as perf
import scan_privacy as privacy
import scan_readability as rd
import scan_seo as seo
import scan_crux as crux_scan
import scan_site as site
import scan_tls as tls
import scan_vitals as vitals
import triage as triage_mod
import trends as trends_mod

# The suite is offline by definition: no test may reach the real CrUX API or
# read real keys from the developer's environment or .env. Tests that need
# these primitives override them locally and restore the stubs after.
common.http_post_json = lambda url, payload, timeout=None: {
    "ok": False, "status": None, "json": None, "error": "stubbed offline (suite default)"}
common.env_value = lambda name: None
# RDAP is a network primitive too: default it to "unavailable" so the whole
# suite (including the tool-contract sweep) stays offline. Tests that exercise
# domain registration override this locally and restore it after.
common.rdap_domain = lambda domain, timeout=None: {
    "ok": False, "expiration": None, "registration": None,
    "error": "stubbed offline (suite default)"}

# A well-formed static page: language, title, one H1, ordered headings, images
# with alt, a labeled input, landmarks, descriptive links, Open Graph, JSON-LD.
GOOD_PAGE = """<!doctype html>
<html lang="en">
<head>
<title>Acme Widgets for Modern Teams</title>
<meta name="description" content="Acme Widgets helps modern teams ship faster with reliable, well-supported tooling and clear docs.">
<link rel="canonical" href="https://acme.example/">
<meta property="og:title" content="Acme Widgets">
<meta property="og:description" content="Ship faster">
<meta property="og:image" content="https://acme.example/og.png">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="application/ld+json">{"@type": "Organization", "name": "Acme"}</script>
</head>
<body>
<header>Acme</header>
<nav><a href="/products">Products</a> <a href="/pricing">Pricing</a></nav>
<main>
<h1>Widgets that work</h1>
<h2>Fast to deploy</h2>
<p>Our widgets install in minutes and scale with your team as it grows over time.</p>
<img src="/hero.png" alt="A widget dashboard">
<img src="/chart.png" alt="Usage chart">
<h2>Simple pricing</h2>
<form>
<label for="email">Work email</label>
<input id="email" name="email" type="email">
</form>
<a href="/docs">Read the full documentation</a>
</main>
<footer>Contact us</footer>
</body>
</html>"""

# A problematic static page: no lang, no title, two H1s, a skipped level, images
# without alt, an unlabeled input, generic and empty link text, positive tabindex.
BAD_PAGE = """<!doctype html>
<html>
<head><meta name="description" content="short"></head>
<body>
<div>Some intro text that is long enough to not look like a client rendered shell at all.</div>
<h1>First title</h1>
<h1>Second title</h1>
<h3>Jumped a level</h3>
<img src="/a.png">
<img src="/b.png" alt="">
<input type="text" name="q" placeholder="Search">
<a href="/x">click here</a>
<a href="/y"></a>
<a href="/z" tabindex="3">Deep link</a>
</body>
</html>"""

# A single-page-app shell: real content is injected by JS, static body is empty.
SPA_SHELL = """<!doctype html>
<html lang="en">
<head><title>App</title></head>
<body><div id="root"></div><script src="/bundle.js"></script></body>
</html>"""

# A heavy shell with no SPA marker: padded past the byte threshold, renders nothing.
HEAVY_SHELL = ("<!doctype html><html lang=\"en\"><head><title>Heavy</title></head><body>"
               + "<script>/*" + ("x" * 30000) + "*/</script></body></html>")


class TestHtmlParser(unittest.TestCase):
    def setUp(self):
        self.good = htmlmeta.parse_html(GOOD_PAGE)
        self.bad = htmlmeta.parse_html(BAD_PAGE)

    def test_title_and_lang(self):
        self.assertEqual(self.good["title"], "Acme Widgets for Modern Teams")
        self.assertEqual(self.good["html_lang"], "en")
        self.assertIsNone(self.bad["html_lang"])
        self.assertIsNone(self.bad["title"])

    def test_meta_and_canonical(self):
        self.assertTrue(self.good["meta_description"].startswith("Acme Widgets helps"))
        self.assertEqual(self.good["canonical"], "https://acme.example/")
        self.assertEqual(self.good["meta_viewport"], "width=device-width, initial-scale=1")

    def test_headings(self):
        levels = [h["level"] for h in self.good["headings"]]
        self.assertEqual(levels, [1, 2, 2])
        self.assertEqual(self.good["headings"][0]["text"], "Widgets that work")
        bad_levels = [h["level"] for h in self.bad["headings"]]
        self.assertEqual(bad_levels, [1, 1, 3])

    def test_images_alt(self):
        self.assertEqual(len(self.good["images"]), 2)
        self.assertTrue(all(i["has_alt"] for i in self.good["images"]))
        # BAD_PAGE: one img has no alt attribute, one has an empty alt.
        self.assertFalse(self.bad["images"][0]["has_alt"])
        self.assertTrue(self.bad["images"][1]["has_alt"])
        self.assertEqual(self.bad["images"][1]["alt"], "")

    def test_open_graph_and_jsonld(self):
        self.assertEqual(self.good["open_graph"]["og:image"], "https://acme.example/og.png")
        self.assertIn("Organization", self.good["jsonld_types"])

    def test_form_labels_and_anchors(self):
        self.assertIn("email", self.good["labels_for"])
        texts = [a["text"] for a in self.good["anchors"]]
        self.assertIn("Read the full documentation", texts)

    def test_landmarks_and_tabindex(self):
        self.assertIn("main", self.good["landmarks"])
        self.assertIn("nav", self.good["landmarks"])
        self.assertEqual(self.good["landmarks"], sorted(self.good["landmarks"]))
        self.assertEqual(self.bad["positive_tabindex"], 1)

    def test_malformed_does_not_crash(self):
        out = htmlmeta.parse_html("<html><body><p>unclosed <b>bold <img src=x></body>")
        self.assertIsInstance(out, dict)


class TestRenderAssessment(unittest.TestCase):
    def test_good_page_is_not_client_rendered(self):
        parsed = htmlmeta.parse_html(GOOD_PAGE)
        r = htmlmeta.render_assessment(parsed, GOOD_PAGE)
        self.assertFalse(r["likely_client_rendered"])

    def test_small_static_page_is_not_flagged(self):
        # The example.com false-positive that forced the byte-weight fix.
        tiny = ('<!doctype html><html lang="en"><head><title>Example</title></head>'
                '<body><h1>Example Domain</h1><p>More information...</p>'
                '<a href="https://iana.org">More</a></body></html>')
        parsed = htmlmeta.parse_html(tiny)
        r = htmlmeta.render_assessment(parsed, tiny)
        self.assertFalse(r["likely_client_rendered"])

    def test_spa_root_marker_is_flagged(self):
        parsed = htmlmeta.parse_html(SPA_SHELL)
        r = htmlmeta.render_assessment(parsed, SPA_SHELL)
        self.assertTrue(r["likely_client_rendered"])

    def test_heavy_empty_body_is_flagged(self):
        parsed = htmlmeta.parse_html(HEAVY_SHELL)
        r = htmlmeta.render_assessment(parsed, HEAVY_SHELL)
        self.assertTrue(r["likely_client_rendered"])


class TestSecurityChecks(unittest.TestCase):
    def test_hsts(self):
        self.assertEqual(sec.check_hsts({"strict-transport-security": "max-age=63072000"})["verdict"], "pass")
        self.assertEqual(sec.check_hsts({"strict-transport-security": "max-age=100"})["verdict"], "warn")
        self.assertEqual(sec.check_hsts({})["verdict"], "fail")

    def test_csp(self):
        self.assertEqual(sec.check_csp({"content-security-policy": "default-src 'self'"})["verdict"], "pass")
        weak = sec.check_csp({"content-security-policy": "default-src 'self' 'unsafe-inline'"})
        self.assertEqual(weak["verdict"], "warn")
        self.assertIn("unsafe-inline", weak["weak_directives"])
        self.assertEqual(sec.check_csp({})["verdict"], "warn")

    def test_csp_depth(self):
        ro = sec.check_csp({"content-security-policy-report-only": "default-src 'self'"})
        self.assertEqual(ro["verdict"], "warn")
        self.assertIn("Report-Only", ro["note"])
        noscript = sec.check_csp({"content-security-policy": "img-src 'self'; style-src 'self'"})
        self.assertEqual(noscript["verdict"], "warn")
        self.assertIn("unrestricted", noscript["note"])
        wild = sec.check_csp({"content-security-policy": "script-src * 'self'"})
        self.assertEqual(wild["verdict"], "warn")
        self.assertIn("any origin", wild["note"])
        # unsafe-inline confined to style-src is not a script hole; the check
        # grades the directive that actually governs scripts.
        style_only = sec.check_csp(
            {"content-security-policy": "script-src 'self'; style-src 'unsafe-inline'"})
        self.assertEqual(style_only["verdict"], "pass")
        # An explicit script-src overrides a weak default-src.
        scoped = sec.check_csp(
            {"content-security-policy": "default-src 'unsafe-eval'; script-src 'self'"})
        self.assertEqual(scoped["verdict"], "pass")

    def test_cookie_samesite(self):
        missing = sec.check_cookies({"set-cookie": "sid=1; Secure; HttpOnly"})
        self.assertEqual(missing["verdict"], "warn")
        self.assertIn("SameSite", missing["note"])
        full = sec.check_cookies({"set-cookie": "sid=1; Secure; HttpOnly; SameSite=Strict"})
        self.assertEqual(full["verdict"], "pass")

    def test_clickjacking(self):
        self.assertEqual(sec.check_clickjacking({"x-frame-options": "DENY"})["verdict"], "pass")
        self.assertEqual(sec.check_clickjacking({"content-security-policy": "frame-ancestors 'self'"})["verdict"], "pass")
        self.assertEqual(sec.check_clickjacking({})["verdict"], "fail")

    def test_cookies(self):
        one = sec._parse_cookies({"set-cookie": "sid=1; Secure; HttpOnly; SameSite=Lax"})
        self.assertEqual(one[0], {"name": "sid", "secure": True, "http_only": True, "same_site": "lax"})
        multi = sec._parse_cookies({"set-cookie": ["a=1; Secure; HttpOnly", "b=2"]})
        self.assertEqual(len(multi), 2)
        self.assertEqual(sec.check_cookies({"set-cookie": "b=2"})["verdict"], "warn")
        self.assertEqual(sec.check_cookies({})["verdict"], "info")

    def test_disclosure(self):
        self.assertEqual(sec.check_disclosure({"server": "nginx/1.25.3"})["verdict"], "warn")
        self.assertEqual(sec.check_disclosure({"server": "cloudflare"})["verdict"], "info")
        self.assertEqual(sec.check_disclosure({})["verdict"], "pass")


class TestSeoChecks(unittest.TestCase):
    def test_length_verdict(self):
        self.assertEqual(seo._len_verdict("A good title here", 10, 65, "Title")["verdict"], "pass")
        self.assertEqual(seo._len_verdict("short", 10, 65, "Title")["verdict"], "warn")
        self.assertEqual(seo._len_verdict("", 10, 65, "Title")["verdict"], "warn")
        self.assertEqual(seo._len_verdict("x" * 80, 10, 65, "Title")["verdict"], "warn")

    def test_heading_checks(self):
        good = seo._heading_checks([{"level": 1, "text": "A"}, {"level": 2, "text": "B"}], False)
        self.assertEqual(good["verdict"], "pass")
        none = seo._heading_checks([{"level": 2, "text": "B"}], False)
        self.assertEqual(none["verdict"], "fail")
        multi = seo._heading_checks([{"level": 1, "text": "A"}, {"level": 1, "text": "B"}], False)
        self.assertEqual(multi["verdict"], "warn")
        self.assertEqual(seo._heading_checks([], True)["verdict"], "info")

    def test_og_checks(self):
        full = seo._og_checks({"og:title": "t", "og:description": "d", "og:image": "i"})
        self.assertEqual(full["verdict"], "pass")
        partial = seo._og_checks({"og:title": "t"})
        self.assertEqual(partial["verdict"], "warn")
        self.assertEqual(seo._og_checks({})["verdict"], "info")

    def test_image_alt(self):
        imgs = [{"src": "/a", "has_alt": False, "alt": None}, {"src": "/b", "has_alt": True, "alt": "x"}]
        self.assertEqual(seo._image_alt_check(imgs, False)["missing_alt"], 1)
        self.assertEqual(seo._image_alt_check(imgs, True)["verdict"], "info")

    def test_robots_meta(self):
        self.assertEqual(seo._robots_meta_check("noindex,follow")["verdict"], "fail")
        self.assertEqual(seo._robots_meta_check(None)["verdict"], "info")


class TestAccessibilityChecks(unittest.TestCase):
    def test_accessible_name(self):
        self.assertEqual(a11y._accessible_name({"id": "e", "wrapped_by_label": False,
                         "aria_label": None, "aria_labelledby": None, "title": None}, {"e"}), "label[for]")
        self.assertEqual(a11y._accessible_name({"id": None, "wrapped_by_label": False,
                         "aria_label": "Search", "aria_labelledby": None, "title": None}, set()), "aria-label")
        self.assertIsNone(a11y._accessible_name({"id": None, "wrapped_by_label": False,
                          "aria_label": None, "aria_labelledby": None, "title": None}, set()))

    def test_form_check(self):
        labeled = {"form_controls": [{"tag": "input", "type": "email", "id": "email", "name": "email",
                    "aria_label": None, "aria_labelledby": None, "title": None,
                    "placeholder": None, "wrapped_by_label": False}], "labels_for": ["email"]}
        self.assertEqual(a11y._form_check(labeled, False)["verdict"], "pass")
        unlabeled = {"form_controls": [{"tag": "input", "type": "text", "id": None, "name": "q",
                      "aria_label": None, "aria_labelledby": None, "title": None,
                      "placeholder": None, "wrapped_by_label": False}], "labels_for": []}
        self.assertEqual(a11y._form_check(unlabeled, False)["verdict"], "fail")
        placeholder = {"form_controls": [{"tag": "input", "type": "text", "id": None, "name": "q",
                        "aria_label": None, "aria_labelledby": None, "title": None,
                        "placeholder": "Search", "wrapped_by_label": False}], "labels_for": []}
        self.assertEqual(a11y._form_check(placeholder, False)["verdict"], "warn")

    def test_landmark_check(self):
        self.assertEqual(a11y._landmark_check({"landmarks": ["main", "nav"], "roles": []}, False)["verdict"], "pass")
        self.assertEqual(a11y._landmark_check({"landmarks": ["footer"], "roles": []}, False)["verdict"], "warn")
        self.assertEqual(a11y._landmark_check({"landmarks": [], "roles": ["main", "navigation"]}, False)["verdict"], "pass")

    def test_link_text_check(self):
        empty = {"anchors": [{"href": "/x", "text": "", "aria_label": None, "tabindex": None}],
                 "generic_link_text_set": ["click here"]}
        self.assertEqual(a11y._link_text_check(empty, False)["verdict"], "fail")
        vague = {"anchors": [{"href": "/x", "text": "click here", "aria_label": None, "tabindex": None}],
                 "generic_link_text_set": ["click here"]}
        self.assertEqual(a11y._link_text_check(vague, False)["verdict"], "warn")


class TestLinkChecks(unittest.TestCase):
    def test_classify_only_real_breaks_are_broken(self):
        self.assertEqual(links._classify(404), "broken")
        self.assertEqual(links._classify(410), "broken")
        self.assertEqual(links._classify(503), "broken")
        # 401/403/429 are access controlled, not broken (the icann.org 403 case).
        self.assertEqual(links._classify(403), "restricted")
        self.assertEqual(links._classify(401), "restricted")
        self.assertEqual(links._classify(429), "restricted")
        # LinkedIn's non-standard 999 anti-bot code is restricted, not broken.
        self.assertEqual(links._classify(999), "restricted")
        self.assertEqual(links._classify(200), "ok")
        self.assertEqual(links._classify(None), "unreachable")

    def test_mixed_content(self):
        active = '<html><body><script src="http://cdn.example/a.js"></script></body></html>'
        self.assertEqual(links._mixed_content(active, True)["verdict"], "fail")
        passive = '<html><body><img src="http://cdn.example/a.png"></body></html>'
        self.assertEqual(links._mixed_content(passive, True)["verdict"], "warn")
        clean = '<html><body><img src="https://cdn.example/a.png"></body></html>'
        self.assertEqual(links._mixed_content(clean, True)["verdict"], "pass")
        # A page not served over HTTPS cannot have mixed content.
        self.assertEqual(links._mixed_content(active, False)["verdict"], "info")

    def test_candidate_links_skips_nonhttp_and_dedupes(self):
        anchors = [{"href": "/a"}, {"href": "/a"}, {"href": "mailto:x@y.com"},
                   {"href": "#top"}, {"href": "https://ext.example/b"}]
        out = links._candidate_links(anchors, "https://site.example/")
        self.assertEqual(out, ["https://site.example/a", "https://ext.example/b"])


class TestPerformanceChecks(unittest.TestCase):
    def test_script_blocking_detection(self):
        html = ('<script src="/a.js"></script>'
                '<script src="/b.js" async></script>'
                '<script defer src="/c.js"></script>'
                '<script>doThing()</script>')
        out = perf._script_resources(html, "https://s.example/")
        by_url = {r["url"]: r["blocking"] for r in out}
        self.assertEqual(by_url["https://s.example/a.js"], True)
        self.assertEqual(by_url["https://s.example/b.js"], False)
        self.assertEqual(by_url["https://s.example/c.js"], False)
        self.assertEqual(len(out), 3)  # the inline script has no src and is skipped

    def test_collect_resources_dedupes_and_types(self):
        parsed = {"links": [{"rel": "stylesheet", "href": "/s.css"}, {"rel": "icon", "href": "/f.ico"}],
                  "images": [{"src": "/i.png"}, {"src": "/i.png"}]}
        html = '<script src="/a.js"></script>'
        out = perf._collect_resources(html, parsed, "https://s.example/")
        types = sorted(r["type"] for r in out)
        self.assertEqual(types, ["image", "script", "stylesheet"])  # icon excluded, image deduped


class TestTlsAndDns(unittest.TestCase):
    def test_host_matches(self):
        self.assertTrue(tls._host_matches("www.example.com", "www.example.com"))
        self.assertTrue(tls._host_matches("a.example.com", "*.example.com"))
        self.assertFalse(tls._host_matches("a.b.example.com", "*.example.com"))
        self.assertFalse(tls._host_matches("example.com", "other.com"))

    def test_registrable_domain(self):
        self.assertEqual(dns.registrable_domain("www.contoso.com"), "contoso.com")
        self.assertEqual(dns.registrable_domain("mail.example.co.uk"), "example.co.uk")
        self.assertEqual(dns.registrable_domain("example.com"), "example.com")


class TestScorecard(unittest.TestCase):
    def test_grade_bands(self):
        self.assertEqual(common.grade(["pass", "pass"])["band"], "Strong")
        self.assertEqual(common.grade(["pass", "warn"])["band"], "Adequate")   # 0.75
        self.assertEqual(common.grade(["pass", "warn", "warn", "fail"])["band"], "Weak")  # 0.5
        self.assertEqual(common.grade(["fail", "fail"])["band"], "Poor")
        not_measured = common.grade(["info", "info"])
        self.assertEqual(not_measured["band"], "Not measured")
        self.assertIsNone(not_measured["score"])

    def test_verdicts_of_prefers_checks_then_top_level(self):
        self.assertEqual(common.verdicts_of({"checks": {"a": {"verdict": "pass"},
                         "b": {"verdict": "fail"}}}), ["pass", "fail"])
        self.assertEqual(common.verdicts_of({"verdict": "fail"}), ["fail"])
        self.assertEqual(common.verdicts_of({"ok": False}), [])

    def test_build_scorecard_rolls_up(self):
        host = {"http_security": {"checks": {"a": {"verdict": "pass"}, "b": {"verdict": "fail"}}},
                "tls": {"ok": True, "checks": {"c": {"verdict": "pass"}}},
                "dns_email": {"checks": {"d": {"verdict": "warn"}}}}
        pages = [{"seo": {"ok": True, "checks": {"e": {"verdict": "pass"}}},
                  "readability": {"ok": True, "checks": {"f": {"verdict": "info"}}}}]
        sc = site.build_scorecard(host, pages)
        self.assertEqual(sc["categories"]["security"]["band"], "Weak")   # (1 pass + 0 fail)/2 = 0.5
        self.assertEqual(sc["categories"]["tls"]["band"], "Strong")
        self.assertIn("overall", sc)
        # readability had only info verdicts, so it is "Not measured", not a false grade.
        self.assertEqual(sc["categories"]["readability"]["band"], "Not measured")


class TestSharedFetchAndCrossPage(unittest.TestCase):
    def test_scanners_accept_shared_page_context(self):
        # A page scanner must return identical parsed-derived verdicts whether it
        # fetches itself or is handed a pre-fetched context.
        parsed = htmlmeta.parse_html(GOOD_PAGE)
        render = htmlmeta.render_assessment(parsed, GOOD_PAGE)
        ctx = {"url": "https://acme.example/", "parsed": parsed, "render": render,
               "res": {"ok": True, "body": GOOD_PAGE, "final_url": "https://acme.example/",
                       "final_headers": {}, "body_bytes": len(GOOD_PAGE),
                       "uncompressed_bytes": len(GOOD_PAGE), "content_encoding": ""}}
        r = a11y.scan("https://acme.example/", page=ctx)
        self.assertTrue(r["ok"])
        self.assertEqual(r["checks"]["document_language"]["verdict"], "pass")
        self.assertEqual(r["checks"]["heading_order"]["verdict"], "pass")

    def test_safe_scan_isolates_failures(self):
        def boom(*a, **k):
            raise ValueError("scanner exploded")
        bad = site._safe_scan(boom, "x", tool_name="scan_x")
        self.assertFalse(bad["ok"])
        self.assertIn("ValueError", bad["error"])
        good = site._safe_scan(lambda u: {"ok": True, "checks": {}}, "x")
        self.assertTrue(good["ok"])

    def test_cross_page_duplicate_titles(self):
        pages = [
            {"url": "a", "seo": {"ok": True, "checks": {"title": {"value": "Same Title"},
             "meta_description": {"value": "Desc one"}}}},
            {"url": "b", "seo": {"ok": True, "checks": {"title": {"value": "Same Title"},
             "meta_description": {"value": "Desc two"}}}},
        ]
        cp = site.check_cross_page(pages)
        self.assertEqual(cp["duplicate_titles"]["verdict"], "warn")
        self.assertEqual(cp["duplicate_descriptions"]["verdict"], "pass")

    def test_cross_page_single_page_is_not_applicable(self):
        pages = [{"url": "a", "seo": {"ok": True, "checks": {"title": {"value": "T"},
                  "meta_description": {"value": "D"}}}}]
        self.assertEqual(site.check_cross_page(pages)["duplicate_titles"]["verdict"], "info")


class TestReadability(unittest.TestCase):
    def test_syllables(self):
        self.assertEqual(rd._syllables("cat"), 1)
        self.assertEqual(rd._syllables("code"), 1)       # silent trailing e
        self.assertEqual(rd._syllables("table"), 2)      # 'le' ending keeps its syllable
        self.assertEqual(rd._syllables("readable"), 3)
        self.assertEqual(rd._syllables(""), 0)

    def test_sentences(self):
        self.assertEqual(len(rd._sentences("One. Two? Three!")), 3)
        self.assertEqual(len(rd._sentences("No terminal punctuation")), 1)
        self.assertEqual(rd._sentences("   "), [])


class TestDecompression(unittest.TestCase):
    def test_gzip_roundtrip(self):
        data = b"<html><body>hello world</body></html>" * 50
        self.assertEqual(common._decompress(gzip.compress(data), "gzip"), data)

    def test_gzip_by_magic_bytes_when_header_absent(self):
        data = b"payload" * 20
        self.assertEqual(common._decompress(gzip.compress(data), ""), data)

    def test_deflate_roundtrip(self):
        data = b"deflate me" * 40
        self.assertEqual(common._decompress(zlib.compress(data), "deflate"), data)

    def test_plain_passes_through(self):
        self.assertEqual(common._decompress(b"plain text", ""), b"plain text")


class TestDiscovery(unittest.TestCase):
    def test_section_of_skips_locale(self):
        self.assertEqual(disco._section_of("https://x.com/en-us/products/foo"), "products")
        self.assertEqual(disco._section_of("https://x.com/products/foo"), "products")
        self.assertEqual(disco._section_of("https://x.com/"), "(root)")
        self.assertEqual(disco._section_of("https://x.com/en/"), "(root)")  # locale only

    def test_is_legal(self):
        self.assertTrue(disco._is_legal("https://x.com/privacy-policy"))
        self.assertTrue(disco._is_legal("https://x.com/legal/terms"))
        self.assertFalse(disco._is_legal("https://x.com/products/widget"))

    def test_propose_starts_with_homepage_and_samples_sections(self):
        home = "https://x.com/"
        sections = {"products": ["https://x.com/products", "https://x.com/products/a",
                                  "https://x.com/products/b", "https://x.com/products/c"],
                    "blog": ["https://x.com/blog"]}
        legal = ["https://x.com/privacy"]
        out = disco._propose(home, sections, legal)
        self.assertEqual(out[0], home)
        self.assertIn("https://x.com/products", out)       # section landing (shortest path)
        self.assertLessEqual(len([u for u in out if "/products" in u]), disco.PER_SECTION)
        self.assertIn("https://x.com/privacy", out)


class TestPerfCompressionCaching(unittest.TestCase):
    def test_compression_check(self):
        gz = perf._compression_check({"content_encoding": "gzip", "body_bytes": 100, "uncompressed_bytes": 460})
        self.assertEqual(gz["verdict"], "pass")
        self.assertEqual(gz["ratio"], 4.6)
        none = perf._compression_check({"content_encoding": "", "body_bytes": 1000, "uncompressed_bytes": 1000})
        self.assertEqual(none["verdict"], "warn")

    def test_caching_check(self):
        self.assertEqual(perf._caching_check({"cache-control": "max-age=3600"})["cache_control"], "max-age=3600")
        self.assertIsNone(perf._caching_check({})["cache_control"])


class TestRegistry(unittest.TestCase):
    def test_registry_lists_all_scanners(self):
        ids = {e.tool_id for e in reg.REGISTRY}
        self.assertEqual(ids, {
            "scan_http_security", "scan_tls", "scan_dns_email", "scan_crawl",
            "scan_seo", "scan_accessibility", "scan_links",
            "scan_performance", "scan_readability", "scan_privacy",
            "scan_page_security", "scan_design", "scan_vitals", "scan_crux",
        })
        self.assertEqual(len(reg.host_tools()), 5)
        self.assertEqual(len(reg.page_tools()), 9)

    def test_every_entry_exposes_a_callable_scan(self):
        for e in reg.REGISTRY:
            self.assertTrue(callable(getattr(e.module, "scan", None)),
                            f"{e.tool_id} exposes no callable scan")

    def test_scan_site_sources_page_scanners_from_registry(self):
        expected = [(e.key, e.module, e.label) for e in reg.page_tools()]
        self.assertEqual(site.PAGE_SCANNERS, expected)

    def test_scan_site_scorecard_categories_come_from_registry(self):
        host = {e.key: {"checks": {"a": {"verdict": "pass"}}} for e in reg.host_tools()}
        sc = site.build_scorecard(host, [])
        for e in reg.host_tools():
            self.assertIn(e.category, sc["categories"])

    def test_by_id_roundtrip(self):
        self.assertEqual(reg.by_id("scan_tls").key, "tls")
        self.assertIsNone(reg.by_id("scan_nonexistent"))

    def test_scope_and_category_are_read_from_the_module(self):
        for e in reg.REGISTRY:
            self.assertEqual(e.scope, e.module.SCOPE,
                             f"{e.tool_id} scope not sourced from module.SCOPE")
            self.assertEqual(e.category, e.module.CATEGORY,
                             f"{e.tool_id} category not sourced from module.CATEGORY")
            self.assertIn(e.scope, ("host", "page"))


# Canned network responses so the contract test runs offline and fast. Every
# scanner reaches the network only through common.http_fetch / common.tls_info /
# common.doh_query (and scan_tls._probe_legacy), so stubbing those four covers
# every tool without a single real request.
VERDICTS = {"pass", "warn", "fail", "info"}


def _canned_fetch(url, *args, **kwargs):
    return {
        "ok": True, "error": None, "requested_url": url,
        "hops": [{"url": url, "status": 200, "headers": {}}],
        "final_url": url, "final_status": 200,
        "final_headers": {"content-type": "text/html; charset=utf-8",
                          "cache-control": "max-age=3600"},
        "content_type": "text/html; charset=utf-8", "content_encoding": "",
        "body": GOOD_PAGE, "body_bytes": len(GOOD_PAGE),
        "uncompressed_bytes": len(GOOD_PAGE), "elapsed_ms": 1,
    }


def _canned_tls(host, *args, **kwargs):
    return {"ok": True, "error": None, "protocol": "TLSv1.3",
            "cipher": ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256),
            "cert": {"subject": ((("commonName", host),),),
                     "issuer": ((("organizationName", "Test CA"),),),
                     "subjectAltName": (("DNS", host),),
                     "notAfter": "Jan 15 12:00:00 2035 GMT",
                     "notBefore": "Jan 15 12:00:00 2024 GMT"}}


def _canned_doh(name, rtype, *args, **kwargs):
    return {"ok": True, "error": None, "status": 0, "ad": True,
            "answers": ["v=spf1 -all"], "raw": [{"data": "v=spf1 -all"}]}


def _down_fetch(url, *args, **kwargs):
    return {"ok": False, "error": "stubbed offline", "requested_url": url,
            "hops": [], "final_url": url, "final_status": None, "final_headers": {},
            "content_type": "", "content_encoding": "", "body": None,
            "body_bytes": 0, "uncompressed_bytes": 0, "elapsed_ms": 0}


def _down_tls(host, *args, **kwargs):
    return {"ok": False, "error": "stubbed offline", "protocol": None,
            "cipher": None, "cert": None}


def _down_doh(name, rtype, *args, **kwargs):
    return {"ok": False, "error": "stubbed offline", "status": None,
            "ad": False, "answers": [], "raw": []}


class TestToolContract(unittest.TestCase):
    """Every registered tool must satisfy the PLAN.md section 4 contract. Checked
    offline by stubbing the network primitives, so a new tool that breaks the
    shape (missing verdict, wrong tool id, raising on failure) fails CI here."""

    TARGET = "https://acme.example/"

    def setUp(self):
        self._orig = (common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy)

    def tearDown(self):
        common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy = self._orig

    def _patch(self, fetch, tlsinfo, doh):
        common.http_fetch = fetch
        common.tls_info = tlsinfo
        common.doh_query = doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}

    def _assert_conformant(self, entry, result):
        self.assertIsInstance(result, dict, f"{entry.tool_id} did not return a dict")
        self.assertEqual(result.get("tool"), entry.tool_id,
                         f"{entry.tool_id} 'tool' field does not match its registry id")
        if "checks" in result:
            for name, c in result["checks"].items():
                self.assertIn(c.get("verdict"), VERDICTS,
                              f"{entry.tool_id}.{name} has an invalid verdict {c.get('verdict')!r}")
                self.assertIsInstance(c.get("note"), str,
                                      f"{entry.tool_id}.{name} has no string note")
        else:
            failed = result.get("ok") is False and bool(result.get("error"))
            self.assertTrue(result.get("verdict") in VERDICTS or failed,
                            f"{entry.tool_id} has no checks, no top-level verdict, and is not a failure")
        if result.get("ok") is False:
            self.assertTrue(result.get("error"),
                            f"{entry.tool_id} reported ok:false without an error string")

    def test_success_shape_for_every_registered_tool(self):
        self._patch(_canned_fetch, _canned_tls, _canned_doh)
        for entry in reg.REGISTRY:
            result = entry.module.scan(self.TARGET)
            self._assert_conformant(entry, result)
            self.assertIn("checks", result, f"{entry.tool_id} produced no checks on a healthy target")
            self.assertEqual(result.get("category"), entry.category,
                             f"{entry.tool_id} did not surface its category in the result")
            grade = result.get("grade")
            self.assertIsInstance(grade, dict, f"{entry.tool_id} did not surface a grade")
            self.assertIn(grade.get("band"),
                          {"Strong", "Adequate", "Weak", "Poor", "Not measured"},
                          f"{entry.tool_id} grade has an invalid band")

    def test_no_tool_raises_on_network_failure(self):
        self._patch(_down_fetch, _down_tls, _down_doh)
        for entry in reg.REGISTRY:
            try:
                result = entry.module.scan(self.TARGET)
            except Exception as e:
                self.fail(f"{entry.tool_id} raised on network failure: {type(e).__name__}: {e}")
            self._assert_conformant(entry, result)

    def test_safe_scan_wraps_a_raising_tool_as_ok_false(self):
        def boom(*a, **k):
            raise RuntimeError("kaboom")
        for entry in reg.REGISTRY:
            wrapped = site._safe_scan(boom, self.TARGET, tool_name=entry.tool_id)
            self.assertFalse(wrapped["ok"])
            self.assertIn("RuntimeError", wrapped["error"])


class TestPrivacy(unittest.TestCase):
    def _ctx(self, html):
        parsed = htmlmeta.parse_html(html)
        render = htmlmeta.render_assessment(parsed, html)
        return {"url": "https://acme.example/", "parsed": parsed, "render": render,
                "res": {"ok": True, "body": html, "final_url": "https://acme.example/",
                        "error": None}}

    def test_third_parties_by_registrable_domain(self):
        urls = ["https://cdn.acme.example/a.js",
                "https://www.google-analytics.com/ga.js",
                "https://acme.example/local.js"]
        tp = privacy._third_parties(urls, "acme.example")
        self.assertIn("google-analytics.com", tp)
        self.assertNotIn("acme.example", tp)

    def test_known_tracker_match(self):
        found = privacy._match_trackers(["https://www.googletagmanager.com/gtm.js",
                                         "https://cdn.acme.example/x.js"])
        self.assertEqual(found.get("googletagmanager.com"), "analytics")

    def test_tracking_pixel_detection(self):
        body = ('<img src="https://x.example/p.gif" width="1" height="1">'
                '<img src="/logo.png" width="200" height="50">')
        pixels = privacy._tracking_pixels(body, "https://acme.example/")
        self.assertEqual(len(pixels), 1)
        self.assertIn("p.gif", pixels[0])

    def test_consent_detected_by_host_and_marker(self):
        self.assertTrue(privacy._consent_detected(
            '<script src="https://consent.cookiebot.com/uc.js"></script>'))
        self.assertTrue(privacy._consent_detected('<div class="cookie-consent-banner">'))
        self.assertFalse(privacy._consent_detected('<div>no banner here</div>'))

    def test_consent_verdict_matrix(self):
        self.assertEqual(privacy._consent_verdict(True, True)["verdict"], "pass")
        self.assertEqual(privacy._consent_verdict(False, True)["verdict"], "warn")
        self.assertEqual(privacy._consent_verdict(False, False)["verdict"], "info")

    def test_full_scan_flags_trackers_pixels_and_missing_consent(self):
        html = ('<!doctype html><html lang="en"><head><title>Home page</title></head>'
                '<body><h1>Hi</h1><p>Some real body text for the page content here.</p>'
                '<script src="https://www.google-analytics.com/analytics.js"></script>'
                '<img src="https://acme.example/pixel.gif" width="1" height="1">'
                '</body></html>')
        r = privacy.scan("https://acme.example/", page=self._ctx(html))
        self.assertTrue(r["ok"])
        self.assertEqual(r["checks"]["known_trackers"]["verdict"], "warn")
        self.assertEqual(r["checks"]["tracking_pixels"]["verdict"], "warn")
        self.assertEqual(r["checks"]["cookie_consent"]["verdict"], "warn")
        self.assertEqual(r["category"], "privacy")
        self.assertIn(r["grade"]["band"],
                      {"Strong", "Adequate", "Weak", "Poor", "Not measured"})

    def test_clean_page_passes(self):
        html = ('<!doctype html><html lang="en"><head><title>Home page</title></head>'
                '<body><h1>Hi</h1><p>Plain first-party content only, nothing external.</p>'
                '</body></html>')
        r = privacy.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["known_trackers"]["verdict"], "pass")
        self.assertEqual(r["checks"]["tracking_pixels"]["verdict"], "pass")

    def test_client_rendered_is_inconclusive(self):
        r = privacy.scan("https://acme.example/", page=self._ctx(SPA_SHELL))
        self.assertEqual(r["checks"]["known_trackers"]["verdict"], "info")
        self.assertEqual(r["checks"]["third_party_origins"]["verdict"], "info")


class TestFetchCache(unittest.TestCase):
    """The per-run fetch cache (PLAN.md section 16), tested through http_fetch
    with a counting fake opener so no real request is made."""

    class _FakeResponse:
        def __init__(self, status=200):
            import email.message
            self.headers = email.message.Message()
            self.headers["Content-Type"] = "text/html"
            self.status = status

        def read(self, n):
            return b"hello"

        def close(self):
            pass

    def setUp(self):
        self.calls = []
        self._orig_opener = common._opener
        common.disable_fetch_cache()

    def tearDown(self):
        common._opener = self._orig_opener
        common.disable_fetch_cache()

    def _install_opener(self, fail=False):
        calls = self.calls
        fake_response = self._FakeResponse

        class _FakeOpener:
            def open(self, req, timeout=None):
                calls.append((req.get_method(), req.full_url))
                if fail:
                    raise urllib.error.URLError("stubbed down")
                return fake_response()

        common._opener = lambda: _FakeOpener()

    def test_repeat_get_is_served_from_cache(self):
        self._install_opener()
        common.enable_fetch_cache()
        first = common.http_fetch("https://acme.example/")
        second = common.http_fetch("https://acme.example/")
        self.assertEqual(len(self.calls), 1)
        self.assertIs(first, second)

    def test_head_and_get_do_not_cross_satisfy(self):
        self._install_opener()
        common.enable_fetch_cache()
        common.http_fetch("https://acme.example/", method="HEAD", want_body=False)
        common.http_fetch("https://acme.example/")
        self.assertEqual(len(self.calls), 2)

    def test_disabled_cache_fetches_every_time(self):
        self._install_opener()
        common.http_fetch("https://acme.example/")
        common.http_fetch("https://acme.example/")
        self.assertEqual(len(self.calls), 2)

    def test_failures_are_not_cached(self):
        self._install_opener(fail=True)
        common.enable_fetch_cache()
        first = common.http_fetch("https://acme.example/")
        second = common.http_fetch("https://acme.example/")
        self.assertFalse(first["ok"])
        self.assertEqual(len(self.calls), 2)
        self.assertIsNot(first, second)

    def test_enable_keeps_entries_when_already_on(self):
        self._install_opener()
        common.enable_fetch_cache()
        common.http_fetch("https://acme.example/")
        common.enable_fetch_cache()  # e.g. run_review enabled, then scan_site.run
        common.http_fetch("https://acme.example/")
        self.assertEqual(len(self.calls), 1)

    def test_scan_site_run_disables_the_cache_afterward(self):
        orig = (common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy)
        common.http_fetch, common.tls_info, common.doh_query = _canned_fetch, _canned_tls, _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        try:
            site.run("https://acme.example/", [])
        finally:
            common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy = orig
        self.assertIsNone(common._FETCH_CACHE)


class TestRunLevelDedup(unittest.TestCase):
    """Orchestrator-level integration for the per-run cache: across a
    two-page scan of the same host, every HEAD probe (link checks, resource
    measurement, favicon) goes out exactly once even though both pages
    declare the same links and assets. Runs the real http_fetch over a fake
    opener; TLS and DoH are stubbed."""

    class _FakeResponse:
        def __init__(self):
            import email.message
            self.headers = email.message.Message()
            self.headers["Content-Type"] = "text/html; charset=utf-8"
            self.status = 200

        def read(self, n):
            return GOOD_PAGE.encode()

        def close(self):
            pass

    def test_two_page_scan_repeats_no_head_request(self):
        calls = []
        fake_response = self._FakeResponse

        class _FakeOpener:
            def open(self, req, timeout=None):
                calls.append((req.get_method(), req.full_url))
                return fake_response()

        orig = (common._opener, common.tls_info, common.doh_query, tls._probe_legacy)
        common._opener = lambda: _FakeOpener()
        common.tls_info = _canned_tls
        common.doh_query = _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        try:
            result = site.run("https://acme.example/", ["https://acme.example/about"])
        finally:
            common._opener, common.tls_info, common.doh_query, tls._probe_legacy = orig

        self.assertEqual(len(result["pages_scanned"]), 2)
        head_counts = {}
        for method, url in calls:
            if method == "HEAD":
                head_counts[url] = head_counts.get(url, 0) + 1
        repeated = {u: n for u, n in head_counts.items() if n > 1}
        self.assertEqual(repeated, {}, f"HEAD requests repeated within one run: {repeated}")
        self.assertIsNone(common._FETCH_CACHE)


class TestAssetCachingAndRedirects(unittest.TestCase):
    def test_cache_max_age_parsing(self):
        self.assertEqual(perf._cache_max_age("public, max-age=31536000, immutable"), 31536000)
        self.assertEqual(perf._cache_max_age("max-age=0"), 0)
        self.assertIsNone(perf._cache_max_age("no-store"))
        self.assertIsNone(perf._cache_max_age(None))
        self.assertEqual(perf._cache_max_age(["public", "max-age=60"]), 60)

    def test_mostly_uncached_assets_warn(self):
        measured = [
            {"url": "https://a/1.js", "status": 200, "cache_control": None},
            {"url": "https://a/2.css", "status": 200, "cache_control": "no-store"},
            {"url": "https://a/3.png", "status": 200, "cache_control": "max-age=86400"},
        ]
        c = perf._asset_caching_check(measured, inconclusive=False)
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["uncached"], 2)

    def test_cached_assets_pass_and_immutable_counts(self):
        measured = [
            {"url": "https://a/1.js", "status": 200, "cache_control": "public, immutable"},
            {"url": "https://a/2.css", "status": 200, "cache_control": "max-age=604800"},
        ]
        c = perf._asset_caching_check(measured, inconclusive=False)
        self.assertEqual(c["verdict"], "pass")
        self.assertEqual(c["uncached"], 0)

    def test_no_cache_directive_defeats_max_age(self):
        measured = [
            {"url": "https://a/1.js", "status": 200, "cache_control": "no-cache, max-age=600"},
        ]
        c = perf._asset_caching_check(measured, inconclusive=False)
        self.assertEqual(c["verdict"], "warn")

    def test_nothing_measured_is_info(self):
        self.assertEqual(perf._asset_caching_check([], False)["verdict"], "info")
        self.assertEqual(perf._asset_caching_check(
            [{"url": "u", "status": 200, "cache_control": None}], True)["verdict"], "info")

    def test_redirect_chain_verdicts(self):
        hop = lambda u, s: {"url": u, "status": s, "headers": {}}
        none = perf._redirect_chain_check({"hops": [hop("https://a/", 200)]})
        one = perf._redirect_chain_check({"hops": [hop("http://a/", 301), hop("https://a/", 200)]})
        two = perf._redirect_chain_check({"hops": [hop("http://a", 301), hop("https://a", 301),
                                                   hop("https://www.a/", 200)]})
        self.assertEqual(none["verdict"], "pass")
        self.assertEqual(none["redirects"], 0)
        self.assertEqual(one["verdict"], "pass")
        self.assertEqual(two["verdict"], "warn")
        self.assertEqual(two["redirects"], 2)


class TestHostCanonicalization(unittest.TestCase):
    def _fetch_stub(self, behavior):
        """behavior: host -> (final_status, final_url) or None for unreachable."""
        def fetch(url, *a, **k):
            host = url.split("//", 1)[1].split("/", 1)[0]
            spec = behavior.get(host)
            if spec is None:
                return {"ok": False, "error": "unreachable", "hops": [], "final_url": url,
                        "final_status": None, "final_headers": {}, "body": None,
                        "content_type": "", "content_encoding": "", "body_bytes": 0,
                        "uncompressed_bytes": 0, "elapsed_ms": 0, "requested_url": url}
            status, final = spec
            return {"ok": True, "error": None,
                    "hops": [{"url": final, "status": status, "headers": {}}],
                    "final_url": final, "final_status": status, "final_headers": {},
                    "body": None, "content_type": "", "content_encoding": "",
                    "body_bytes": 0, "uncompressed_bytes": 0, "elapsed_ms": 1,
                    "requested_url": url}
        return fetch

    def _run(self, host, behavior):
        orig = common.http_fetch
        common.http_fetch = self._fetch_stub(behavior)
        try:
            return crawl.check_host_canonicalization(host)
        finally:
            common.http_fetch = orig

    def test_www_redirecting_to_apex_passes(self):
        c = self._run("acme.example", {
            "acme.example": (200, "https://acme.example/"),
            "www.acme.example": (200, "https://acme.example/"),
        })
        self.assertEqual(c["verdict"], "pass")
        self.assertEqual(c["canonical_host"], "acme.example")

    def test_both_live_without_convergence_warns(self):
        c = self._run("acme.example", {
            "acme.example": (200, "https://acme.example/"),
            "www.acme.example": (200, "https://www.acme.example/"),
        })
        self.assertEqual(c["verdict"], "warn")

    def test_unreachable_variant_is_info(self):
        c = self._run("acme.example", {
            "acme.example": (200, "https://acme.example/"),
            "www.acme.example": None,
        })
        self.assertEqual(c["verdict"], "info")
        self.assertEqual(c["unreachable"], "www.acme.example")

    def test_subdomain_site_is_not_applicable(self):
        c = self._run("blog.acme.example", {})
        self.assertEqual(c["verdict"], "info")
        self.assertIn("subdomain", c["note"])


class TestIssueGroupingAndDelta(unittest.TestCase):
    ISSUES = [
        {"scan": "a11y:https://x/a", "check": "landmarks", "verdict": "warn", "note": "Missing landmark(s): main."},
        {"scan": "a11y:https://x/b", "check": "landmarks", "verdict": "warn", "note": "Missing landmark(s): main."},
        {"scan": "a11y:https://x/c", "check": "landmarks", "verdict": "warn", "note": "Missing landmark(s): main."},
        {"scan": "seo:https://x/a", "check": "headings", "verdict": "fail", "note": "No H1 on the page."},
        {"scan": "http_security", "check": "hsts", "verdict": "fail", "note": "No HSTS header."},
    ]

    def test_grouping_collapses_per_page_repeats(self):
        groups = site.group_issues(self.ISSUES)
        self.assertEqual(len(groups), 3)
        landmarks = next(g for g in groups if g["check"] == "landmarks")
        self.assertEqual(landmarks["scan"], "a11y")
        self.assertEqual(landmarks["page_count"], 3)
        self.assertEqual(landmarks["pages"], ["https://x/a", "https://x/b", "https://x/c"])

    def test_host_issue_passes_through_without_pages(self):
        groups = site.group_issues(self.ISSUES)
        hsts = next(g for g in groups if g["check"] == "hsts")
        self.assertEqual(hsts["pages"], [])
        self.assertEqual(hsts["page_count"], 0)

    def test_distinct_verdicts_stay_apart(self):
        issues = [dict(self.ISSUES[0]), {**self.ISSUES[1], "verdict": "fail"}]
        self.assertEqual(len(site.group_issues(issues)), 2)

    def test_issue_line_names_pages(self):
        groups = site.group_issues(self.ISSUES)
        line = site.issue_line(next(g for g in groups if g["check"] == "landmarks"))
        self.assertIn("on 3 page(s)", line)
        self.assertIn("+1 more", line)

    def test_diff_issues_reports_new_and_resolved(self):
        prev = {"measured_at_utc": "2026-07-01T00:00:00Z",
                "issues": {"fail": [self.ISSUES[3]], "warn": [self.ISSUES[0]]}}
        curr = {"issues": {"fail": [self.ISSUES[4]], "warn": [self.ISSUES[0]]}}
        delta = site.diff_issues(prev, curr)
        self.assertEqual(delta["previous_measured_at"], "2026-07-01T00:00:00Z")
        self.assertEqual([i["check"] for i in delta["new"]], ["hsts"])
        self.assertEqual([i["check"] for i in delta["resolved"]], ["headings"])

    def test_attach_delta_reads_previous_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x_scan.json"
            prev = {"measured_at_utc": "2026-07-01T00:00:00Z",
                    "issues": {"fail": [self.ISSUES[3]], "warn": []}}
            path.write_text(json.dumps(prev), encoding="utf-8")
            result = {"issues": {"fail": [], "warn": []}}
            site.attach_delta(result, path)
            self.assertEqual(len(result["delta"]["resolved"]), 1)
            fresh = {"issues": {"fail": [], "warn": []}}
            site.attach_delta(fresh, Path(tmp) / "missing.json")
            self.assertNotIn("delta", fresh)

    def test_draft_consumes_grouped_issues(self):
        scan = {
            "slug": "x", "host": "x", "target": "https://x/",
            "measured_at_utc": "2026-07-02T00:00:00Z",
            "totals": {"fail": 4, "warn": 0},
            "pages_scanned": ["https://x/a"],
            "scorecard": {"overall": {"band": "Weak"}, "categories": {}},
            "issues": {"fail": self.ISSUES[:4], "warn": []},
            "issues_grouped": {"fail": site.group_issues(self.ISSUES[:4]), "warn": []},
        }
        data = drpt.draft(scan)
        landmarks = next(f for f in data["findings"] if "landmarks" in f["finding"])
        self.assertEqual(landmarks["area"], "a11y")
        self.assertIn("3 page(s)", landmarks["evidence"])
        # One grouped finding, not three per-page duplicates.
        self.assertEqual(sum(1 for f in data["findings"] if "landmarks" in f["finding"]), 1)


class TestCrux(unittest.TestCase):
    RECORD = {"record": {"metrics": {
        "largest_contentful_paint": {"percentiles": {"p75": 2100}},
        "cumulative_layout_shift": {"percentiles": {"p75": "0.31"}},
        "interaction_to_next_paint": {"percentiles": {"p75": 350}},
    }}}

    def _run(self, key="k", post=None):
        orig = (common.env_value, common.http_post_json)
        common.env_value = lambda name: key
        common.http_post_json = post or (lambda url, payload, timeout=None: {
            "ok": True, "status": 200, "json": self.RECORD, "error": None})
        try:
            return crux_scan.scan("https://acme.example/")
        finally:
            common.env_value, common.http_post_json = orig

    def test_threshold_grading_from_a_canned_record(self):
        r = self._run()
        self.assertEqual(r["checks"]["field_lcp"]["verdict"], "pass")
        self.assertEqual(r["checks"]["field_cls"]["verdict"], "fail")   # string p75 parsed
        self.assertEqual(r["checks"]["field_inp"]["verdict"], "warn")
        self.assertEqual(r["category"], "performance")
        self.assertIn("real Chrome users", r["checks"]["field_lcp"]["note"])

    def test_no_key_is_not_measured(self):
        r = self._run(key=None)
        self.assertFalse(r["queried"])
        self.assertEqual({c["verdict"] for c in r["checks"].values()}, {"info"})
        self.assertEqual(r["grade"]["band"], "Not measured")

    def test_origin_absent_from_dataset_is_info(self):
        r = self._run(post=lambda url, payload, timeout=None: {
            "ok": False, "status": 404, "json": None, "error": "HTTP 404"})
        self.assertEqual({c["verdict"] for c in r["checks"].values()}, {"info"})
        self.assertIn("not in the CrUX dataset", r["checks"]["field_lcp"]["note"])

    def test_api_error_is_info_never_fabricated(self):
        r = self._run(post=lambda url, payload, timeout=None: {
            "ok": False, "status": 500, "json": None, "error": "HTTP 500"})
        self.assertEqual({c["verdict"] for c in r["checks"].values()}, {"info"})


class TestShakedownFixes(unittest.TestCase):
    """Regressions for defects confirmed on real sites (I2)."""

    def test_logo_link_with_img_alt_is_not_empty(self):
        # Found on client-a.example and python.org: a home link wrapping an
        # image WITH alt text is accessible and was falsely flagged empty.
        html = ('<a href="/"><img src="/logo.png" alt="Acme logo"></a>'
                '<a href="/bare"><img src="/x.png"></a>')
        parsed = htmlmeta.parse_html(html)
        self.assertEqual(parsed["anchors"][0]["img_alt"], "Acme logo")
        self.assertIsNone(parsed["anchors"][1]["img_alt"])
        c = a11y._link_text_check(parsed, inconclusive=False)
        self.assertEqual(c["verdict"], "fail")
        self.assertEqual(c["examples"], ["/bare"])
        clean = htmlmeta.parse_html('<a href="/"><img src="/l.png" alt="Logo"></a>')
        ok = a11y._link_text_check(clean, inconclusive=False)
        self.assertEqual(ok["verdict"], "pass")

    def test_list_like_pages_are_not_graded_as_prose(self):
        # Found on python.org event listings: hundreds of words with almost no
        # sentence punctuation drove Flesch to -13.6. Not prose; report info.
        listing = " ".join(f"Event {i} Springfield March {i}" for i in range(60)) + "."
        html = f"<html><body><p>{listing}</p></body></html>"
        parsed = htmlmeta.parse_html(html)
        render = htmlmeta.render_assessment(parsed, html)
        ctx = {"url": "https://acme.example/", "parsed": parsed, "render": render,
               "res": {"ok": True, "body": html, "final_url": "https://acme.example/",
                       "error": None}}
        r = rd.scan("https://acme.example/", page=ctx)
        c = r["checks"]["readability"]
        self.assertEqual(c["verdict"], "info")
        self.assertIn("not meaningful", c["note"])

    def test_link_heavy_pages_are_not_graded_as_prose(self):
        # Event-listing pages punctuate enough to dodge the sentence guard but
        # most visible words are link text; still not prose.
        items = " ".join(
            f'<a href="/e{i}">Regional Python Conference Number {i} Spring.</a>'
            for i in range(40))
        html = f"<html><body><p>A few plain words here.</p>{items}</body></html>"
        parsed = htmlmeta.parse_html(html)
        render = htmlmeta.render_assessment(parsed, html)
        ctx = {"url": "https://acme.example/", "parsed": parsed, "render": render,
               "res": {"ok": True, "body": html, "final_url": "https://acme.example/",
                       "error": None}}
        r = rd.scan("https://acme.example/", page=ctx)
        c = r["checks"]["readability"]
        self.assertEqual(c["verdict"], "info")
        self.assertIn("link text", c["note"])


class TestCrawler(unittest.TestCase):
    SITE = {
        "https://acme.example/robots.txt":
            "User-agent: *\nDisallow: /private/\nCrawl-delay: 2",
        "https://acme.example/":
            '<a href="/a">a</a> <a href="/b">b</a> <a href="/private/x">p</a> '
            '<a href="/file.pdf">pdf</a> <a href="https://other.example/">ext</a>',
        "https://acme.example/a": '<a href="/b">b</a> <a href="/c">c</a>',
        "https://acme.example/b": '<a href="/">home</a>',
        "https://acme.example/c": "no links here",
    }

    def setUp(self):
        self.fetches = []
        self.sleeps = []
        self._orig = common.http_fetch
        site_map = self.SITE
        fetches = self.fetches

        def fetch(url, *a, **k):
            fetches.append(url)
            body = site_map.get(url)
            status = 200 if body is not None else 404
            return {"ok": body is not None, "error": None,
                    "hops": [{"url": url, "status": status, "headers": {}}],
                    "final_url": url, "final_status": status, "final_headers": {},
                    "content_type": "text/html", "content_encoding": "",
                    "body": body, "body_bytes": len(body or ""),
                    "uncompressed_bytes": len(body or ""), "elapsed_ms": 1,
                    "requested_url": url}

        common.http_fetch = fetch

    def tearDown(self):
        common.http_fetch = self._orig

    def test_bfs_respects_robots_extensions_and_domain(self):
        import crawler
        r = crawler.crawl("https://acme.example/", max_pages=10,
                          delay=1.0, sleep=self.sleeps.append)
        self.assertEqual(r["pages"], ["https://acme.example/", "https://acme.example/a",
                                      "https://acme.example/b", "https://acme.example/c"])
        self.assertEqual(r["stats"]["skipped_by_robots"], 1)
        self.assertNotIn("https://acme.example/file.pdf", self.fetches)
        self.assertNotIn("https://other.example/", self.fetches)
        # Crawl-delay: 2 raises the 1.0s default; one wait between each fetch.
        self.assertTrue(self.sleeps and all(s == 2.0 for s in self.sleeps))

    def test_page_cap_is_enforced(self):
        import crawler
        r = crawler.crawl("https://acme.example/", max_pages=2,
                          delay=0, sleep=self.sleeps.append)
        self.assertEqual(len(r["pages"]), 2)

    def test_resume_does_not_refetch_visited_pages(self):
        import crawler
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            crawler.crawl("https://acme.example/", max_pages=2, delay=0,
                          state_path=state, sleep=self.sleeps.append)
            first_fetches = list(self.fetches)
            self.fetches.clear()
            r = crawler.crawl("https://acme.example/", max_pages=4, delay=0,
                              state_path=state, sleep=self.sleeps.append)
        self.assertIn("https://acme.example/", first_fetches)
        self.assertEqual(len(r["pages"]), 4)
        # The resumed run fetched only robots.txt plus the unvisited frontier.
        self.assertNotIn("https://acme.example/", self.fetches)
        self.assertNotIn("https://acme.example/a", self.fetches)
        self.assertIn("https://acme.example/b", self.fetches)


class TestFindingsHistory(unittest.TestCase):
    RESULT = {
        "measured_at_utc": "2026-07-03T10:00:00Z",
        "target": "https://acme.example/",
        "pages_scanned": ["https://acme.example/"],
        "totals": {"fail": 1, "warn": 1, "grouped_fail": 1, "grouped_warn": 1},
        "scorecard": {"overall": {"band": "Adequate", "pass": 3, "warn": 1, "fail": 1,
                                  "info": 0, "graded": 5, "score": 0.7},
                      "categories": {"seo": {"band": "Strong", "pass": 3, "warn": 1,
                                             "fail": 0, "info": 0, "graded": 4, "score": 0.88},
                                     "security": {"band": "Poor", "pass": 0, "warn": 0,
                                                  "fail": 1, "info": 0, "graded": 1,
                                                  "score": 0.0}}},
        "issues": {
            "fail": [{"scan": "http_security", "check": "hsts", "verdict": "fail",
                      "note": "No HSTS header. " + "x" * 300}],
            "warn": [{"scan": "seo:https://acme.example/", "check": "title",
                      "verdict": "warn", "note": "Title is short."}],
        },
    }

    def test_history_entry_fields_and_note_truncation(self):
        e = site.history_entry(self.RESULT)
        self.assertEqual(e["measured_at_utc"], "2026-07-03T10:00:00Z")
        self.assertEqual(e["pages_scanned"], 1)
        self.assertEqual(e["bands"], {"overall": "Adequate", "seo": "Strong",
                                      "security": "Poor"})
        self.assertLessEqual(len(e["issues"]["fail"][0]["note"]), 160)

    def test_append_and_read_roundtrip_skips_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            site.append_history(self.RESULT, path)
            with open(path, "a", encoding="utf-8") as f:
                f.write("{not json\n")
            site.append_history(self.RESULT, path)
            entries = site.read_history(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["target"], "https://acme.example/")

    def test_delta_prefers_ledger_over_stale_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "x_scan.json"
            history_path = Path(tmp) / "x_history.jsonl"
            # Stale JSON says the hsts fail already existed; the ledger's last
            # run does not have it, so the delta must report it as NEW.
            json_path.write_text(json.dumps(self.RESULT), encoding="utf-8")
            older = dict(self.RESULT)
            older = json.loads(json.dumps(older))
            older["measured_at_utc"] = "2026-07-02T10:00:00Z"
            older["issues"] = {"fail": [], "warn": self.RESULT["issues"]["warn"]}
            site.append_history(older, history_path)
            current = json.loads(json.dumps(self.RESULT))
            site.attach_delta(current, json_path, history_path)
        self.assertEqual(current["delta"]["previous_measured_at"], "2026-07-02T10:00:00Z")
        self.assertEqual([i["check"] for i in current["delta"]["new"]], ["hsts"])

    def test_delta_falls_back_to_scan_json_without_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "x_scan.json"
            json_path.write_text(json.dumps(self.RESULT), encoding="utf-8")
            current = json.loads(json.dumps(self.RESULT))
            current["issues"] = {"fail": [], "warn": []}
            site.attach_delta(current, json_path, Path(tmp) / "absent.jsonl")
        self.assertEqual(len(current["delta"]["resolved"]), 2)

    def test_digest_trend_section(self):
        older = json.loads(json.dumps(self.RESULT))
        older["measured_at_utc"] = "2026-07-02T10:00:00Z"
        older["scorecard"]["overall"]["band"] = "Weak"
        history = [site.history_entry(older), site.history_entry(self.RESULT)]
        result = json.loads(json.dumps(self.RESULT))
        result["host"] = "acme.example"
        result["slug"] = "acme-example"
        result["issues_grouped"] = {"fail": site.group_issues(result["issues"]["fail"]),
                                    "warn": site.group_issues(result["issues"]["warn"])}
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "digest.md"
            site.write_digest_md(result, md, history=history)
            text = md.read_text(encoding="utf-8")
        self.assertIn("## Trend (last 2 runs)", text)
        self.assertIn("overall Weak", text)
        self.assertIn("Overall band moved: Weak -> Adequate.", text)


class TestTrendMetrics(unittest.TestCase):
    def _page(self, lcp=2000, weight=1500.0, ease=55.0, broken=1, checked=10,
              mixed=0, domains=("a.example",), trackers=(), captured=True):
        vit = {"captured": captured, "checks": {}}
        if captured:
            vit["checks"] = {"lcp": {"value": lcp, "verdict": "pass"},
                             "cls": {"value": 0.05, "verdict": "pass"},
                             "tbt": {"value": 100, "verdict": "pass"}}
        return {
            "url": "https://acme.example/",
            "vitals": vit,
            "performance": {"ok": True, "checks": {"static_weight": {
                "total_floor_kb": weight, "verdict": "pass"}}},
            "readability": {"ok": True, "checks": {"reading_ease": {
                "flesch_reading_ease": ease, "verdict": "pass"}}},
            "links": {"ok": True, "checks": {
                "link_health": {"checked": checked, "counts": {"broken": broken}},
                "mixed_content": {"count": mixed}}},
            "privacy": {"ok": True, "checks": {
                "third_party_origins": {"count": len(domains),
                                        "domains": list(domains)},
                "known_trackers": {"trackers": {t: 1 for t in trackers}}}},
        }

    def _result(self, pages):
        return {"scorecard": {"overall": {"score": 0.8, "band": "Strong"},
                              "categories": {"seo": {"score": 0.9, "band": "Strong"}}},
                "page_scans": pages}

    def test_metrics_rollup_medians_and_counts(self):
        m = site.collect_metrics(self._result([
            self._page(lcp=1000, weight=100.0, ease=40.0, broken=1, checked=10,
                       domains=("a.example",), trackers=("t.example",)),
            self._page(lcp=3000, weight=300.0, ease=60.0, broken=2, checked=20,
                       domains=("a.example", "b.example", "c.example")),
            self._page(lcp=2000, weight=200.0, ease=50.0, broken=0, checked=5,
                       mixed=2, domains=("d.example",)),
        ]))
        self.assertEqual(m["scores"], {"overall": 0.8, "seo": 0.9})
        self.assertEqual(m["pages"]["median_lcp_ms"], 2000)
        self.assertEqual(m["pages"]["median_weight_kb"], 200.0)
        self.assertEqual(m["pages"]["max_weight_kb"], 300.0)
        self.assertEqual(m["pages"]["median_reading_ease"], 50.0)
        self.assertEqual(m["pages"]["broken_links"], 3)
        self.assertEqual(m["pages"]["links_checked"], 35)
        self.assertEqual(m["pages"]["mixed_content"], 2)
        # Max of per-page counts (1, 3, 1), not the cross-page union (4):
        # the scanner truncates each page's domains list, so only the
        # per-page count field is exact.
        self.assertEqual(m["pages"]["third_party_origins"], 3)
        self.assertEqual(m["pages"]["known_trackers"], 1)
        self.assertTrue(m["vitals_captured"])

    def test_even_page_count_uses_midpoint_median(self):
        m = site.collect_metrics(self._result(
            [self._page(lcp=1000), self._page(lcp=3000)]))
        self.assertEqual(m["pages"]["median_lcp_ms"], 2000)

    def test_uncaptured_vitals_are_gaps_not_zeros(self):
        m = site.collect_metrics(self._result([self._page(captured=False)]))
        self.assertIsNone(m["pages"]["median_lcp_ms"])
        self.assertIsNone(m["pages"]["median_cls"])
        self.assertFalse(m["vitals_captured"])

    def test_missing_page_scans_yield_all_gaps(self):
        m = site.collect_metrics({"scorecard": {}})
        self.assertIsNone(m["pages"]["median_weight_kb"])
        self.assertIsNone(m["pages"]["broken_links"])
        self.assertIsNone(m["pages"]["third_party_origins"])
        self.assertEqual(m["scores"], {"overall": None})
        self.assertFalse(m["vitals_captured"])

    def test_history_entry_carries_metrics(self):
        e = site.history_entry(TestFindingsHistory.RESULT)
        self.assertIn("metrics", e)
        self.assertEqual(e["metrics"]["scores"]["overall"], 0.7)
        self.assertEqual(e["metrics"]["scores"]["seo"], 0.88)


class TestVitals(unittest.TestCase):
    URL = "https://acme.example/"

    def _with_metrics(self, entry):
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name) / "rendered" / "acme-example"
        base.mkdir(parents=True)
        (base / "metrics.json").write_text(json.dumps(
            {"captured_with": "test", "viewport": "1440px",
             "pages": {self.URL: entry}}), encoding="utf-8")
        orig = common.evidence_dir
        common.evidence_dir = lambda: Path(tmp.name)

        def restore():
            common.evidence_dir = orig
            tmp.cleanup()
        return restore

    def test_threshold_matrix(self):
        cases = [
            ({"lcp_ms": 1800, "cls": 0.05, "tbt_ms": 150}, ("pass", "pass", "pass")),
            ({"lcp_ms": 3200, "cls": 0.2, "tbt_ms": 400}, ("warn", "warn", "warn")),
            ({"lcp_ms": 5200, "cls": 0.4, "tbt_ms": 900}, ("fail", "fail", "fail")),
        ]
        for entry, expected in cases:
            restore = self._with_metrics({**entry, "captured_at_utc": "2026-07-03T00:00:00Z"})
            try:
                r = vitals.scan(self.URL)
            finally:
                restore()
            got = (r["checks"]["lcp"]["verdict"], r["checks"]["cls"]["verdict"],
                   r["checks"]["tbt"]["verdict"])
            self.assertEqual(got, expected, entry)
            self.assertTrue(r["captured"])

    def test_contrast_violations_fail(self):
        restore = self._with_metrics({
            "lcp_ms": 1000, "cls": 0.0, "tbt_ms": 0,
            "contrast": {"checked": 50, "violations": [
                {"sample": "gray footer text", "ratio": 2.9, "required": 4.5}]}})
        try:
            r = vitals.scan(self.URL)
        finally:
            restore()
        c = r["checks"]["contrast"]
        self.assertEqual(c["verdict"], "fail")
        self.assertIn("2.9:1", c["note"])

    def test_clean_contrast_passes(self):
        restore = self._with_metrics({"contrast": {"checked": 80, "violations": []}})
        try:
            r = vitals.scan(self.URL)
        finally:
            restore()
        self.assertEqual(r["checks"]["contrast"]["verdict"], "pass")
        # Metrics missing from the entry are info, never guessed.
        self.assertEqual(r["checks"]["lcp"]["verdict"], "info")

    def test_no_capture_is_not_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            orig = common.evidence_dir
            common.evidence_dir = lambda: Path(tmp)
            try:
                r = vitals.scan(self.URL)
            finally:
                common.evidence_dir = orig
        self.assertFalse(r["captured"])
        self.assertEqual({c["verdict"] for c in r["checks"].values()}, {"info"})
        self.assertEqual(r["grade"]["band"], "Not measured")


class TestRenderedSnapshots(unittest.TestCase):
    def test_page_from_snapshot_builds_a_measured_context(self):
        net = {"ok": False, "error": None, "final_url": "https://acme.example/app",
               "final_status": 200, "final_headers": {"content-type": "text/html"},
               "hops": [], "content_type": "text/html", "content_encoding": "",
               "body": SPA_SHELL, "body_bytes": 10, "uncompressed_bytes": 10,
               "elapsed_ms": 1, "requested_url": "https://acme.example/app"}
        ctx = htmlmeta.page_from_snapshot("https://acme.example/app", GOOD_PAGE, net)
        self.assertEqual(ctx["res"]["body"], GOOD_PAGE)
        self.assertTrue(ctx["res"]["ok"])
        self.assertEqual(ctx["res"]["final_url"], "https://acme.example/app")
        self.assertFalse(ctx["render"]["likely_client_rendered"])
        self.assertEqual(ctx["render"]["source"], "rendered_dom_snapshot")

    def test_load_rendered_snapshots_reads_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "rendered" / "acme-example"
            base.mkdir(parents=True)
            (base / "home.html").write_text(GOOD_PAGE, encoding="utf-8")
            (base / "manifest.json").write_text(json.dumps({
                "captured_with": "test", "viewport": "1440px",
                "pages": {"https://acme.example/": {"file": "home.html",
                                                    "captured_at_utc": "2026-07-03T00:00:00Z"}},
            }), encoding="utf-8")
            orig = common.evidence_dir
            common.evidence_dir = lambda: Path(tmp)
            try:
                snaps = site.load_rendered_snapshots("acme-example")
                empty = site.load_rendered_snapshots("other-slug")
            finally:
                common.evidence_dir = orig
        self.assertEqual(snaps, {"https://acme.example/": GOOD_PAGE})
        self.assertEqual(empty, {})

    def test_spa_page_with_snapshot_gets_measured_verdicts(self):
        def spa_fetch(url, *args, **kwargs):
            res = dict(_canned_fetch(url))
            res["body"] = SPA_SHELL
            res["body_bytes"] = len(SPA_SHELL)
            res["uncompressed_bytes"] = len(SPA_SHELL)
            return res

        orig = (common.http_fetch, common.tls_info, common.doh_query,
                tls._probe_legacy, site.load_rendered_snapshots)
        common.http_fetch = spa_fetch
        common.tls_info = _canned_tls
        common.doh_query = _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        site.load_rendered_snapshots = lambda slug: {"https://acme.example/": GOOD_PAGE}
        try:
            result = site.run("https://acme.example/", [])
        finally:
            (common.http_fetch, common.tls_info, common.doh_query,
             tls._probe_legacy, site.load_rendered_snapshots) = orig

        page = result["page_scans"][0]
        self.assertTrue(page["rendered_snapshot_used"])
        self.assertEqual(page["seo"]["evidence_source"], "rendered_dom")
        # Structural verdicts are measured from the snapshot, not inconclusive.
        self.assertEqual(page["seo"]["checks"]["headings"]["verdict"], "pass")
        self.assertEqual(page["accessibility"]["evidence_source"], "rendered_dom")
        # Performance keeps the static context: transfer facts are not simulated.
        self.assertNotIn("evidence_source", page["performance"])

    def test_spa_page_without_snapshot_stays_inconclusive(self):
        def spa_fetch(url, *args, **kwargs):
            res = dict(_canned_fetch(url))
            res["body"] = SPA_SHELL
            return res

        orig = (common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy)
        common.http_fetch = spa_fetch
        common.tls_info = _canned_tls
        common.doh_query = _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        try:
            result = site.run("https://acme.example/", [])
        finally:
            common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy = orig
        page = result["page_scans"][0]
        self.assertNotIn("rendered_snapshot_used", page)
        self.assertEqual(page["seo"]["checks"]["headings"]["verdict"], "info")


class TestDkimSelectorFamilies(unittest.TestCase):
    def test_probe_list_includes_date_and_provider_families(self):
        for sel in ("20230601", "20161025", "s2048", "fm1", "protonmail", "zoho"):
            self.assertIn(sel, dns.DKIM_SELECTORS)

    def test_hit_on_date_selector_is_reported(self):
        orig = common.doh_query

        def doh(name, rtype, *a, **k):
            answers = (["v=DKIM1; k=rsa; p=MIIB"]
                       if name.startswith("20230601._domainkey.") else [])
            return {"ok": True, "error": None, "status": 0, "ad": False,
                    "answers": answers, "raw": []}

        common.doh_query = doh
        try:
            c = dns.check_dkim("acme.example")
        finally:
            common.doh_query = orig
        self.assertEqual(c["verdict"], "pass")
        self.assertEqual(c["selectors_found"], ["20230601"])

    def test_absence_note_keeps_the_honest_caveat(self):
        orig = common.doh_query
        common.doh_query = lambda *a, **k: {"ok": True, "error": None, "status": 0,
                                            "ad": False, "answers": [], "raw": []}
        try:
            c = dns.check_dkim("acme.example")
        finally:
            common.doh_query = orig
        self.assertEqual(c["verdict"], "info")
        self.assertIn("absence is not proof", c["note"])


class TestHttp2Alpn(unittest.TestCase):
    def _scan_with_alpn(self, alpn):
        orig = (common.tls_info, common.doh_query, tls._probe_legacy)
        canned = dict(_canned_tls("acme.example"))
        canned["alpn"] = alpn
        common.tls_info = lambda host, *a, **k: canned
        common.doh_query = _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        try:
            return tls.scan("https://acme.example/")
        finally:
            common.tls_info, common.doh_query, tls._probe_legacy = orig

    def test_h2_passes(self):
        c = self._scan_with_alpn("h2")["checks"]["http2"]
        self.assertEqual(c["verdict"], "pass")

    def test_http11_only_warns(self):
        c = self._scan_with_alpn("http/1.1")["checks"]["http2"]
        self.assertEqual(c["verdict"], "warn")
        self.assertIn("http/1.1", c["note"])

    def test_no_alpn_warns(self):
        c = self._scan_with_alpn(None)["checks"]["http2"]
        self.assertEqual(c["verdict"], "warn")
        self.assertIn("no ALPN", c["note"])


class TestEmailTransportPosture(unittest.TestCase):
    STS_POLICY = "version: STSv1\nmode: enforce\nmx: mail.acme.example\nmax_age: 86400"

    def _doh_stub(self, txt_map):
        def doh(name, rtype, *a, **k):
            return {"ok": True, "error": None, "status": 0, "ad": False,
                    "answers": txt_map.get(name, []), "raw": []}
        return doh

    def _fetch_stub(self, status=200, body=None):
        def fetch(url, *a, **k):
            return {"ok": status == 200, "error": None,
                    "hops": [{"url": url, "status": status, "headers": {}}],
                    "final_url": url, "final_status": status, "final_headers": {},
                    "body": body, "content_type": "text/plain", "content_encoding": "",
                    "body_bytes": 0, "uncompressed_bytes": 0, "elapsed_ms": 1,
                    "requested_url": url}
        return fetch

    def _run(self, check, txt_map, has_mx=True, status=200, body=None):
        orig = (common.doh_query, common.http_fetch)
        common.doh_query = self._doh_stub(txt_map)
        common.http_fetch = self._fetch_stub(status, body)
        try:
            return check("acme.example", has_mx)
        finally:
            common.doh_query, common.http_fetch = orig

    def test_mta_sts_enforced_passes(self):
        c = self._run(dns.check_mta_sts,
                      {"_mta-sts.acme.example": ["v=STSv1; id=20260702"]},
                      body=self.STS_POLICY)
        self.assertEqual(c["verdict"], "pass")
        self.assertEqual(c["mode"], "enforce")

    def test_mta_sts_testing_mode_is_info(self):
        c = self._run(dns.check_mta_sts,
                      {"_mta-sts.acme.example": ["v=STSv1; id=1"]},
                      body=self.STS_POLICY.replace("enforce", "testing"))
        self.assertEqual(c["verdict"], "info")
        self.assertEqual(c["mode"], "testing")

    def test_mta_sts_unreachable_policy_is_info(self):
        c = self._run(dns.check_mta_sts,
                      {"_mta-sts.acme.example": ["v=STSv1; id=1"]}, status=404)
        self.assertEqual(c["verdict"], "info")
        self.assertFalse(c["policy_reachable"])

    def test_mta_sts_absent_is_info(self):
        c = self._run(dns.check_mta_sts, {})
        self.assertEqual(c["verdict"], "info")
        self.assertFalse(c["present"])

    def test_no_mx_makes_transport_checks_not_applicable(self):
        for check in (dns.check_mta_sts, dns.check_tls_rpt, dns.check_bimi):
            c = self._run(check, {}, has_mx=False)
            self.assertEqual(c["verdict"], "info")
            self.assertIn("no MX", c["note"])

    def test_tls_rpt_and_bimi_present_pass(self):
        rpt = self._run(dns.check_tls_rpt,
                        {"_smtp._tls.acme.example": ["v=TLSRPTv1; rua=mailto:tls@acme.example"]})
        self.assertEqual(rpt["verdict"], "pass")
        bimi = self._run(dns.check_bimi,
                         {"default._bimi.acme.example": ["v=BIMI1; l=https://acme.example/logo.svg"]})
        self.assertEqual(bimi["verdict"], "pass")
        self.assertIn("logo", bimi["note"])


class TestRobotsDisallowAllAndFragments(unittest.TestCase):
    def test_global_disallow_detected(self):
        self.assertTrue(crawl._star_group_disallows_all(
            "User-agent: *\nDisallow: /"))

    def test_path_scoped_disallow_is_fine(self):
        self.assertFalse(crawl._star_group_disallows_all(
            "User-agent: *\nDisallow: /admin/\nDisallow: /tmp/"))

    def test_disallow_in_specific_group_ignored(self):
        self.assertFalse(crawl._star_group_disallows_all(
            "User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nDisallow: /private/"))

    def test_allow_root_reopens(self):
        self.assertFalse(crawl._star_group_disallows_all(
            "User-agent: *\nDisallow: /\nAllow: /"))

    def test_consecutive_agent_lines_share_a_group(self):
        self.assertTrue(crawl._star_group_disallows_all(
            "User-agent: Googlebot\nUser-agent: *\nDisallow: /"))

    def test_robots_check_fails_on_global_disallow(self):
        orig = common.http_fetch
        common.http_fetch = lambda url, *a, **k: {
            "ok": True, "error": None, "hops": [{"url": url, "status": 200, "headers": {}}],
            "final_url": url, "final_status": 200, "final_headers": {},
            "body": "User-agent: *\nDisallow: /", "content_type": "text/plain",
            "content_encoding": "", "body_bytes": 24, "uncompressed_bytes": 24,
            "elapsed_ms": 1, "requested_url": url}
        try:
            c = crawl.check_robots_txt("https://acme.example/")
        finally:
            common.http_fetch = orig
        self.assertEqual(c["verdict"], "fail")
        self.assertTrue(c["disallows_all"])

    def test_parser_collects_ids_and_legacy_names(self):
        parsed = htmlmeta.parse_html(
            '<div id="pricing"></div><a name="legacy"></a><span id="faq"></span>')
        self.assertEqual(parsed["ids"], ["faq", "legacy", "pricing"])

    def test_fragment_matrix(self):
        base = "https://acme.example/"
        anchors = [{"href": "#pricing"}, {"href": "#missing"}, {"href": "#"},
                   {"href": "#top"}, {"href": "/other"}]
        c = links._fragment_check(anchors, ["pricing"], base, False)
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["missing"], ["missing"])
        ok = links._fragment_check([{"href": "#pricing"}], ["pricing"], base, False)
        self.assertEqual(ok["verdict"], "pass")
        none = links._fragment_check([{"href": "/x"}, {"href": "#"}], [], base, False)
        self.assertEqual(none["verdict"], "info")
        spa = links._fragment_check([{"href": "#a"}], [], base, True)
        self.assertEqual(spa["verdict"], "info")

    def test_path_form_same_page_fragments_are_checked(self):
        # Found live: SPA navs write same-page anchors as /#fragment, which a
        # bare-#-only check missed entirely.
        base = "https://acme.example/"
        anchors = [{"href": "/#pricing"}, {"href": "/#missing-anchor"},
                   {"href": "https://acme.example/#also-missing"},
                   {"href": "/other#elsewhere"}]
        c = links._fragment_check(anchors, ["pricing"], base, False)
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["missing"], ["also-missing", "missing-anchor"])
        # Fragments on other pages cannot be verified and are not counted.
        self.assertEqual(c["count"], 3)
        # Found live: a slashless page url (http://host) must still match its
        # anchors resolved to http://host/#fragment.
        slashless = links._fragment_check([{"href": "/#missing-anchor"}], [],
                                          "http://localhost:8819", False)
        self.assertEqual(slashless["verdict"], "warn")


class TestPageSecurity(unittest.TestCase):
    def _ctx(self, html, final_url="https://acme.example/"):
        parsed = htmlmeta.parse_html(html)
        render = htmlmeta.render_assessment(parsed, html)
        return {"url": final_url, "parsed": parsed, "render": render,
                "res": {"ok": True, "body": html, "final_url": final_url,
                        "error": None}}

    BASE = ('<!doctype html><html lang="en"><head><title>Home page</title></head>'
            '<body><h1>Hi</h1><p>Some real body text for the page content here.</p>{}</body></html>')

    def test_sri_missing_on_cross_origin_script_warns(self):
        html = self.BASE.format('<script src="https://cdn.vendor.example/lib.js"></script>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        c = r["checks"]["subresource_integrity"]
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["without_integrity"], 1)

    def test_sri_present_passes(self):
        html = self.BASE.format(
            '<script src="https://cdn.vendor.example/lib.js" integrity="sha384-abc" '
            'crossorigin="anonymous"></script>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["subresource_integrity"]["verdict"], "pass")

    def test_sri_same_origin_only_is_info(self):
        html = self.BASE.format('<script src="/app.js"></script>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["subresource_integrity"]["verdict"], "info")

    def test_cross_origin_stylesheet_without_sri_counts(self):
        html = self.BASE.format(
            '<link rel="stylesheet" href="https://fonts.vendor.example/f.css">')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["subresource_integrity"]["verdict"], "warn")

    def test_http_form_action_on_https_page_fails(self):
        html = self.BASE.format('<form action="http://acme.example/login"><input name="u"></form>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        c = r["checks"]["insecure_form_action"]
        self.assertEqual(c["verdict"], "fail")
        self.assertIn("http://acme.example/login", c["insecure_actions"])

    def test_relative_form_action_passes(self):
        html = self.BASE.format('<form action="/login"><input name="u"></form>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["insecure_form_action"]["verdict"], "pass")

    def test_inline_handlers_reported_as_info(self):
        html = self.BASE.format('<button onclick="go()">Go</button><div onmouseover="x()">y</div>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        c = r["checks"]["inline_event_handlers"]
        self.assertEqual(c["verdict"], "info")
        self.assertEqual(c["count"], 2)

    def test_target_blank_without_rel_is_info(self):
        html = self.BASE.format('<a href="https://x.example" target="_blank">out</a>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        c = r["checks"]["target_blank_rel"]
        self.assertEqual(c["verdict"], "info")
        self.assertEqual(c["without_rel"], 1)

    def test_target_blank_with_noopener_passes(self):
        html = self.BASE.format(
            '<a href="https://x.example" target="_blank" rel="noopener">out</a>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["target_blank_rel"]["verdict"], "pass")

    def test_client_rendered_is_inconclusive(self):
        r = psec.scan("https://acme.example/", page=self._ctx(SPA_SHELL))
        self.assertEqual(r["checks"]["subresource_integrity"]["verdict"], "info")
        self.assertEqual(r["checks"]["insecure_form_action"]["verdict"], "info")
        self.assertEqual(r["category"], "security")

    def test_lazy_load_data_src_is_not_mixed_content(self):
        # <img data-src="http://..."> is not fetched by the browser, so it is
        # not mixed content; and a '>' inside a quoted attribute value must
        # not hide a real insecure src later in the same tag.
        clean = links._mixed_content(
            '<img data-src="http://cdn.acme.example/lazy.jpg" src="/real.jpg">', True)
        self.assertEqual(clean["verdict"], "pass")
        flagged = links._mixed_content(
            '<script data-cfg="a->b" src="http://cdn.acme.example/x.js"></script>', True)
        self.assertEqual(flagged["verdict"], "fail")
        self.assertEqual(flagged["items"][0]["url"], "http://cdn.acme.example/x.js")

    def test_data_action_does_not_shadow_the_real_insecure_action(self):
        # Stimulus/Turbo forms put data-action before action; a \b-anchored
        # regex matched data-action first and reported a false pass.
        html = self.BASE.format(
            '<form data-action="submit->checkout#go" action="http://acme.example/pay">'
            '<input name="card"></form>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        c = r["checks"]["insecure_form_action"]
        self.assertEqual(c["verdict"], "fail")
        self.assertIn("http://acme.example/pay", c["insecure_actions"])

    def test_consent_gated_data_src_script_is_not_a_live_resource(self):
        # Cookiebot/OneTrust gate trackers as <script type="text/plain"
        # data-src=...>; the browser loads nothing until consent, so SRI must
        # not count it as an active cross-origin script.
        html = self.BASE.format(
            '<script type="text/plain" data-src="https://www.googletagmanager.com/gtag/js"></script>')
        r = psec.scan("https://acme.example/", page=self._ctx(html))
        self.assertEqual(r["checks"]["subresource_integrity"]["verdict"], "info")


class TestDesign(unittest.TestCase):
    def _ctx(self, html, final_url="https://acme.example/"):
        parsed = htmlmeta.parse_html(html)
        render = htmlmeta.render_assessment(parsed, html)
        return {"url": final_url, "parsed": parsed, "render": render,
                "res": {"ok": True, "body": html, "final_url": final_url,
                        "error": None}}

    def _no_favicon_fetch(self, url, *a, **k):
        return {"ok": True, "error": None, "hops": [{"url": url, "status": 404, "headers": {}}],
                "final_url": url, "final_status": 404, "final_headers": {}, "body": None,
                "content_type": "", "content_encoding": "", "body_bytes": 0,
                "uncompressed_bytes": 0, "elapsed_ms": 1, "requested_url": url}

    BASE = ('<!doctype html><html lang="en"><head><title>Home page</title>{head}</head>'
            '<body><h1>Hi</h1><p>Some real body text for the page content here.</p>{body}'
            '</body></html>')

    def _scan(self, head="", body=""):
        html = self.BASE.format(head=head, body=body)
        orig = common.http_fetch
        common.http_fetch = self._no_favicon_fetch
        try:
            return design.scan("https://acme.example/", page=self._ctx(html))
        finally:
            common.http_fetch = orig

    def test_declared_favicon_passes(self):
        r = self._scan(head='<link rel="icon" href="/favicon.svg">')
        self.assertEqual(r["checks"]["favicon"]["verdict"], "pass")

    def test_missing_favicon_warns_when_default_absent(self):
        r = self._scan()
        self.assertEqual(r["checks"]["favicon"]["verdict"], "warn")

    def test_default_favicon_ico_counts(self):
        html = self.BASE.format(head="", body="")
        orig = common.http_fetch
        common.http_fetch = lambda url, *a, **k: {
            "ok": True, "error": None, "hops": [{"url": url, "status": 200, "headers": {}}],
            "final_url": url, "final_status": 200, "final_headers": {}, "body": None,
            "content_type": "image/x-icon", "content_encoding": "", "body_bytes": 0,
            "uncompressed_bytes": 0, "elapsed_ms": 1, "requested_url": url}
        try:
            r = design.scan("https://acme.example/", page=self._ctx(html))
        finally:
            common.http_fetch = orig
        self.assertEqual(r["checks"]["favicon"]["verdict"], "pass")

    def test_favicon_head_rejection_falls_back_to_get(self):
        html = self.BASE.format(head="", body="")
        seen = []

        def fetch(url, method="GET", *a, **k):
            seen.append(method)
            status = 405 if method == "HEAD" else 200
            return {"ok": True, "error": None,
                    "hops": [{"url": url, "status": status, "headers": {}}],
                    "final_url": url, "final_status": status, "final_headers": {},
                    "body": None, "content_type": "", "content_encoding": "",
                    "body_bytes": 0, "uncompressed_bytes": 0, "elapsed_ms": 1,
                    "requested_url": url}

        orig = common.http_fetch
        common.http_fetch = fetch
        try:
            r = design.scan("https://acme.example/", page=self._ctx(html))
        finally:
            common.http_fetch = orig
        self.assertEqual(r["checks"]["favicon"]["verdict"], "pass")
        self.assertEqual(seen, ["HEAD", "GET"])

    def test_theme_color(self):
        r = self._scan(head='<meta name="theme-color" content="#0b1f3a">')
        self.assertEqual(r["checks"]["theme_color"]["verdict"], "pass")
        self.assertEqual(r["checks"]["theme_color"]["value"], "#0b1f3a")
        r2 = self._scan()
        self.assertEqual(r2["checks"]["theme_color"]["verdict"], "info")

    def test_deprecated_tags_warn_with_counts(self):
        r = self._scan(body="<center><font size=3>old</font></center><marquee>hi</marquee>")
        c = r["checks"]["deprecated_presentational_tags"]
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["counts"]["font"], 1)
        self.assertEqual(c["counts"]["marquee"], 1)

    def test_inline_style_density(self):
        few = self._scan(body='<div style="color:red">x</div>')
        self.assertEqual(few["checks"]["inline_style_density"]["verdict"], "pass")
        many = self._scan(body='<i style="color:red">x</i>' * 31)
        c = many["checks"]["inline_style_density"]
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["count"], 31)

    def test_font_families_from_inline_and_linked_css(self):
        html = self.BASE.format(
            head='<link rel="stylesheet" href="/site.css">'
                 '<style>body { font-family: "Inter", sans-serif; }</style>',
            body="")
        orig = common.http_fetch
        common.http_fetch = lambda url, *a, **k: {
            "ok": True, "error": None, "hops": [{"url": url, "status": 200, "headers": {}}],
            "final_url": url, "final_status": 200, "final_headers": {},
            "body": "h1 { font-family: Georgia, serif; } p { font-family: Inter; }",
            "content_type": "text/css", "content_encoding": "", "body_bytes": 10,
            "uncompressed_bytes": 10, "elapsed_ms": 1, "requested_url": url}
        try:
            r = design.scan("https://acme.example/", page=self._ctx(html))
        finally:
            common.http_fetch = orig
        c = r["checks"]["font_families"]
        self.assertEqual(c["verdict"], "pass")
        self.assertEqual(sorted(c["families"]), ["georgia", "inter"])

    def test_too_many_font_families_warn(self):
        css = "".join(f".c{i} {{ font-family: Font{i}; }}" for i in range(6))
        r = self._scan(head=f"<style>{css}</style>")
        self.assertEqual(r["checks"]["font_families"]["verdict"], "warn")

    def test_image_dimensions(self):
        good = self._scan(body='<img src="/a.png" width="10" height="10">')
        self.assertEqual(good["checks"]["image_dimensions"]["verdict"], "pass")
        bad = self._scan(body='<img src="/a.png"><img src="/b.png"><img src="/c.png" width="1" height="1">')
        c = bad["checks"]["image_dimensions"]
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["missing_dimensions"], 2)

    def test_data_width_does_not_count_as_a_declared_dimension(self):
        # Lazy-load libraries ship <img data-src data-width data-height>; the
        # real width/height attributes are still absent, so layout shifts.
        bad = self._scan(body='<img src="/a.png" data-width="10" data-height="10">'
                              '<img src="/b.png" data-width="20" data-height="20">')
        c = bad["checks"]["image_dimensions"]
        self.assertEqual(c["verdict"], "warn")
        self.assertEqual(c["missing_dimensions"], 2)

    def test_client_rendered_marks_body_checks_info_but_head_still_counts(self):
        orig = common.http_fetch
        common.http_fetch = self._no_favicon_fetch
        try:
            r = design.scan("https://acme.example/", page=self._ctx(SPA_SHELL))
        finally:
            common.http_fetch = orig
        self.assertEqual(r["checks"]["deprecated_presentational_tags"]["verdict"], "info")
        self.assertEqual(r["checks"]["inline_style_density"]["verdict"], "info")
        self.assertEqual(r["checks"]["image_dimensions"]["verdict"], "info")
        self.assertEqual(r["category"], "design")


class TestSecurityTxtAndCaa(unittest.TestCase):
    def test_security_txt_published(self):
        orig = common.http_fetch
        common.http_fetch = lambda url, *a, **k: {
            "ok": True, "error": None, "hops": [{"url": url, "status": 200, "headers": {}}],
            "final_url": url, "final_status": 200, "final_headers": {},
            "content_type": "text/plain", "content_encoding": "",
            "body": "Contact: mailto:security@acme.example\nExpires: 2027-01-01T00:00:00Z",
            "body_bytes": 60, "uncompressed_bytes": 60, "elapsed_ms": 1}
        try:
            c = sec.check_security_txt("https://acme.example/")
        finally:
            common.http_fetch = orig
        self.assertEqual(c["verdict"], "pass")
        self.assertTrue(c["present"])

    def test_security_txt_absent_is_info(self):
        orig = common.http_fetch
        common.http_fetch = lambda url, *a, **k: {
            "ok": True, "error": None, "hops": [{"url": url, "status": 404, "headers": {}}],
            "final_url": url, "final_status": 404, "final_headers": {},
            "content_type": "text/html", "content_encoding": "", "body": "not found",
            "body_bytes": 9, "uncompressed_bytes": 9, "elapsed_ms": 1}
        try:
            c = sec.check_security_txt("https://acme.example/")
        finally:
            common.http_fetch = orig
        self.assertEqual(c["verdict"], "info")
        self.assertFalse(c["present"])

    def test_spa_catchall_200_without_contact_is_not_published(self):
        orig = common.http_fetch
        common.http_fetch = lambda url, *a, **k: {
            "ok": True, "error": None, "hops": [{"url": url, "status": 200, "headers": {}}],
            "final_url": url, "final_status": 200, "final_headers": {},
            "content_type": "text/html", "content_encoding": "",
            "body": "<html><body>app shell</body></html>",
            "body_bytes": 30, "uncompressed_bytes": 30, "elapsed_ms": 1}
        try:
            c = sec.check_security_txt("https://acme.example/")
        finally:
            common.http_fetch = orig
        self.assertEqual(c["verdict"], "info")
        self.assertFalse(c["present"])

    def test_caa_present_passes(self):
        orig = common.doh_query
        common.doh_query = lambda name, rtype, *a, **k: {
            "ok": True, "error": None, "status": 0, "ad": False,
            "answers": ['0 issue "letsencrypt.org"'], "raw": []}
        try:
            c = tls.check_caa("acme.example")
        finally:
            common.doh_query = orig
        self.assertEqual(c["verdict"], "pass")
        self.assertIn('0 issue "letsencrypt.org"', c["records"])

    def test_caa_absent_is_info(self):
        orig = common.doh_query
        common.doh_query = lambda name, rtype, *a, **k: {
            "ok": True, "error": None, "status": 0, "ad": False, "answers": [], "raw": []}
        try:
            c = tls.check_caa("acme.example")
        finally:
            common.doh_query = orig
        self.assertEqual(c["verdict"], "info")

    def test_caa_lookup_failure_is_info(self):
        orig = common.doh_query
        common.doh_query = lambda name, rtype, *a, **k: {
            "ok": False, "error": "stubbed offline", "status": None,
            "ad": False, "answers": [], "raw": []}
        try:
            c = tls.check_caa("acme.example")
        finally:
            common.doh_query = orig
        self.assertEqual(c["verdict"], "info")


class TestDraftReportData(unittest.TestCase):
    SCAN = {
        "host": "example.com", "slug": "example-com", "target": "https://example.com",
        "measured_at_utc": "2026-07-01T12:00:00Z",
        "pages_scanned": ["https://example.com"],
        "totals": {"fail": 2, "warn": 1},
        "scorecard": {"overall": {"band": "Weak"},
                      "categories": {
                          "security": {"band": "Poor", "pass": 0, "warn": 1, "fail": 6, "score": 0.07},
                          "seo": {"band": "Adequate", "pass": 4, "warn": 3, "fail": 0, "score": 0.79}}},
        "issues": {
            "fail": [{"scan": "http_security", "check": "hsts", "verdict": "fail", "note": "No HSTS."},
                     {"scan": "a11y:https://example.com", "check": "image_alt",
                      "verdict": "fail", "note": "Images missing alt."}],
            "warn": [{"scan": "seo:https://example.com", "check": "title",
                      "verdict": "warn", "note": "Title short."}]},
    }

    def test_top_level_fields(self):
        d = drpt.draft(self.SCAN)
        self.assertEqual(d["site"], "example.com")
        self.assertEqual(d["target_url"], "https://example.com")
        self.assertEqual(d["date"], "2026-07-01")
        self.assertEqual(d["recommendations"], [])
        self.assertEqual(d["quick_wins"], [])
        self.assertTrue(d["bottom_line"].startswith("DRAFT"))

    def test_scorecard_overall_is_a_band_string(self):
        d = drpt.draft(self.SCAN)
        self.assertEqual(d["scorecard"]["overall"], "Weak")
        self.assertEqual({r["category"] for r in d["scorecard"]["rows"]}, {"security", "seo"})

    def test_scorecard_rows_carry_the_numeric_score(self):
        # The builder draws its score bar from this number (PLAN.md section
        # 35); it must be the measured score, copied, never re-derived.
        rows = {r["category"]: r for r in drpt.draft(self.SCAN)["scorecard"]["rows"]}
        self.assertEqual(rows["security"]["score"], 0.07)
        self.assertEqual(rows["seo"]["score"], 0.79)

    def test_findings_map_severity_ordering_and_evidence(self):
        d = drpt.draft(self.SCAN)
        self.assertEqual([f["severity"] for f in d["findings"]], ["High", "High", "Medium"])
        a11y = next(f for f in d["findings"] if f["area"] == "a11y")
        self.assertEqual(a11y["evidence"], "https://example.com")
        host = next(f for f in d["findings"] if f["area"] == "http_security")
        self.assertIn("example-com_scan.json", host["evidence"])

    def test_schema_has_every_builder_key(self):
        d = drpt.draft(self.SCAN)
        for key in ("site", "target_url", "date", "bottom_line", "scorecard",
                    "findings", "recommendations", "quick_wins", "scope", "progress"):
            self.assertIn(key, d)

    def test_scope_and_progress_are_filled_from_measured_data(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["pages_scanned"] = ["https://x/", "https://x/a"]
        scan["page_scans"] = [{"url": "https://x/", "rendered_snapshot_used": True}]
        scan["delta"] = {"previous_measured_at": "2026-07-01T09:00:00Z",
                         "new": [{"scan": "s", "check": "c", "verdict": "warn", "note": "n"}],
                         "resolved": []}
        d = drpt.draft(scan)
        self.assertEqual(d["scope"]["pages_reviewed"], 2)
        self.assertIn("rendered-DOM capture", d["scope"]["method"])
        self.assertEqual(d["progress"], {"previous_date": "2026-07-01",
                                         "new_issues": 1, "resolved_issues": 0})

    def test_progress_is_none_on_a_first_run(self):
        d = drpt.draft(self.SCAN)
        self.assertIsNone(d["progress"])
        self.assertEqual(d["scope"]["method"], "Passive external scan")

    def test_web_vitals_prefers_field_over_lab(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["host_scans"] = {"crux": {"checks": {
            "field_lcp": {"verdict": "pass", "value": 875},
            "field_cls": {"verdict": "fail", "value": 0.31},
            "field_inp": {"verdict": "warn", "value": 350}}}}
        scan["page_scans"] = [{"url": "https://x/", "vitals": {"checks": {
            "lcp": {"verdict": "pass", "value": 1200}}}}]
        wv = drpt.draft(scan)["web_vitals"]
        self.assertEqual(wv["source"], "field")
        labels = {m["label"]: (m["value"], m["rating"]) for m in wv["metrics"]}
        self.assertEqual(labels["LCP"], ("0.9s", "Good"))
        self.assertEqual(labels["CLS"], ("0.31", "Poor"))
        self.assertEqual(labels["INP"], ("350ms", "Needs work"))

    def test_web_vitals_falls_back_to_lab_capture(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["page_scans"] = [{"url": "https://x/", "vitals": {"checks": {
            "lcp": {"verdict": "pass", "value": 1800},
            "cls": {"verdict": "pass", "value": 0.02},
            "tbt": {"verdict": "warn", "value": 300},
            "contrast": {"verdict": "info"}}}}]
        wv = drpt.draft(scan)["web_vitals"]
        self.assertEqual(wv["source"], "lab")
        self.assertEqual([m["label"] for m in wv["metrics"]], ["LCP", "CLS", "TBT"])

    def test_web_vitals_none_when_nothing_measured(self):
        d = drpt.draft(self.SCAN)
        self.assertIsNone(d["web_vitals"])

    def test_assessment_reads_weaknesses_with_worst_finding_named(self):
        # Fixture: security is Poor (weakness); the http_security -> security
        # label mapping must land the worst-finding note on it.
        d = drpt.draft(self.SCAN)
        w = d["assessment"]["weaknesses"]
        sec = next(x for x in w if x.startswith("Security posture"))
        self.assertIn("poor", sec)
        self.assertIn("No HSTS.", sec)

    def test_assessment_lists_strong_categories(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["scorecard"]["categories"]["seo"]["band"] = "Strong"
        d = drpt.draft(scan)
        self.assertTrue(any(s.startswith("SEO and on-page: strong")
                            for s in d["assessment"]["strengths"]))

    def test_strengths_are_ordered_by_score_so_strongest_is_true(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["scorecard"]["categories"] = {
            "security": {"band": "Strong", "pass": 20, "warn": 0, "fail": 0, "score": 0.97},
            "tls": {"band": "Strong", "pass": 4, "warn": 0, "fail": 0, "score": 1.0},
        }
        d = drpt.draft(scan)
        # TLS (1.0) must lead security (0.97), and the bottom line names it.
        self.assertTrue(d["assessment"]["strengths"][0].startswith("TLS and certificates"))
        self.assertIn("strongest area is tls and certificates", d["bottom_line"])

    def test_action_plan_orders_by_measured_breadth_within_a_verdict(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["issues_grouped"] = {
            "fail": [],
            "warn": [
                {"scan": "seo", "check": "title", "verdict": "warn",
                 "note": "Title short.", "pages": ["https://x/a"]},
                {"scan": "privacy", "check": "known_trackers", "verdict": "warn",
                 "note": "Trackers.", "pages": [f"https://x/{i}" for i in range(12)]},
                {"scan": "http_security", "check": "content_security_policy",
                 "verdict": "warn", "note": "No CSP.", "pages": []},
            ],
        }
        plan = drpt.draft(scan)["action_plan"]
        # Site-wide (host) first, then 12 pages, then 1 page.
        self.assertEqual([a["affects"] for a in plan[:3]],
                         ["site-wide", "12 page(s)", "https://x/a"])

    def test_action_plan_maps_checks_to_imperatives_fail_first(self):
        d = drpt.draft(self.SCAN)
        plan = d["action_plan"]
        self.assertEqual(plan[0]["priority"], "High")
        self.assertEqual(plan[0]["action"], drpt.ACTION["hsts"])
        self.assertTrue(any(a["priority"] == "Medium" and a["action"] == drpt.ACTION["title"]
                            for a in plan))
        self.assertEqual(plan[0]["affects"], "site-wide")  # host issue

    def test_finding_evidence_enumerates_every_affected_page(self):
        scan = json.loads(json.dumps(self.SCAN))
        pages = [f"https://x/p{i}" for i in range(12)]
        scan["issues_grouped"] = {"fail": [
            {"scan": "a11y", "check": "landmarks", "verdict": "fail",
             "note": "Missing landmarks.", "pages": pages}], "warn": []}
        f = drpt.draft(scan)["findings"][0]
        for url in pages:  # no page hidden behind a "+N more"
            self.assertIn(url, f["evidence"])
        self.assertNotIn("more", f["evidence"])

    def test_finding_evidence_ceiling_points_at_the_full_list(self):
        scan = json.loads(json.dumps(self.SCAN))
        pages = [f"https://x/p{i}" for i in range(50)]
        scan["issues_grouped"] = {"fail": [
            {"scan": "a11y", "check": "landmarks", "verdict": "fail",
             "note": "Missing landmarks.", "pages": pages}], "warn": []}
        f = drpt.draft(scan)["findings"][0]
        self.assertIn("https://x/p39", f["evidence"])
        self.assertIn("and 10 more listed in example-com_scan_summary.md", f["evidence"])

    def test_plan_affects_names_urls_for_small_page_sets(self):
        scan = json.loads(json.dumps(self.SCAN))
        scan["issues_grouped"] = {"fail": [
            {"scan": "perf", "check": "static_weight", "verdict": "fail",
             "note": "Heavy.", "pages": ["https://x/about/"]}], "warn": []}
        plan = drpt.draft(scan)["action_plan"]
        self.assertEqual(plan[0]["affects"], "https://x/about/")

    def test_bottom_line_names_band_and_top_priority(self):
        d = drpt.draft(self.SCAN)
        self.assertIn("Weak", d["bottom_line"])
        self.assertIn("top priority", d["bottom_line"])

    def test_findings_are_capped(self):
        big = {**self.SCAN, "issues": {"fail": [{"scan": "x", "check": "c", "verdict": "fail",
               "note": "n"}] * 40, "warn": []}}
        self.assertEqual(len(drpt.draft(big)["findings"]), drpt.MAX_FINDINGS)


class TestDraftTrend(unittest.TestCase):
    SCAN = {
        "slug": "acme-example", "host": "acme.example",
        "target": "https://acme.example/",
        "measured_at_utc": "2026-07-03T10:00:00Z",
        "pages_scanned": ["https://acme.example/"],
        "totals": {"fail": 0, "warn": 0},
        "scorecard": {"overall": {"band": "Strong", "score": 0.9, "pass": 1,
                                  "warn": 0, "fail": 0},
                      "categories": {}},
        "issues": {"fail": [], "warn": []},
        "issues_grouped": {"fail": [], "warn": []},
        "page_scans": [],
    }

    def test_draft_embeds_trend_in_progress(self):
        trend = {"quarters": ["2026-Q2", "2026-Q3"], "series": {},
                 "latest_delta": {"new_findings": 0, "resolved_findings": 0}}
        data = drpt.draft(json.loads(json.dumps(self.SCAN)), trend=trend)
        self.assertEqual(data["slug"], "acme-example")
        self.assertEqual(data["progress"]["trend"]["quarters"],
                         ["2026-Q2", "2026-Q3"])

    def test_draft_without_trend_keeps_progress_shape(self):
        data = drpt.draft(json.loads(json.dumps(self.SCAN)))
        self.assertEqual(data["slug"], "acme-example")
        self.assertIsNone(data["progress"])

    def test_draft_with_delta_and_trend_keeps_both(self):
        """K5: a scan carrying both a run-over-run delta and a quarterly
        trend must surface both in progress, not let one crowd out the
        other."""
        scan = json.loads(json.dumps(self.SCAN))
        scan["delta"] = {"previous_measured_at": "2026-04-01T09:00:00Z",
                         "new": [{"check": "x"}],
                         "resolved": [{"check": "y"}, {"check": "z"}]}
        trend = {"quarters": ["2026-Q2", "2026-Q3"], "series": {},
                 "latest_delta": {"new_findings": 1, "resolved_findings": 2}}
        data = drpt.draft(scan, trend=trend)
        progress = data["progress"]
        self.assertEqual(progress["previous_date"], "2026-04-01")
        self.assertEqual(progress["new_issues"], 1)
        self.assertEqual(progress["resolved_issues"], 2)
        self.assertEqual(progress["trend"]["quarters"], ["2026-Q2", "2026-Q3"])


class TestTitleExtraction(unittest.TestCase):
    def test_title_is_rcdata_with_charrefs_converted(self):
        # Per HTML5, <title> is RCDATA: markup inside is literal text and
        # character references are converted, matching what browsers show.
        out = htmlmeta.parse_html("<html><head><title>Acme &amp; Co</title></head></html>")
        self.assertEqual(out["title"], "Acme & Co")

    def test_unclosed_title_does_not_swallow_the_page(self):
        out = htmlmeta.parse_html("<html><head><title>Acme<meta name='x'></head>"
                                  "<body><p>Body text should not become the title.</p></body></html>")
        self.assertEqual(out["title"], "Acme")

    def test_first_title_wins(self):
        out = htmlmeta.parse_html("<title>First</title><title>Second</title>")
        self.assertEqual(out["title"], "First")


class TestViewportZoom(unittest.TestCase):
    def _check(self, viewport):
        return a11y._viewport_check({"meta_viewport": viewport})

    def test_generous_maximum_scale_is_not_flagged(self):
        # maximum-scale=10 contains the substring "maximum-scale=1"; the old
        # substring test warned on it even though 10x zoom is allowed.
        self.assertEqual(self._check("width=device-width, maximum-scale=10")["verdict"], "pass")
        self.assertEqual(self._check("width=device-width, maximum-scale=5.0")["verdict"], "pass")

    def test_restrictive_zoom_warns(self):
        self.assertEqual(self._check("maximum-scale=1")["verdict"], "warn")
        self.assertEqual(self._check("maximum-scale=1.5")["verdict"], "warn")
        self.assertEqual(self._check("user-scalable=no")["verdict"], "warn")
        self.assertEqual(self._check("user-scalable=0")["verdict"], "warn")

    def test_plain_viewport_passes(self):
        self.assertEqual(self._check("width=device-width, initial-scale=1")["verdict"], "pass")


class TestReferrerPolicy(unittest.TestCase):
    def test_matrix(self):
        self.assertEqual(sec.check_referrer_policy({})["verdict"], "fail")
        self.assertEqual(sec.check_referrer_policy(
            {"referrer-policy": "strict-origin-when-cross-origin"})["verdict"], "pass")
        self.assertEqual(sec.check_referrer_policy(
            {"referrer-policy": "unsafe-url"})["verdict"], "warn")


class TestTrackerListDepth(unittest.TestCase):
    def test_list_covers_the_major_families_with_a_count_floor(self):
        # An accidental truncation of the embedded list must fail loudly.
        self.assertGreaterEqual(len(privacy.KNOWN_TRACKERS), 140)
        for domain, category in (
                ("criteo.net", "advertising"), ("adnxs.com", "advertising"),
                ("omtrdc.net", "analytics"), ("taboola.com", "advertising"),
                ("rlcdn.com", "advertising"), ("logrocket.com", "session-replay"),
                ("hs-analytics.net", "marketing"), ("appsflyer.com", "attribution"),
                ("optimizely.com", "ab-testing")):
            self.assertEqual(privacy.KNOWN_TRACKERS.get(domain), category, domain)

    def test_new_entries_match_by_subdomain_not_lookalike(self):
        found = privacy._match_trackers([
            "https://static.criteo.net/js/ld/ld.js",
            "https://secure.adnxs.com/px",
            "https://notcriteo.net/x.js",
        ])
        self.assertIn("criteo.net", found)
        self.assertIn("adnxs.com", found)
        self.assertEqual(len(found), 2)

    def test_expanded_cmp_and_marker_detection(self):
        self.assertTrue(privacy._consent_detected(
            '<script src="https://sdk.privacy-center.org/loader.js"></script>'))
        self.assertTrue(privacy._consent_detected('<div id="didomi-host">'))
        self.assertTrue(privacy._consent_detected('<div class="cmplz-cookiebanner">'))
        self.assertFalse(privacy._consent_detected('<div>plain page</div>'))


class TestPrivacyHostMatching(unittest.TestCase):
    def test_suffix_not_substring(self):
        self.assertTrue(privacy._host_matches("www.facebook.com", "facebook.com"))
        self.assertTrue(privacy._host_matches("facebook.com", "facebook.com"))
        self.assertFalse(privacy._host_matches("notfacebook.com", "facebook.com"))
        self.assertFalse(privacy._host_matches("facebook.com.evil.example", "facebook.com"))

    def test_match_trackers_ignores_lookalike_hosts(self):
        self.assertEqual(privacy._match_trackers(["https://notfacebook.com/x.js"]), {})
        found = privacy._match_trackers(["https://www.google-analytics.com/ga.js"])
        self.assertEqual(found.get("google-analytics.com"), "analytics")


class TestCrawl(unittest.TestCase):
    """scan_crawl owns robots/sitemap; scan_seo no longer refetches them per page."""

    def setUp(self):
        self._orig = common.http_fetch

    def tearDown(self):
        common.http_fetch = self._orig

    @staticmethod
    def _fetch_returning(status, body):
        def fetch(url, *a, **k):
            return {"ok": status is not None, "error": None if status else "stubbed down",
                    "requested_url": url, "hops": [{"url": url, "status": status, "headers": {}}]
                    if status else [],
                    "final_url": url, "final_status": status, "final_headers": {},
                    "content_type": "text/plain", "content_encoding": "", "body": body,
                    "body_bytes": len(body or ""), "uncompressed_bytes": len(body or ""),
                    "elapsed_ms": 1}
        return fetch

    def test_robots_present_passes_and_reports_sitemaps(self):
        common.http_fetch = self._fetch_returning(
            200, "User-agent: *\nDisallow:\nSitemap: https://x.example/sm.xml\n")
        c = crawl.check_robots_txt("https://x.example/")
        self.assertEqual(c["verdict"], "pass")
        self.assertEqual(c["sitemaps"], ["https://x.example/sm.xml"])

    def test_robots_missing_warns_and_fetch_failure_is_info(self):
        common.http_fetch = self._fetch_returning(404, "not found")
        self.assertEqual(crawl.check_robots_txt("https://x.example/")["verdict"], "warn")
        common.http_fetch = self._fetch_returning(None, None)
        self.assertEqual(crawl.check_robots_txt("https://x.example/")["verdict"], "info")

    def test_sitemap_verdicts(self):
        common.http_fetch = self._fetch_returning(200, '<?xml version="1.0"?><urlset></urlset>')
        self.assertEqual(crawl.check_sitemap("https://x.example/", [])["verdict"], "pass")
        common.http_fetch = self._fetch_returning(200, "<html>soft 404</html>")
        self.assertEqual(crawl.check_sitemap("https://x.example/", [])["verdict"], "warn")
        common.http_fetch = self._fetch_returning(None, None)
        self.assertEqual(crawl.check_sitemap("https://x.example/", [])["verdict"], "info")

    def test_seo_scan_no_longer_carries_host_checks(self):
        parsed = htmlmeta.parse_html(GOOD_PAGE)
        render = htmlmeta.render_assessment(parsed, GOOD_PAGE)
        ctx = {"url": "https://acme.example/", "parsed": parsed, "render": render,
               "res": {"ok": True, "body": GOOD_PAGE, "final_url": "https://acme.example/",
                       "error": None}}
        r = seo.scan("https://acme.example/", page=ctx)
        self.assertNotIn("robots_txt", r["checks"])
        self.assertNotIn("sitemap", r["checks"])

    def test_scorecard_merges_crawl_into_seo_category(self):
        host = {"crawl": {"checks": {"robots_txt": {"verdict": "warn"},
                                     "sitemap": {"verdict": "warn"}}}}
        pages = [{"seo": {"ok": True, "checks": {"title": {"verdict": "pass"},
                                                 "headings": {"verdict": "pass"}}}}]
        sc = site.build_scorecard(host, pages)
        g = sc["categories"]["seo"]
        # 2 pass + 2 warn merged into one bucket -> score 0.75, no key overwrite.
        self.assertEqual((g["pass"], g["warn"], g["fail"]), (2, 2, 0))
        self.assertEqual(g["score"], 0.75)


class TestRunReview(unittest.TestCase):
    def test_choose_pages_excludes_target_and_homepage(self):
        disco_result = {"homepage": "https://x.example/",
                        "proposed_review_set": ["https://x.example/", "https://x.example/a",
                                                "https://x.example/b"]}
        out = run_review.choose_pages("https://x.example/", disco_result)
        self.assertEqual(out, ["https://x.example/a", "https://x.example/b"])

    def test_choose_pages_on_failed_discovery(self):
        self.assertEqual(run_review.choose_pages("https://x.example/", {"ok": False}), [])

    def test_pipeline_offline_writes_all_artifacts(self):
        orig = (common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy)
        common.http_fetch, common.tls_info, common.doh_query = _canned_fetch, _canned_tls, _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        try:
            with tempfile.TemporaryDirectory() as td:
                out = run_review.pipeline("https://acme.example/", out_dir=td,
                                          capture=False)
                for key in ("json_path", "digest_path", "draft_path"):
                    self.assertTrue(Path(out[key]).exists(), f"{key} not written")
                draft = json.loads(Path(out["draft_path"]).read_text(encoding="utf-8"))
                for key in ("site", "scorecard", "findings", "recommendations"):
                    self.assertIn(key, draft)
                self.assertGreaterEqual(len(out["scan"]["pages_scanned"]), 1)
        finally:
            common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy = orig

    def test_pipeline_reports_missing_browser_honestly(self):
        orig = (common.http_fetch, common.tls_info, common.doh_query,
                tls._probe_legacy, caprend.find_browser)
        common.http_fetch, common.tls_info, common.doh_query = _canned_fetch, _canned_tls, _canned_doh
        tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
        caprend.find_browser = lambda: None
        try:
            with tempfile.TemporaryDirectory() as td:
                out = run_review.pipeline("https://acme.example/", out_dir=td)
                # The rest of the pipeline still delivered its artifacts.
                self.assertTrue(Path(out["json_path"]).exists())
        finally:
            (common.http_fetch, common.tls_info, common.doh_query,
             tls._probe_legacy, caprend.find_browser) = orig
        self.assertFalse(out["capture"]["ok"])
        self.assertIn("no Chrome or Edge found", out["capture"]["note"])

    def test_pipeline_capture_and_rescan_consumes_snapshot(self):
        def spa_fetch(url, *args, **kwargs):
            res = dict(_canned_fetch(url))
            res["body"] = SPA_SHELL
            res["body_bytes"] = len(SPA_SHELL)
            res["uncompressed_bytes"] = len(SPA_SHELL)
            return res

        target = "https://acme.example/"

        def fake_capture(slug, plan, **kwargs):
            base = common.evidence_dir() / "rendered" / slug
            base.mkdir(parents=True, exist_ok=True)
            (base / "home.html").write_text(GOOD_PAGE, encoding="utf-8")
            common.write_json(base / "manifest.json", {
                "captured_with": "stub", "viewport": "1440px",
                "pages": {target: {"file": "home.html",
                                   "captured_at_utc": "2026-01-01T00:00:00Z"}}})
            return {"ok": True, "captured": [target], "failed": {}, "dropped": []}

        orig = (common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy,
                caprend.find_browser, caprend.capture_pages, common.evidence_dir)
        with tempfile.TemporaryDirectory() as td:
            common.http_fetch, common.tls_info, common.doh_query = spa_fetch, _canned_tls, _canned_doh
            tls._probe_legacy = lambda host, *a, **k: {"tested": False, "note": "stubbed"}
            caprend.find_browser = lambda: "C:/fake/chrome.exe"
            caprend.capture_pages = fake_capture
            common.evidence_dir = lambda: Path(td)
            try:
                out = run_review.pipeline(target)
            finally:
                (common.http_fetch, common.tls_info, common.doh_query, tls._probe_legacy,
                 caprend.find_browser, caprend.capture_pages, common.evidence_dir) = orig

        self.assertTrue(out["capture"]["rescanned"])
        page = out["scan"]["page_scans"][0]
        self.assertTrue(page["likely_client_rendered"])
        self.assertTrue(page["rendered_snapshot_used"])
        self.assertEqual(page["seo"]["evidence_source"], "rendered_dom")


class TestCaptureRendered(unittest.TestCase):
    """The automated capture tool (PLAN.md section 34). Offline: no browser
    is ever launched; the WebSocket layer is driven with crafted bytes and
    the capture run with a fake CDP session."""

    def test_ws_accept_key_matches_the_rfc_6455_vector(self):
        self.assertEqual(caprend.ws_accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
                         "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    @staticmethod
    def _reader(data):
        bio = io.BytesIO(data)

        def read_exact(n):
            chunk = bio.read(n)
            if len(chunk) != n:
                raise AssertionError("short read in test fixture")
            return chunk
        return read_exact

    def test_client_frame_roundtrip_across_length_encodings(self):
        for size in (0, 1, 125, 126, 65535, 65536):
            payload = b"a" * size
            frame = caprend.ws_encode_frame(0x1, payload)
            fin, opcode, decoded = caprend.ws_read_frame(self._reader(frame))
            self.assertTrue(fin)
            self.assertEqual(opcode, 0x1)
            self.assertEqual(decoded, payload, f"size {size}")

    def test_oversized_frame_is_rejected(self):
        header = b"\x81\xff" + struct.pack(">Q", caprend.MAX_WS_MESSAGE + 1)
        with self.assertRaises(caprend.CaptureError):
            caprend.ws_read_frame(self._reader(header))

    def test_read_message_assembles_fragments_and_answers_ping(self):
        class FakeSocket:
            def __init__(self, data):
                self.data, self.pos, self.sent = data, 0, b""

            def recv(self, n):
                chunk = self.data[self.pos:self.pos + n]
                self.pos += len(chunk)
                return chunk

            def sendall(self, b):
                self.sent += b

            def settimeout(self, t):
                pass

        # server frames are unmasked: a ping, then "hello" in two fragments
        stream = b"\x89\x02hi" + b"\x01\x03hel" + b"\x80\x02lo"
        sock = FakeSocket(stream)
        conn = caprend.WsConn(sock)
        self.assertEqual(conn.read_message(timeout=5), "hello")
        fin, opcode, payload = caprend.ws_read_frame(self._reader(sock.sent))
        self.assertTrue(fin)
        self.assertEqual(opcode, 0xA)  # the ping was answered with a pong
        self.assertEqual(payload, b"hi")

    def test_snapshot_filenames_are_safe_and_unique(self):
        taken = set()
        self.assertEqual(caprend.snapshot_filename("https://x.example/", taken),
                         "home.html")
        self.assertEqual(caprend.snapshot_filename("https://x.example/products/a b", taken),
                         "products-a-b.html")
        self.assertEqual(caprend.snapshot_filename("https://x.example/products/a_b", taken),
                         "products-a_b.html")
        self.assertEqual(caprend.snapshot_filename("https://x.example/products/a%20b", taken),
                         "products-a-20b.html")
        # A colliding path gets a numeric suffix instead of overwriting.
        self.assertEqual(caprend.snapshot_filename("https://x.example/products/a b/", taken),
                         "products-a-b-2.html")

    def test_plan_prioritizes_dom_pages_and_names_dropped(self):
        pages = ["https://x.example/"] + [f"https://x.example/p{i}" for i in range(1, 21)]
        scan = {"pages_scanned": pages,
                "page_scans": [
                    {"url": "https://x.example/p18", "likely_client_rendered": True},
                    {"url": "https://x.example/p19", "likely_client_rendered": True,
                     "rendered_snapshot_used": True}]}
        plan = caprend.plan_from_scan(scan, cap=5)
        self.assertEqual(plan["pages"][0], "https://x.example/")
        # DOM pages jump the queue; an existing snapshot is refreshed, not kept stale.
        self.assertEqual(plan["pages"][1:3],
                         ["https://x.example/p18", "https://x.example/p19"])
        self.assertEqual(plan["dom_pages"],
                         ["https://x.example/p18", "https://x.example/p19"])
        self.assertEqual(len(plan["pages"]), 5)
        # 21 candidates, 5 captured, every dropped page is named.
        self.assertEqual(len(plan["dropped"]), 16)
        self.assertNotIn("https://x.example/p18", plan["dropped"])

    def test_plan_dom_pages_survive_the_cap(self):
        pages = [f"https://x.example/p{i}" for i in range(10)]
        scan = {"pages_scanned": pages,
                "page_scans": [{"url": u, "likely_client_rendered": True} for u in pages]}
        plan = caprend.plan_from_scan(scan, cap=3)
        self.assertEqual(len(plan["pages"]), 10)  # DOM capture is the point of the run
        self.assertEqual(plan["dropped"], [])

    class FakeSession:
        def __init__(self, fail_goto=()):
            self.fail_goto = set(fail_goto)
            self.current = None

        def goto(self, url):
            if url in self.fail_goto:
                raise caprend.CaptureError("connection refused (test)")
            self.current = url
            return True

        def evaluate(self, expression, await_promise=False):
            if "outerHTML" in expression:
                return f"<html><body>rendered {self.current}</body></html>"
            if "largest-contentful-paint" in expression:
                return {"lcp_ms": 1200, "cls": 0.02, "tbt_ms": 30}
            return {"checked": 10, "violations": []}

        def close(self):
            pass

    def test_capture_writes_both_handoff_files_and_vitals_reads_them(self):
        home = "https://x.example/"
        app = "https://x.example/app"
        plan = {"pages": [home, app], "dom_pages": [app], "dropped": []}
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "rendered" / "x-example"
            summary = caprend.capture_pages(
                "x-example", plan, session_factory=self.FakeSession,
                out_dir=out_dir, delay_s=0)
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["captured"], [home, app])
            self.assertEqual(summary["failed"], {})

            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(list(manifest["pages"]), [app])
            snap = (out_dir / manifest["pages"][app]["file"]).read_text(encoding="utf-8")
            self.assertIn("rendered https://x.example/app", snap)

            metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(set(metrics["pages"]), {home, app})
            self.assertEqual(metrics["pages"][home]["lcp_ms"], 1200)
            self.assertEqual(metrics["pages"][home]["contrast"]["checked"], 10)

            # scan_vitals consumes the file exactly as written (section 27 schema).
            orig = common.evidence_dir
            common.evidence_dir = lambda: Path(td)
            try:
                graded = vitals.scan(home)
            finally:
                common.evidence_dir = orig
            self.assertTrue(graded["captured"])
            self.assertEqual(graded["checks"]["lcp"]["verdict"], "pass")
            self.assertEqual(graded["checks"]["contrast"]["verdict"], "pass")

    def test_capture_merges_over_an_existing_manual_capture(self):
        first = "https://x.example/a"
        second = "https://x.example/b"
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            caprend.capture_pages("x-example",
                                  {"pages": [first], "dom_pages": [first], "dropped": []},
                                  session_factory=self.FakeSession,
                                  out_dir=out_dir, delay_s=0)
            caprend.capture_pages("x-example",
                                  {"pages": [second], "dom_pages": [second], "dropped": []},
                                  session_factory=self.FakeSession,
                                  out_dir=out_dir, delay_s=0)
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["pages"]), {first, second})
            metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(set(metrics["pages"]), {first, second})

    def test_page_failure_is_named_and_the_run_continues(self):
        bad = "https://x.example/bad"
        good = "https://x.example/good"
        plan = {"pages": [bad, good], "dom_pages": [], "dropped": []}
        with tempfile.TemporaryDirectory() as td:
            summary = caprend.capture_pages(
                "x-example", plan,
                session_factory=lambda: self.FakeSession(fail_goto={bad}),
                out_dir=Path(td), delay_s=0)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["captured"], [good])
        self.assertIn(bad, summary["failed"])
        self.assertIn("connection refused", summary["failed"][bad][0])

    def test_no_browser_found_is_an_honest_note_not_a_crash(self):
        orig = caprend.find_browser
        caprend.find_browser = lambda: None
        try:
            with tempfile.TemporaryDirectory() as td:
                summary = caprend.capture_pages(
                    "x-example",
                    {"pages": ["https://x.example/"], "dom_pages": [], "dropped": []},
                    out_dir=Path(td))
        finally:
            caprend.find_browser = orig
        self.assertFalse(summary["ok"])
        self.assertIn("no Chrome or Edge found", summary["note"])
        self.assertEqual(summary["captured"], [])

    def test_find_browser_env_override(self):
        orig = common.env_value
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            fake = f.name
        try:
            common.env_value = lambda name: fake if name == "REVIEW_BROWSER" else None
            self.assertEqual(caprend.find_browser(), fake)
            common.env_value = (lambda name: r"C:\does\not\exist.exe"
                                if name == "REVIEW_BROWSER" else None)
            self.assertIsNone(caprend.find_browser())
        finally:
            common.env_value = orig
            Path(fake).unlink(missing_ok=True)


class TestDomainRegistration(unittest.TestCase):
    """RDAP domain-registration facts (PLAN.md section 37). Offline: the parse
    step is pure, and check_domain_registration runs against a stubbed
    common.rdap_domain."""

    RDAP_RESPONSE = {
        "events": [
            {"eventAction": "registration", "eventDate": "2015-04-02T00:00:00Z"},
            {"eventAction": "expiration", "eventDate": "2027-04-02T00:00:00Z"},
            {"eventAction": "last changed", "eventDate": "2024-03-01T00:00:00Z"},
        ]
    }

    def test_parse_rdap_reads_the_standard_events(self):
        parsed = common.parse_rdap_domain(self.RDAP_RESPONSE)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["expiration"], "2027-04-02T00:00:00Z")
        self.assertEqual(parsed["registration"], "2015-04-02T00:00:00Z")

    def test_iso_days_returns_days_and_a_date(self):
        # A fixed far-future date is always positive; a fixed past date negative.
        days, date = dns.iso_days("2999-01-01T00:00:00Z")
        self.assertGreater(days, 0)
        self.assertEqual(date, "2999-01-01")
        past_days, past_date = dns.iso_days("2000-01-01T00:00:00Z")
        self.assertLess(past_days, 0)
        self.assertEqual(past_date, "2000-01-01")
        self.assertEqual(dns.iso_days(None), (None, None))
        self.assertEqual(dns.iso_days("not a date"), (None, None))

    def test_registration_checks_are_info_and_carry_dates(self):
        orig = common.rdap_domain
        common.rdap_domain = lambda domain, timeout=None: {
            "ok": True, "expiration": "2999-04-02T00:00:00Z",
            "registration": "2015-04-02T00:00:00Z", "error": None}
        try:
            checks = dns.check_domain_registration("example.com")
        finally:
            common.rdap_domain = orig
        self.assertEqual(checks["domain_expiry"]["verdict"], "info")  # never scored
        self.assertEqual(checks["domain_expiry"]["date"], "2999-04-02")
        self.assertIn("2999-04-02", checks["domain_expiry"]["note"])
        self.assertEqual(checks["domain_created"]["date"], "2015-04-02")
        self.assertIsNotNone(checks["domain_created"]["age_years"])

    def test_unavailable_rdap_degrades_to_one_info_check(self):
        orig = common.rdap_domain
        common.rdap_domain = lambda domain, timeout=None: {
            "ok": False, "expiration": None, "registration": None,
            "error": "No RDAP service published for .example"}
        try:
            checks = dns.check_domain_registration("acme.example")
        finally:
            common.rdap_domain = orig
        self.assertEqual(checks["domain_expiry"]["verdict"], "info")
        self.assertIsNone(checks["domain_expiry"]["date"])
        self.assertNotIn("domain_created", checks)
        self.assertIn("unavailable", checks["domain_expiry"]["note"].lower())

    def test_registration_does_not_change_the_email_auth_grade(self):
        # info verdicts are not graded, so adding them leaves the band intact.
        base = {"spf": {"verdict": "pass"}, "dmarc": {"verdict": "pass"}}
        before = common.grade([c["verdict"] for c in base.values()])
        with_dates = dict(base, domain_expiry={"verdict": "info"},
                          domain_created={"verdict": "info"})
        after = common.grade([c["verdict"] for c in with_dates.values()])
        self.assertEqual(before["band"], after["band"])
        self.assertEqual(before["score"], after["score"])


class TestKeyDates(unittest.TestCase):
    """The key_dates conversation-starter panel data (PLAN.md section 37)."""

    def _scan(self):
        return {
            "host_scans": {
                "tls": {"expires_on": "2026-09-10", "days_to_expiry": 70.0},
                "dns_email": {"checks": {
                    "domain_expiry": {"date": "2027-04-02", "days_to_expiry": 640.0},
                    "domain_created": {"date": "2015-04-02", "age_years": 11.0},
                }},
            }
        }

    def test_key_dates_collects_cert_and_domain_facts(self):
        kd = drpt._key_dates(self._scan())
        labels = [i["label"] for i in kd["items"]]
        self.assertEqual(labels, ["SSL certificate renews", "Domain renews",
                                  "Domain registered"])
        cert = kd["items"][0]
        self.assertEqual(cert["value"], "2026-09-10")
        self.assertEqual(cert["detail"], "in 70 days")
        self.assertEqual(kd["items"][2]["detail"], "about 11.0 years ago")

    def test_key_dates_is_none_when_nothing_measured(self):
        self.assertIsNone(drpt._key_dates({"host_scans": {}}))

    def test_in_days_handles_expired(self):
        self.assertEqual(drpt._in_days(-3.0), "expired 3 days ago")
        self.assertEqual(drpt._in_days(None), "")


def _triage_result(host, overall_score, categories, host_checks=None,
                   page_checks=None, totals=None):
    """A minimal scan_site.run-shaped result for triage tests (PLAN.md 36)."""
    def grade(score):
        band = ("Strong" if score >= 0.85 else "Adequate" if score >= 0.65
                else "Weak" if score >= 0.4 else "Poor")
        return {"score": score, "band": band, "pass": 0, "warn": 0, "fail": 0}
    return {
        "target": f"https://{host}", "host": host, "slug": host.replace(".", "-"),
        "scorecard": {
            "overall": grade(overall_score),
            "categories": {name: grade(s) for name, s in categories.items()},
        },
        "totals": totals or {"fail": 0, "warn": 0},
        "host_scans": {tool: {"checks": checks}
                       for tool, checks in (host_checks or {}).items()},
        "page_scans": [{"url": f"https://{host}", **{
            tool: {"ok": True, "checks": checks}
            for tool, checks in (page_checks or {}).items()}}],
    }


class TestTriage(unittest.TestCase):
    def test_plain_http_is_the_top_hook(self):
        r = _triage_result("a.example", 0.3, {"security": 0.3},
                           host_checks={"http_security": {
                               "https_redirect": {"verdict": "fail", "note": "no redirect"}}})
        self.assertIn("plain HTTP", triage_mod.pick_hook(r))

    def test_cert_expiry_hook_when_https_is_fine(self):
        r = _triage_result("a.example", 0.6, {"tls": 0.5},
                           host_checks={
                               "http_security": {"https_redirect": {"verdict": "pass"}},
                               "tls": {"expiry": {"verdict": "warn",
                                                  "note": "Certificate expires in 12.0 days."}}})
        hook = triage_mod.pick_hook(r)
        self.assertIn("certificate", hook.lower())
        self.assertIn("12.0 days", hook)

    def test_consent_hook_needs_both_trackers_and_no_consent(self):
        base_host = {"http_security": {"https_redirect": {"verdict": "pass"}},
                     "tls": {"expiry": {"verdict": "pass"}}}
        r = _triage_result("a.example", 0.7, {"privacy": 0.6}, host_checks=base_host,
                           page_checks={"privacy": {
                               "known_trackers": {"verdict": "warn"},
                               "cookie_consent": {"verdict": "warn"}}})
        self.assertIn("consent", triage_mod.pick_hook(r).lower())
        # Trackers present but a consent mechanism detected: no consent hook.
        r2 = _triage_result("a.example", 0.7, {"privacy": 0.9}, host_checks=base_host,
                            page_checks={"privacy": {
                                "known_trackers": {"verdict": "warn"},
                                "cookie_consent": {"verdict": "pass"}}})
        self.assertNotIn("consent", triage_mod.pick_hook(r2).lower())

    def test_hook_falls_through_to_weakest_area(self):
        # Everything higher-priority is clean; the hook names the worst category.
        r = _triage_result("a.example", 0.7,
                           {"security": 0.95, "design": 0.6, "seo": 0.8},
                           host_checks={
                               "http_security": {"https_redirect": {"verdict": "pass"},
                                                 "hsts": {"verdict": "pass"},
                                                 "content_security_policy": {"verdict": "pass"},
                                                 "clickjacking": {"verdict": "pass"}},
                               "tls": {"expiry": {"verdict": "pass"}}})
        hook = triage_mod.pick_hook(r)
        self.assertIn("design", hook)

    def test_worst_category_picks_the_lowest_score(self):
        r = _triage_result("a.example", 0.7,
                           {"security": 0.9, "readability": 0.4, "seo": 0.8})
        name, band = triage_mod.worst_category(r)
        self.assertEqual(name, "readability")
        self.assertEqual(band, "Weak")

    def test_score_site_reduces_a_scan_to_a_row(self):
        result = _triage_result("weak.example", 0.35, {"security": 0.2},
                                totals={"fail": 9, "warn": 4},
                                host_checks={"http_security": {
                                    "https_redirect": {"verdict": "fail"}}})
        row = triage_mod.score_site("https://weak.example/", run=lambda url: result)
        self.assertTrue(row["reachable"])
        self.assertEqual(row["domain"], "weak.example")
        self.assertEqual(row["band"], "Poor")
        self.assertEqual(row["fails"], 9)
        self.assertIn("plain HTTP", row["hook"])

    def test_unreachable_domain_becomes_a_flagged_row_not_a_crash(self):
        def boom(url):
            raise ConnectionError("refused")
        row = triage_mod.score_site("https://dead.example/", run=boom)
        self.assertFalse(row["reachable"])
        self.assertEqual(row["band"], "Unreachable")
        self.assertIsNone(row["score"])
        self.assertIn("did not respond", row["hook"])

    def test_rank_orders_worst_first_and_sinks_unreachable(self):
        rows = [
            {"domain": "strong.example", "reachable": True, "score": 0.95, "band": "Strong"},
            {"domain": "poor.example", "reachable": True, "score": 0.30, "band": "Poor"},
            {"domain": "dead.example", "reachable": False, "score": None, "band": "Unreachable"},
            {"domain": "mid.example", "reachable": True, "score": 0.60, "band": "Weak"},
        ]
        ordered = triage_mod.rank(rows)
        self.assertEqual([r["domain"] for r in ordered],
                         ["poor.example", "mid.example", "strong.example", "dead.example"])
        self.assertEqual([r["rank"] for r in ordered], [1, 2, 3, 4])

    def test_triage_scores_every_domain_serially(self):
        results = {
            "https://a.example/": _triage_result("a.example", 0.9, {"security": 0.9}),
            "https://b.example/": _triage_result("b.example", 0.2, {"security": 0.2}),
        }
        ordered = triage_mod.triage(list(results), delay=0,
                                    run=lambda url: results[url])
        self.assertEqual(ordered[0]["domain"], "b.example")  # worst first
        self.assertEqual([r["rank"] for r in ordered], [1, 2])

    def test_read_domains_from_a_list_and_a_file(self):
        self.assertEqual(triage_mod.read_domains(cli_domains=["acme.com"]),
                         ["https://acme.com"])
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "list.txt"
            p.write_text("# a comment\nacme.com\n\nhttps://globex.com\n", encoding="utf-8")
            self.assertEqual(triage_mod.read_domains(source=str(p)),
                             ["https://acme.com", "https://globex.com"])

    def test_csv_and_markdown_render_the_ranked_rows(self):
        rows = triage_mod.rank([
            {"domain": "poor.example", "reachable": True, "score": 0.30, "band": "Poor",
             "worst_area": "security headers (Poor)", "fails": 9, "warns": 4,
             "hook": "Homepage served over plain HTTP with no redirect to HTTPS"},
            {"domain": "dead.example", "reachable": False, "score": None,
             "band": "Unreachable", "worst_area": "", "fails": None, "warns": None,
             "hook": "Site did not respond (ConnectionError)"},
        ])
        with tempfile.TemporaryDirectory() as td:
            csv_path = triage_mod.write_csv(rows, Path(td) / "t.csv")
            md_path = triage_mod.write_markdown(rows, Path(td) / "t.md")
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("rank,domain,band,score,worst_area,fails,warns,hook", csv_text)
            self.assertIn("1,poor.example,Poor,0.30", csv_text)
            self.assertIn(",dead.example,Unreachable,,", csv_text)  # empty score/counts
            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("| 1 | poor.example | Poor | 0.30 |", md_text)


class TestRunOutputsAndArchive(unittest.TestCase):
    def _result(self, measured_at):
        r = json.loads(json.dumps(TestFindingsHistory.RESULT))
        r.update({"measured_at_utc": measured_at, "tool": "scan_site",
                  "host": "acme.example", "slug": "acme-example",
                  "page_scans": []})
        r["issues_grouped"] = {"fail": site.group_issues(r["issues"]["fail"]),
                               "warn": site.group_issues(r["issues"]["warn"])}
        return r

    def test_write_run_outputs_writes_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = site.write_run_outputs(self._result("2026-07-03T10:00:00Z"), out)
            self.assertTrue(paths["json_path"].exists())
            self.assertTrue(paths["digest_path"].exists())
            self.assertTrue(paths["history_path"].exists())
            archived = list((out / "archive").glob("*.json"))
            self.assertEqual([p.name for p in archived],
                             ["acme-example_scan_20260703T100000Z.json"])
            # The archive is the complete scan result, not the slim ledger line.
            data = json.loads(archived[0].read_text(encoding="utf-8"))
            self.assertIn("page_scans", data)

    def test_second_run_appends_ledger_and_new_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            site.write_run_outputs(self._result("2026-07-03T10:00:00Z"), out)
            second = self._result("2026-10-01T09:00:00Z")
            site.write_run_outputs(second, out)
            entries = site.read_history(out / "acme-example_history.jsonl")
            self.assertEqual(len(entries), 2)
            self.assertEqual(len(list((out / "archive").glob("*.json"))), 2)
            # The second run's delta compared against the first ledger entry.
            self.assertEqual(second["delta"]["previous_measured_at"],
                             "2026-07-03T10:00:00Z")

    def test_archive_scan_refuses_without_measured_at_utc(self):
        """K3: the archive is irreplaceable business data, so a scan result
        with no timestamp must not silently land as an overwritable
        'unknown' file; it must raise instead."""
        with tempfile.TemporaryDirectory() as tmp:
            result = self._result("2026-07-03T10:00:00Z")
            result["measured_at_utc"] = ""
            with self.assertRaises(ValueError):
                site.archive_scan(result, Path(tmp))


class TestTrends(unittest.TestCase):
    def _entry(self, ts, overall=0.7, seo=0.8, lcp=2000, fails=(), pages=5,
               with_metrics=True, bands=None):
        e = {
            "measured_at_utc": ts,
            "pages_scanned": pages,
            "bands": bands or {"overall": "Adequate", "seo": "Strong"},
            "issues": {"fail": [{"scan": "http_security", "check": c,
                                 "verdict": "fail", "note": f"{c} missing"}
                                for c in fails],
                       "warn": []},
        }
        if with_metrics:
            e["metrics"] = {
                "scores": {"overall": overall, "seo": seo},
                "pages": {"median_lcp_ms": lcp, "median_cls": None,
                          "median_tbt_ms": None, "median_weight_kb": None,
                          "max_weight_kb": None, "median_reading_ease": None,
                          "broken_links": None, "links_checked": None,
                          "mixed_content": None, "third_party_origins": None,
                          "known_trackers": None},
                "vitals_captured": lcp is not None,
            }
        return e

    def test_quarter_of(self):
        self.assertEqual(trends_mod.quarter_of("2026-07-02T15:37:23Z"), "2026-Q3")
        self.assertEqual(trends_mod.quarter_of("2025-12-31T23:59:59Z"), "2025-Q4")
        self.assertEqual(trends_mod.quarter_of("2026-01-01T00:00:00Z"), "2026-Q1")
        self.assertIsNone(trends_mod.quarter_of(None))
        self.assertIsNone(trends_mod.quarter_of("garbage"))

    def test_latest_run_per_quarter_wins(self):
        entries = [self._entry("2026-01-10T10:00:00Z", overall=0.5),
                   self._entry("2026-07-01T10:00:00Z", overall=0.6),
                   self._entry("2026-09-20T10:00:00Z", overall=0.9)]
        points = trends_mod.quarterly_points(entries)
        self.assertEqual([q for q, _ in points], ["2026-Q1", "2026-Q3"])
        self.assertEqual(points[-1][1]["metrics"]["scores"]["overall"], 0.9)

    def test_quarter_winner_by_latest_timestamp_regardless_of_file_order(self):
        """K1: a backfilled ledger line appended after a later run must not
        shadow the run with the later measured_at_utc within the quarter."""
        entries = [self._entry("2026-07-20T10:00:00Z", overall=0.9),
                   self._entry("2026-07-05T09:00:00Z", overall=0.4)]
        points = trends_mod.quarterly_points(entries)
        self.assertEqual([q for q, _ in points], ["2026-Q3"])
        self.assertEqual(points[0][1]["metrics"]["scores"]["overall"], 0.9)

    def test_quarter_sort_and_winner_across_year_boundary(self):
        """K5 year-boundary case: quarters spanning 2025-Q4 into 2026-Q1
        sort in calendar order, and the K1 winner rule still holds inside
        the 2026-Q1 group even though its later-timestamp entry comes
        first in file order."""
        entries = [self._entry("2026-01-20T10:00:00Z", overall=0.9),
                   self._entry("2025-12-15T09:00:00Z", overall=0.5),
                   self._entry("2026-01-05T08:00:00Z", overall=0.3)]
        points = trends_mod.quarterly_points(entries)
        self.assertEqual([q for q, _ in points], ["2025-Q4", "2026-Q1"])
        by_quarter = dict(points)
        self.assertEqual(by_quarter["2026-Q1"]["metrics"]["scores"]["overall"], 0.9)

    def test_no_trend_under_two_quarterly_points(self):
        self.assertIsNone(trends_mod.build_trend([]))
        same_quarter = [self._entry("2026-07-01T10:00:00Z"),
                        self._entry("2026-09-01T10:00:00Z")]
        self.assertIsNone(trends_mod.build_trend(same_quarter))

    def test_series_align_to_quarters_with_gaps(self):
        entries = [self._entry("2026-01-10T10:00:00Z", overall=0.6, lcp=3000),
                   self._entry("2026-04-10T10:00:00Z", with_metrics=False),
                   self._entry("2026-07-10T10:00:00Z", overall=0.8, lcp=2000)]
        t = trends_mod.build_trend(entries)
        self.assertEqual(t["quarters"], ["2026-Q1", "2026-Q2", "2026-Q3"])
        self.assertEqual(t["series"]["overall_score"], [0.6, None, 0.8])
        self.assertEqual(t["series"]["median_lcp_ms"], [3000, None, 2000])
        # A metric never measured in any quarter gets no series at all.
        self.assertNotIn("median_weight_kb", t["series"])

    def test_latest_delta_directions_and_named_resolved(self):
        entries = [self._entry("2026-01-10T10:00:00Z", overall=0.6, seo=0.8,
                               fails=("hsts", "csp")),
                   self._entry("2026-04-10T10:00:00Z", overall=0.8, seo=0.9,
                               fails=("csp",), pages=6)]
        d = trends_mod.build_trend(entries)["latest_delta"]
        self.assertEqual(d["prev_quarter"], "2026-Q1")
        self.assertEqual(d["quarter"], "2026-Q2")
        seo_row = next(r for r in d["scorecard"] if r["category"] == "seo")
        self.assertEqual(seo_row["direction"], "improved")
        self.assertEqual(seo_row["prev_score"], 0.8)
        self.assertEqual(seo_row["score"], 0.9)
        self.assertEqual(d["new_findings"], 0)
        self.assertEqual(d["resolved_findings"], 1)
        self.assertEqual(d["resolved_examples"],
                         ["[http_security] hsts: hsts missing"])
        self.assertEqual(d["pages_scanned"], {"prev": 5, "current": 6})

    def test_missing_score_falls_back_to_band_direction(self):
        entries = [self._entry("2026-01-10T10:00:00Z", with_metrics=False,
                               bands={"overall": "Weak", "seo": "Weak"}),
                   self._entry("2026-04-10T10:00:00Z",
                               bands={"overall": "Strong", "seo": "Strong"})]
        d = trends_mod.build_trend(entries)["latest_delta"]
        seo_row = next(r for r in d["scorecard"] if r["category"] == "seo")
        self.assertEqual(seo_row["direction"], "improved")

    def test_missing_score_and_band_movement_down_is_declined(self):
        entries = [self._entry("2026-01-10T10:00:00Z", with_metrics=False,
                               bands={"overall": "Strong", "seo": "Strong"}),
                   self._entry("2026-04-10T10:00:00Z",
                               bands={"overall": "Weak", "seo": "Weak"})]
        d = trends_mod.build_trend(entries)["latest_delta"]
        seo_row = next(r for r in d["scorecard"] if r["category"] == "seo")
        self.assertEqual(seo_row["direction"], "declined")

    def test_missing_score_and_same_band_holds(self):
        entries = [self._entry("2026-01-10T10:00:00Z", with_metrics=False),
                   self._entry("2026-04-10T10:00:00Z", with_metrics=False)]
        d = trends_mod.build_trend(entries)["latest_delta"]
        self.assertTrue(all(r["direction"] == "held" for r in d["scorecard"]))

    def test_not_measured_band_holds(self):
        entries = [self._entry("2026-01-10T10:00:00Z", with_metrics=False,
                               bands={"overall": "Adequate", "seo": "Not measured"}),
                   self._entry("2026-04-10T10:00:00Z",
                               bands={"overall": "Adequate", "seo": "Strong"})]
        d = trends_mod.build_trend(entries)["latest_delta"]
        seo_row = next(r for r in d["scorecard"] if r["category"] == "seo")
        self.assertEqual(seo_row["direction"], "held")

    def test_delta_includes_prev_only_category_as_held(self):
        """K5: a category present in the previous quarter's bands but
        retired (or not yet scored) this quarter must still surface, not
        vanish from the scorecard."""
        entries = [self._entry("2026-01-10T10:00:00Z",
                               bands={"overall": "Adequate", "seo": "Strong",
                                      "design": "Strong"}),
                   self._entry("2026-04-10T10:00:00Z",
                               bands={"overall": "Adequate", "seo": "Strong"})]
        d = trends_mod.build_trend(entries)["latest_delta"]
        self.assertEqual([r["category"] for r in d["scorecard"]],
                         ["seo", "design"])
        design_row = next(r for r in d["scorecard"] if r["category"] == "design")
        self.assertEqual(design_row["prev_band"], "Strong")
        self.assertIsNone(design_row["band"])
        self.assertEqual(design_row["direction"], "held")

    def test_trend_from_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                for e in [self._entry("2026-01-10T10:00:00Z"),
                          self._entry("2026-04-10T10:00:00Z")]:
                    f.write(json.dumps(e) + "\n")
            t = trends_mod.trend_from_ledger(path)
        self.assertEqual(t["quarters"], ["2026-Q1", "2026-Q2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
