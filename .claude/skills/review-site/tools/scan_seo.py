#!/usr/bin/env python3
"""
Passive SEO and on-page technical scanner.

Extracts the objective, countable facts an SEO review depends on: title and
meta description quality, canonical and hreflang, Open Graph and Twitter cards,
heading hierarchy, structured data, and image alt coverage. robots.txt and
sitemap checks are host-level facts and live in scan_crawl. It reports counts
and observations, never a fabricated score. Client-rendered pages are flagged
so empty-body results are not mistaken for clean results.

Usage:
    python scan_seo.py <url> [output.json]
"""

import sys

import common
import htmlmeta

TITLE_MIN, TITLE_MAX = 10, 65
DESC_MIN, DESC_MAX = 50, 165

CATEGORY = "seo"
SCOPE = "page"


def _len_verdict(value, lo, hi, label):
    if not value:
        return {"present": False, "length": 0, "verdict": "warn", "note": f"No {label}."}
    n = len(value)
    if n < lo:
        return {"present": True, "length": n, "verdict": "warn", "note": f"{label} is short ({n} chars)."}
    if n > hi:
        return {"present": True, "length": n, "verdict": "warn", "note": f"{label} is long ({n} chars)."}
    return {"present": True, "length": n, "verdict": "pass", "note": f"{label} length {n} chars."}


def _heading_checks(headings, inconclusive):
    if inconclusive:
        return {"h1_count": 0, "verdict": "info",
                "note": "Headings not assessable from static HTML (client-rendered)."}
    levels = [h["level"] for h in headings]
    h1 = levels.count(1)
    skips = []
    prev = 0
    for lv in levels:
        if prev and lv > prev + 1:
            skips.append(f"h{prev}->h{lv}")
        prev = lv
    if h1 == 0:
        return {"h1_count": 0, "skips": skips, "verdict": "fail", "note": "No H1 on the page."}
    if h1 > 1:
        return {"h1_count": h1, "skips": skips, "verdict": "warn", "note": f"{h1} H1 elements (expect one)."}
    if skips:
        return {"h1_count": h1, "skips": skips, "verdict": "warn",
                "note": f"Heading levels skip: {', '.join(skips)}."}
    return {"h1_count": h1, "skips": [], "verdict": "pass", "note": "Single H1, no skipped levels."}


def _og_checks(og):
    need = ["og:title", "og:description", "og:image"]
    have = [k for k in need if og.get(k)]
    if len(have) == len(need):
        return {"present": have, "verdict": "pass", "note": "Core Open Graph tags present."}
    if have:
        missing = [k for k in need if k not in have]
        return {"present": have, "missing": missing, "verdict": "warn",
                "note": f"Open Graph incomplete; missing {', '.join(missing)}."}
    return {"present": [], "verdict": "info", "note": "No Open Graph tags; poorer social sharing."}


def _robots_meta_check(robots):
    if robots and "noindex" in robots.lower():
        return {"value": robots, "verdict": "fail", "note": "Page meta robots contains noindex."}
    return {"value": robots, "verdict": "pass" if robots else "info",
            "note": "No noindex on this page." if not robots else f"Robots meta: {robots}."}


def _image_alt_check(images, inconclusive):
    if inconclusive or not images:
        note = ("Images not assessable from static HTML (client-rendered)."
                if inconclusive else "No images in static HTML.")
        return {"count": len(images), "missing_alt": 0, "verdict": "info", "note": note}
    missing = [i["src"] for i in images if not i["has_alt"]]
    if missing:
        return {"count": len(images), "missing_alt": len(missing),
                "examples": missing[:5], "verdict": "warn",
                "note": f"{len(missing)} of {len(images)} images lack an alt attribute."}
    return {"count": len(images), "missing_alt": 0, "verdict": "pass",
            "note": "All static images carry an alt attribute."}


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_seo", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    inconclusive = render["likely_client_rendered"]

    checks = {
        "title": {**_len_verdict(parsed["title"], TITLE_MIN, TITLE_MAX, "Title"),
                  "value": parsed["title"]},
        "meta_description": {**_len_verdict(parsed["meta_description"], DESC_MIN, DESC_MAX,
                                            "Meta description"),
                             "value": parsed["meta_description"]},
        "canonical": {"value": parsed["canonical"],
                      "verdict": "pass" if parsed["canonical"] else "info",
                      "note": "Canonical set." if parsed["canonical"] else "No canonical link."},
        "viewport": {"value": parsed["meta_viewport"],
                     "verdict": "pass" if parsed["meta_viewport"] else "fail",
                     "note": "Mobile viewport set." if parsed["meta_viewport"]
                     else "No viewport meta; mobile rendering will suffer."},
        "lang": {"value": parsed["html_lang"],
                 "verdict": "pass" if parsed["html_lang"] else "warn",
                 "note": f"html lang={parsed['html_lang']}." if parsed["html_lang"]
                 else "No lang attribute on <html>."},
        "robots_meta": _robots_meta_check(parsed["meta_robots"]),
        "headings": _heading_checks(parsed["headings"], inconclusive),
        "open_graph": _og_checks(parsed["open_graph"]),
        "twitter_card": {"present": list(parsed["twitter_card"].keys()),
                         "verdict": "pass" if parsed["twitter_card"] else "info",
                         "note": "Twitter card tags present." if parsed["twitter_card"]
                         else "No Twitter card tags."},
        "structured_data": {"types": parsed["jsonld_types"],
                            "verdict": "pass" if parsed["jsonld_types"] else "info",
                            "note": (f"JSON-LD types: {', '.join(sorted(set(parsed['jsonld_types'])))}."
                                     if parsed["jsonld_types"] else "No JSON-LD structured data.")},
        "hreflang": {"alternates": parsed["hreflang"],
                     "verdict": "info",
                     "note": f"{len(parsed['hreflang'])} hreflang alternate(s)."},
        "image_alt": _image_alt_check(parsed["images"], inconclusive),
    }

    tally = common.summarize(checks)

    return {
        "tool": "scan_seo",
        "target": url,
        "final_url": base,
        "ok": True,
        "render": render,
        "word_count": parsed["word_count"],
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
        print("Usage: python scan_seo.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
