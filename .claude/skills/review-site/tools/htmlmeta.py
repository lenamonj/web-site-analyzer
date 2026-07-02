#!/usr/bin/env python3
"""
Single-pass HTML extractor shared by the SEO and accessibility scanners.

Uses only the standard-library html.parser. It captures the structural facts
both scanners need (title, meta tags, links, headings, images, form controls,
landmarks, JSON-LD types, visible word count) so the parsing logic lives in one
place instead of being duplicated.
"""

import json
from html.parser import HTMLParser

import common

VOID_TAGS = {"meta", "link", "img", "input", "br", "hr", "source", "area", "base"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
LANDMARK_TAGS = {"header", "nav", "main", "footer", "aside", "section"}
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template"}
GENERIC_LINK_TEXT = {
    "click here", "here", "read more", "more", "learn more", "link", "this",
    "details", "continue", "go", "click", "read", "download",
}


def _attr_dict(attrs):
    return {k.lower(): (v if v is not None else "") for k, v in attrs}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self._title_buf = []
        self.html_lang = None
        self.metas = []          # raw meta tag attr dicts
        self.links = []          # raw <link> attr dicts
        self.anchors = []        # {href, text, tabindex}
        self.headings = []       # {level, text}
        self.images = []         # {src, has_alt, alt}
        self.form_controls = []  # {tag, type, id, name, accessible_name_sources, wrapped_by_label}
        self.labels_for = set()  # ids referenced by <label for=...>
        self.landmarks = set()
        self.roles = []
        self.jsonld_types = []
        self.positive_tabindex = 0
        self.buttons_empty = 0
        self.word_count = 0
        self._skip_depth = 0
        self._cur_heading = None
        self._heading_buf = []
        self._cur_anchor = None
        self._anchor_buf = []
        self._label_depth = 0
        self._in_jsonld = False
        self._jsonld_buf = []
        self._cur_button = None
        self._button_buf = []

    def _end_title(self):
        """Close the title capture. Also called when another tag interrupts an
        unclosed <title>, so a malformed page cannot swallow the body as title."""
        self._in_title = False
        if self.title is None:
            self.title = "".join(self._title_buf).strip()

    # -- tag open ---------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = _attr_dict(attrs)

        if self._in_title and tag != "title":
            self._end_title()
        if tag in SKIP_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "html" and "lang" in a:
            self.html_lang = a["lang"]
        if tag == "title" and self.title is None:
            self._in_title = True
            self._title_buf = []
        if tag == "meta":
            self.metas.append(a)
        if tag == "link":
            self.links.append(a)
        if tag == "img":
            self.images.append({"src": a.get("src", ""), "has_alt": "alt" in a, "alt": a.get("alt")})
        if tag in LANDMARK_TAGS:
            self.landmarks.add(tag)
        if "role" in a:
            self.roles.append(a["role"])
        if "tabindex" in a:
            try:
                if int(a["tabindex"]) > 0:
                    self.positive_tabindex += 1
            except ValueError:
                pass

        if tag in HEADING_TAGS:
            self._cur_heading = int(tag[1])
            self._heading_buf = []
        if tag == "a" and "href" in a:
            self._cur_anchor = a
            self._anchor_buf = []
        if tag == "label":
            self._label_depth += 1
            if "for" in a:
                self.labels_for.add(a["for"])
        if tag in ("input", "select", "textarea"):
            itype = a.get("type", "text") if tag == "input" else tag
            if itype not in ("hidden",):
                self.form_controls.append({
                    "tag": tag, "type": itype, "id": a.get("id"), "name": a.get("name"),
                    "aria_label": a.get("aria-label"), "aria_labelledby": a.get("aria-labelledby"),
                    "title": a.get("title"), "placeholder": a.get("placeholder"),
                    "wrapped_by_label": self._label_depth > 0,
                })
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buf = []
        if tag == "button":
            self._cur_button = a
            self._button_buf = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    # -- tag close --------------------------------------------------------
    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._in_title:
            self._end_title()
        if tag in HEADING_TAGS and self._cur_heading == int(tag[1]):
            self.headings.append({"level": self._cur_heading, "text": " ".join(self._heading_buf).strip()})
            self._cur_heading = None
        if tag == "a" and self._cur_anchor is not None:
            text = " ".join(self._anchor_buf).strip()
            self.anchors.append({
                "href": self._cur_anchor.get("href", ""),
                "text": text,
                "aria_label": self._cur_anchor.get("aria-label"),
                "tabindex": self._cur_anchor.get("tabindex"),
            })
            self._cur_anchor = None
        if tag == "label" and self._label_depth > 0:
            self._label_depth -= 1
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self._collect_jsonld("".join(self._jsonld_buf))
        if tag == "button" and self._cur_button is not None:
            if not " ".join(self._button_buf).strip() and not self._cur_button.get("aria-label"):
                self.buttons_empty += 1
            self._cur_button = None

    # -- text -------------------------------------------------------------
    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._in_title:
            self._title_buf.append(data)
        if self._cur_heading is not None:
            self._heading_buf.append(data)
        if self._cur_anchor is not None:
            self._anchor_buf.append(data)
        if self._cur_button is not None:
            self._button_buf.append(data)
        if self._skip_depth == 0:
            self.word_count += len(data.split())

    def _collect_jsonld(self, text):
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return
        for node in obj if isinstance(obj, list) else [obj]:
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, list):
                    self.jsonld_types.extend(str(x) for x in t)
                elif t:
                    self.jsonld_types.append(str(t))


SPA_ROOT_MARKERS = ('id="root"', "id='root'", 'id="__next"', 'id="app"',
                    "data-reactroot", "__nuxt__", "ng-version", "ng-app")
# HTML this heavy that still renders almost nothing is shipping a JS shell, not
# a small static page. A genuinely small static page (a few KB) is just small
# and its handful of elements are still worth assessing.
HEAVY_BODY_BYTES = 25000


def render_assessment(parsed, html=""):
    """
    Detect a page whose body is injected by JavaScript.

    Static fetching sees the shipped HTML only. A client-rendered shell ships a
    lot of markup or scripts that render almost no text, so the static scanners
    must say "inconclusive" instead of reporting a clean bill of health. A small
    static page (like a plain landing page) is simply small, so it is NOT flagged
    and its elements are assessed normally. The distinguishing signals are byte
    weight and known single-page-app root markers, not element count alone.
    """
    semantic = len(parsed["headings"]) + len(parsed["anchors"]) + len(parsed["images"])
    sparse = parsed["word_count"] < 40 and semantic < 5
    heavy = len(html) > HEAVY_BODY_BYTES
    has_spa_root = any(m in html.lower() for m in SPA_ROOT_MARKERS)
    likely = sparse and (heavy or has_spa_root)
    if likely:
        why = "heavy body with a JS shell" if heavy else "single-page-app root marker"
        note = ("Static HTML renders almost nothing (words=%d, semantic elements=%d) despite a "
                "%s. The page is client-rendered; static structural findings are inconclusive. "
                "Use the browser-based capture for real content."
                % (parsed["word_count"], semantic, why))
    else:
        note = "Static HTML carries rendered content; structural findings are valid."
    return {"likely_client_rendered": likely, "words": parsed["word_count"],
            "semantic_elements": semantic, "html_bytes": len(html), "note": note}


def _meta_lookup(metas, key, attr="name"):
    for m in metas:
        if m.get(attr, "").lower() == key.lower():
            return m.get("content", "")
    return None


def parse_html(html):
    """Return a structured dict of everything the scanners need from one page."""
    p = _Extractor()
    try:
        p.feed(html or "")
        p.close()  # flush buffered RCDATA (e.g. an unclosed <title>)
    except Exception:
        pass  # malformed markup should degrade, not crash the scan
    if p.title is None and p._title_buf:
        # Unclosed <title>: RCDATA buffering hands us the rest of the document
        # as text. Real title text ends where markup starts.
        p.title = "".join(p._title_buf).split("<", 1)[0].strip()

    canonical = next((l.get("href") for l in p.links if l.get("rel", "").lower() == "canonical"), None)
    hreflangs = [{"lang": l.get("hreflang"), "href": l.get("href")}
                 for l in p.links if l.get("hreflang")]

    og = {m.get("property", ""): m.get("content", "")
          for m in p.metas if m.get("property", "").lower().startswith("og:")}
    twitter = {m.get("name", ""): m.get("content", "")
               for m in p.metas if m.get("name", "").lower().startswith("twitter:")}

    return {
        "title": p.title,
        "html_lang": p.html_lang,
        "meta_description": _meta_lookup(p.metas, "description"),
        "meta_robots": _meta_lookup(p.metas, "robots"),
        "meta_viewport": _meta_lookup(p.metas, "viewport"),
        "meta_theme_color": _meta_lookup(p.metas, "theme-color"),
        "meta_generator": _meta_lookup(p.metas, "generator"),
        "charset": next((m.get("charset") for m in p.metas if "charset" in m), None),
        "canonical": canonical,
        "hreflang": hreflangs,
        "links": p.links,
        "open_graph": og,
        "twitter_card": twitter,
        "headings": p.headings,
        "images": p.images,
        "anchors": p.anchors,
        "form_controls": p.form_controls,
        "labels_for": sorted(p.labels_for),
        "landmarks": sorted(p.landmarks),
        "roles": p.roles,
        "jsonld_types": p.jsonld_types,
        "positive_tabindex": p.positive_tabindex,
        "buttons_empty": p.buttons_empty,
        "word_count": p.word_count,
        "generic_link_text_set": sorted(GENERIC_LINK_TEXT),
    }


def fetch_page(url):
    """
    Fetch and parse a page once, returning a context the page scanners share.

    The orchestrator builds this a single time per URL and hands it to every
    page-level scanner, so a page is fetched and parsed once instead of once per
    scanner. Standalone scanner runs simply call this themselves.
    """
    res = common.http_fetch(common.normalize_url(url))
    body = res.get("body") or ""
    parsed = parse_html(body)
    render = render_assessment(parsed, body)
    return {"url": res.get("final_url", url), "res": res, "parsed": parsed, "render": render}
