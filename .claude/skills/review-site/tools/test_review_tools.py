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
import unittest
import zlib

import common
import discover_pages as disco
import htmlmeta
import registry as reg
import scan_accessibility as a11y
import scan_dns_email as dns
import scan_http_security as sec
import scan_links as links
import scan_performance as perf
import scan_readability as rd
import scan_seo as seo
import scan_site as site
import scan_tls as tls

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
        self.assertEqual(site._grade(["pass", "pass"])["band"], "Strong")
        self.assertEqual(site._grade(["pass", "warn"])["band"], "Adequate")   # 0.75
        self.assertEqual(site._grade(["pass", "warn", "warn", "fail"])["band"], "Weak")  # 0.5
        self.assertEqual(site._grade(["fail", "fail"])["band"], "Poor")
        not_measured = site._grade(["info", "info"])
        self.assertEqual(not_measured["band"], "Not measured")
        self.assertIsNone(not_measured["score"])

    def test_verdicts_of_prefers_checks_then_top_level(self):
        self.assertEqual(site._verdicts_of({"checks": {"a": {"verdict": "pass"},
                         "b": {"verdict": "fail"}}}), ["pass", "fail"])
        self.assertEqual(site._verdicts_of({"verdict": "fail"}), ["fail"])
        self.assertEqual(site._verdicts_of({"ok": False}), [])

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
    def test_registry_lists_all_eight_scanners(self):
        ids = {e.tool_id for e in reg.REGISTRY}
        self.assertEqual(ids, {
            "scan_http_security", "scan_tls", "scan_dns_email",
            "scan_seo", "scan_accessibility", "scan_links",
            "scan_performance", "scan_readability",
        })
        self.assertEqual(len(reg.host_tools()), 3)
        self.assertEqual(len(reg.page_tools()), 5)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
