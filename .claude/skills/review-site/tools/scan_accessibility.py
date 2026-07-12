#!/usr/bin/env python3
"""
Static accessibility scanner (WCAG-informed, structural subset).

Checks the accessibility signals that are decidable from HTML alone: document
language and title, image alt coverage, form controls with a programmatic
label, heading order, landmark structure, generic or empty link text, positive
tabindex, and empty buttons. Colour contrast and focus order need a rendered
page and are out of scope here; the browser pass covers those. Client-rendered
pages are flagged so an empty body is not scored as accessible.

Usage:
    python scan_accessibility.py <url> [output.json]
"""

import re
import sys

import common
import htmlmeta

CATEGORY = "accessibility"
SCOPE = "page"

MAX_SCALE_RE = re.compile(r"maximum-scale=(\d+(?:\.\d+)?)")


def _accessible_name(control, labels_for, ids):
    if control["id"] and control["id"] in labels_for:
        return "label[for]"
    if control["wrapped_by_label"]:
        return "wrapping label"
    if control["aria_label"]:
        return "aria-label"
    # aria-labelledby is a space-separated list of id references, not a literal
    # string: it names the control only if at least one referenced id exists on
    # the page. A dangling reference (id typo, JS-generated id absent from the
    # static DOM) provides no accessible name, so fall through rather than credit
    # it - otherwise an effectively-unlabeled control grades "labeled".
    labelledby = control["aria_labelledby"]
    if labelledby and any(tok in ids for tok in labelledby.split()):
        return "aria-labelledby"
    if control["title"]:
        return "title"
    # An image input's accessible name is its alt text, not a <label>.
    if control.get("type") == "image" and control.get("alt"):
        return "alt"
    return None


def _lang_check(parsed):
    if parsed["html_lang"]:
        return {"value": parsed["html_lang"], "verdict": "pass", "note": "Document language declared."}
    return {"value": None, "verdict": "fail", "note": "No lang attribute; screen readers cannot pick a voice."}


def _title_check(parsed):
    if parsed["title"]:
        return {"value": parsed["title"], "verdict": "pass", "note": "Document has a title."}
    return {"value": None, "verdict": "fail", "note": "No document title."}


def _viewport_check(parsed):
    vp = parsed["meta_viewport"] or ""
    low = vp.replace(" ", "").lower()
    scale = MAX_SCALE_RE.search(low)
    # WCAG 1.4.4 needs 200% zoom, so a maximum-scale below 2 restricts it.
    blocks_zoom = ("user-scalable=no" in low or "user-scalable=0" in low
                   or (scale and float(scale.group(1)) < 2))
    if blocks_zoom:
        return {"value": vp, "verdict": "warn",
                "note": "Viewport restricts zoom below 200% (WCAG 1.4.4); pinch-zoom limited."}
    if vp:
        return {"value": vp, "verdict": "pass", "note": "Viewport allows zoom."}
    return {"value": None, "verdict": "warn", "note": "No viewport meta."}


def _alt_check(parsed, inconclusive):
    images = parsed["images"]
    if inconclusive or not images:
        note = ("Images client-rendered; not assessable statically."
                if inconclusive else "No images in static HTML.")
        return {"count": len(images), "missing_alt": 0, "verdict": "info", "note": note}
    missing = [i["src"] for i in images if not i["has_alt"]]
    if missing:
        return {"count": len(images), "missing_alt": len(missing), "examples": missing[:5],
                "verdict": "fail", "note": f"{len(missing)} of {len(images)} images have no alt attribute."}
    return {"count": len(images), "missing_alt": 0, "verdict": "pass",
            "note": "Every static image has an alt attribute."}


def _form_check(parsed, inconclusive):
    controls = parsed["form_controls"]
    if inconclusive or not controls:
        note = ("Forms client-rendered; not assessable statically."
                if inconclusive else "No form controls in static HTML.")
        return {"count": len(controls), "unlabeled": 0, "verdict": "info", "note": note}
    unlabeled, placeholder_only = [], []
    for c in controls:
        src = _accessible_name(c, set(parsed["labels_for"]), set(parsed["ids"]))
        if not src:
            if c["placeholder"]:
                placeholder_only.append(c.get("name") or c.get("id") or c["type"])
            else:
                unlabeled.append(c.get("name") or c.get("id") or c["type"])
    if unlabeled:
        return {"count": len(controls), "unlabeled": len(unlabeled),
                "examples": unlabeled[:5], "placeholder_only": placeholder_only,
                "verdict": "fail",
                "note": f"{common.count_noun(len(unlabeled), 'form control')} "
                        "without a programmatic label."}
    if placeholder_only:
        return {"count": len(controls), "unlabeled": 0, "placeholder_only": placeholder_only,
                "verdict": "warn",
                "note": f"{common.count_noun(len(placeholder_only), 'control')} "
                        "labeled only by placeholder text."}
    return {"count": len(controls), "unlabeled": 0, "verdict": "pass",
            "note": "All form controls have a programmatic label."}


def _heading_check(parsed, inconclusive):
    if inconclusive:
        return {"verdict": "info", "note": "Headings client-rendered; not assessable statically."}
    levels = [h["level"] for h in parsed["headings"]]
    if not levels:
        return {"verdict": "warn", "note": "No headings found; content structure is flat."}
    h1 = levels.count(1)
    skips, prev = [], 0
    for lv in levels:
        if prev and lv > prev + 1:
            skips.append(f"h{prev}->h{lv}")
        prev = lv
    if h1 != 1 or skips:
        issues = []
        if h1 != 1:
            issues.append(f"{h1} H1 elements")
        if skips:
            issues.append("skipped levels " + ", ".join(skips))
        return {"h1_count": h1, "skips": skips, "verdict": "warn",
                "note": "Heading order issues: " + "; ".join(issues) + "."}
    return {"h1_count": h1, "skips": [], "verdict": "pass", "note": "Logical heading order."}


def _landmark_check(parsed, inconclusive):
    if inconclusive:
        return {"verdict": "info", "note": "Landmarks client-rendered; not assessable statically."}
    landmarks = set(parsed["landmarks"])
    roles = set(r.lower() for r in parsed["roles"])
    has_main = "main" in landmarks or "main" in roles
    has_nav = "nav" in landmarks or "navigation" in roles
    if has_main and has_nav:
        return {"landmarks": sorted(landmarks), "verdict": "pass",
                "note": "Main and navigation landmarks present."}
    missing = [x for x, ok in (("main", has_main), ("nav", has_nav)) if not ok]
    word = "landmark" if len(missing) == 1 else "landmarks"
    return {"landmarks": sorted(landmarks), "verdict": "warn",
            "note": f"Missing {word}: {', '.join(missing)}."}


def _link_text_check(parsed, inconclusive):
    anchors = parsed["anchors"]
    if inconclusive or not anchors:
        note = ("Links client-rendered; not assessable statically."
                if inconclusive else "No links in static HTML.")
        return {"count": len(anchors), "verdict": "info", "note": note}
    generic = set(parsed["generic_link_text_set"])
    empty, vague = [], []
    for a in anchors:
        text = (a["text"] or "").strip().lower()
        # An aria-label or a wrapped image's alt text is an accessible name
        # (the logo-link pattern), so such links are not empty.
        named = a["aria_label"] or a.get("img_alt")
        if not text and not named:
            empty.append(a["href"])
        elif text in generic and not named:
            vague.append(text)
    if empty:
        return {"count": len(anchors), "empty_links": len(empty), "vague_links": len(vague),
                "examples": empty[:5], "verdict": "fail",
                "note": f"{common.count_noun(len(empty), 'link')} with no discernible text."}
    if vague:
        return {"count": len(anchors), "empty_links": 0, "vague_links": len(vague),
                "verdict": "warn",
                "note": f"{common.count_noun(len(vague), 'link')} using generic "
                        "text like 'click here'."}
    return {"count": len(anchors), "empty_links": 0, "vague_links": 0,
            "verdict": "pass", "note": "Link text is descriptive."}


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_accessibility", "target": url, "ok": False, "error": res["error"]}

    inconclusive = render["likely_client_rendered"]

    checks = {
        "document_language": _lang_check(parsed),
        "document_title": _title_check(parsed),
        "viewport_zoom": _viewport_check(parsed),
        "image_alt": _alt_check(parsed, inconclusive),
        "form_labels": _form_check(parsed, inconclusive),
        "heading_order": _heading_check(parsed, inconclusive),
        "landmarks": _landmark_check(parsed, inconclusive),
        "link_text": _link_text_check(parsed, inconclusive),
        "positive_tabindex": {
            "count": parsed["positive_tabindex"],
            # Gate on inconclusive like every other body-derived check: a client-
            # rendered page's static tabindex count is not the real page, so grade
            # info (not measured), never a pass on an unmeasured property.
            "verdict": ("warn" if parsed["positive_tabindex"] and not inconclusive
                        else "info" if inconclusive else "pass"),
            "note": ("Tab order not assessable from static HTML (client-rendered)."
                     if inconclusive
                     else f"{common.count_noun(parsed['positive_tabindex'], 'element')} "
                          "with a positive tabindex."
                     if parsed["positive_tabindex"] else "No positive tabindex values.")},
        "empty_buttons": {
            "count": parsed["buttons_empty"],
            "verdict": "warn" if parsed["buttons_empty"] and not inconclusive else "info" if inconclusive else "pass",
            "note": (f"{common.count_noun(parsed['buttons_empty'], 'button')} "
                     "with no accessible text."
                     if parsed["buttons_empty"] else "No empty buttons in static HTML.")},
    }

    tally = common.summarize(checks)

    return {
        "tool": "scan_accessibility",
        "target": url,
        "final_url": res["final_url"],
        "ok": True,
        "render": render,
        "note": "Structural subset only. Colour contrast and focus order require the browser pass.",
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
        print("Usage: python scan_accessibility.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
