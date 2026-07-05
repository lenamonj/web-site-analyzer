#!/usr/bin/env python3
"""
Static design-signal scanner.

Measures the design facts decidable without rendering: favicon and
theme-color declarations, deprecated presentational tags, inline-style
density, the distinct font families declared in inline and linked CSS, and
images shipped without dimensions (layout shift). These are objective,
countable signals of design consistency and polish; aesthetic judgement stays
with the browser-based visual pass in SKILL.md. Head-level declarations
(favicon, theme-color, stylesheets) are assessed even on client-rendered
pages because the shipped head is static; body-derived checks are marked
inconclusive there. See PLAN.md section 15.

Usage:
    python scan_design.py <url> [output.json]
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common
import htmlmeta

CATEGORY = "design"
SCOPE = "page"
MAX_STYLESHEETS = 5      # bounded, passive CSS fetches per page
MAX_EXAMPLES = 5
INLINE_STYLE_WARN = 30
FONT_FAMILY_WARN = 4

DEPRECATED_RE = re.compile(r"<(font|center|marquee|blink|frameset|frame|big|strike)\b", re.I)
# (?<![-\w]) instead of \b so hyphenated attributes (data-src, data-width,
# lazy-load patterns) never satisfy the real attribute's regex.
STYLE_ATTR_RE = re.compile(r"""(?<![-\w])style\s*=\s*["']""", re.I)
STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.I | re.S)
FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
IMG_RE = common.tag_attrs_re("img")
SRC_RE = re.compile(r"""(?<![-\w])src\s*=\s*["']([^"']+)["']""", re.I)
WIDTH_ATTR_RE = re.compile(r"(?<![-\w])width\s*=", re.I)
HEIGHT_ATTR_RE = re.compile(r"(?<![-\w])height\s*=", re.I)
STYLE_ATTR_RE = re.compile(r"""(?<![-\w])style\s*=\s*["']([^"']*)""", re.I)

GENERIC_FONTS = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
    "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji",
    "inherit", "initial", "unset", "revert",
}


def check_favicon(parsed, base):
    """A declared icon link, or the default /favicon.ico. Browsers request the
    default path anyway, so its existence counts; one extra passive GET."""
    declared = [l for l in parsed["links"] if "icon" in (l.get("rel", "") or "").lower()]
    if declared:
        return {"verdict": "pass", "declared": len(declared),
                "note": f"{len(declared)} icon link(s) declared (favicon or touch icon)."}
    res = common.http_fetch(urljoin(base, "/favicon.ico"), method="HEAD", want_body=False)
    if res.get("final_status") in (405, 501):
        # Some servers reject HEAD; do not report a missing favicon off that.
        res = common.http_fetch(urljoin(base, "/favicon.ico"), method="GET", want_body=False)
    if res.get("final_status") == 200:
        return {"verdict": "pass", "declared": 0,
                "note": "No icon link declared, but the default /favicon.ico exists."}
    if not res["ok"]:  # fetch did not complete (no response, or a failed redirect)
        return {"verdict": "info", "declared": 0,
                "note": "No icon link declared; /favicon.ico could not be checked."}
    return {"verdict": "warn", "declared": 0,
            "note": ("No favicon: no icon link declared and /favicon.ico is absent. Browser "
                     "tabs and bookmarks show a blank default for this site.")}


def check_theme_color(parsed):
    if parsed.get("meta_theme_color"):
        return {"verdict": "pass", "value": parsed["meta_theme_color"],
                "note": f"theme-color declared ({parsed['meta_theme_color']})."}
    return {"verdict": "info", "value": None,
            "note": "No theme-color meta; mobile browser chrome uses its default tint."}


def check_deprecated_tags(body, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page body is client-rendered; static tag scan is not representative."}
    counts = {}
    for tag in DEPRECATED_RE.findall(body):
        tag = tag.lower()
        counts[tag] = counts.get(tag, 0) + 1
    if counts:
        listed = ", ".join(f"{t} x{n}" for t, n in sorted(counts.items()))
        return {"verdict": "warn", "counts": counts,
                "note": f"Deprecated presentational tag(s) in the markup: {listed}."}
    return {"verdict": "pass", "counts": {}, "note": "No deprecated presentational tags."}


def check_inline_style_density(body, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page body is client-rendered; static inline-style count is not representative."}
    count = len(STYLE_ATTR_RE.findall(body))
    if count > INLINE_STYLE_WARN:
        return {"verdict": "warn", "count": count,
                "note": (f"{count} inline style attributes on one page; styling is escaping the "
                         "stylesheet, which erodes visual consistency and maintainability.")}
    return {"verdict": "pass", "count": count,
            "note": f"{count} inline style attribute(s) in the static HTML."}


def _first_family(declaration):
    fam = declaration.split(",")[0].strip().strip("'\"").lower()
    if not fam or fam in GENERIC_FONTS or fam.startswith("var("):
        return None
    return fam


def _stylesheet_urls(parsed, base):
    urls = []
    for l in parsed["links"]:
        rel = (l.get("rel", "") or "").lower()
        href = l.get("href")
        if "stylesheet" in rel and href:
            absolute = urljoin(base, href)
            if urlparse(absolute).scheme in ("http", "https"):
                urls.append(absolute)
    return urls[:MAX_STYLESHEETS]


def check_font_families(body, parsed, base):
    """Distinct non-generic families declared in inline <style> blocks and up
    to MAX_STYLESHEETS same-page stylesheets. Head declarations survive client
    rendering, so this runs on every page."""
    css_texts = [m for m in STYLE_BLOCK_RE.findall(body)]
    sheets = _stylesheet_urls(parsed, base)
    fetched = 0
    for url in sheets:
        res = common.http_fetch(url, want_body=True)
        if res.get("final_status") == 200 and res.get("body"):
            css_texts.append(res["body"])
            fetched += 1
    families = []
    for text in css_texts:
        for decl in FONT_FAMILY_RE.findall(text):
            fam = _first_family(decl)
            if fam and fam not in families:
                families.append(fam)
    if not css_texts:
        return {"verdict": "info", "families": [], "stylesheets_read": 0,
                "note": "No inline styles or readable stylesheets to inspect for fonts."}
    if len(families) > FONT_FAMILY_WARN:
        return {"verdict": "warn", "families": families, "stylesheets_read": fetched,
                "note": (f"{len(families)} distinct font families declared "
                         f"({', '.join(families[:8])}); more than {FONT_FAMILY_WARN} "
                         "reads as typographic inconsistency.")}
    if families:
        return {"verdict": "pass", "families": families, "stylesheets_read": fetched,
                "note": f"{len(families)} font family(ies): {', '.join(families)}."}
    return {"verdict": "info", "families": [], "stylesheets_read": fetched,
            "note": "No explicit non-generic font-family declarations found."}


def _style_reserves_space(attrs):
    """True if an inline style declares enough to reserve the image box before load
    (so it does not shift layout). Grade the declared PROPERTIES, not a 'width'
    substring: max-width/min-width reserve nothing, and a bare width with no height
    (a percentage width) also reserves no vertical space. The box is reserved by an
    explicit width AND height, or by aspect-ratio (which fixes the proportion)."""
    m = STYLE_ATTR_RE.search(attrs)
    if not m:
        return False
    props = {decl.split(":", 1)[0].strip().lower()
             for decl in m.group(1).split(";") if ":" in decl}
    return "aspect-ratio" in props or ("width" in props and "height" in props)


def check_image_dimensions(body, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page body is client-rendered; static image scan is not representative."}
    imgs = IMG_RE.findall(body)
    if not imgs:
        return {"verdict": "info", "count": 0, "note": "No images in the static HTML."}
    missing = []
    for attrs in imgs:
        has_dims = (WIDTH_ATTR_RE.search(attrs) and HEIGHT_ATTR_RE.search(attrs)) \
            or _style_reserves_space(attrs)
        if not has_dims:
            m = SRC_RE.search(attrs)
            missing.append(m.group(1) if m else "(no src)")
    if len(missing) * 2 > len(imgs):
        return {"verdict": "warn", "count": len(imgs), "missing_dimensions": len(missing),
                "examples": missing[:MAX_EXAMPLES],
                "note": (f"{len(missing)} of {len(imgs)} images declare no width/height, so the "
                         "layout shifts as they load (cumulative layout shift).")}
    return {"verdict": "pass", "count": len(imgs), "missing_dimensions": len(missing),
            "note": f"{len(imgs) - len(missing)} of {len(imgs)} images declare dimensions."}


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_design", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    body = res["body"] or ""
    inconclusive = render["likely_client_rendered"]

    checks = {
        "favicon": check_favicon(parsed, base),
        "theme_color": check_theme_color(parsed),
        "deprecated_presentational_tags": check_deprecated_tags(body, inconclusive),
        "inline_style_density": check_inline_style_density(body, inconclusive),
        "font_families": check_font_families(body, parsed, base),
        "image_dimensions": check_image_dimensions(body, inconclusive),
    }

    tally = common.summarize(checks)

    return {
        "tool": "scan_design",
        "target": url,
        "final_url": base,
        "ok": True,
        "render": render,
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
        print("Usage: python scan_design.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
