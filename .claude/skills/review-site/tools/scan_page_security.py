#!/usr/bin/env python3
"""
Passive page-level security hygiene scanner.

Checks the security signals decidable from a page's static HTML: Subresource
Integrity coverage on cross-origin scripts and stylesheets, forms that post to
plain HTTP from an HTTPS page, inline event handlers (which block a strict
CSP), and target=_blank links without rel=noopener. Complements the host-level
header checks in scan_http_security; both roll into the "security" scorecard
category. Client-rendered pages are flagged so an empty static body is not
scored as secure. See PLAN.md section 13.

Usage:
    python scan_page_security.py <url> [output.json]
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common
import htmlmeta

CATEGORY = "security"
SCOPE = "page"
MAX_EXAMPLES = 5

SCRIPT_RE = common.tag_attrs_re("script")
LINK_RE = common.tag_attrs_re("link")
FORM_RE = common.tag_attrs_re("form")
# Attribute names are anchored with (?<![-\w]) instead of \b: a plain \b also
# matches the tail of hyphenated attributes (data-src, data-action, ng-href),
# which flipped real verdicts (a form's data-action shadowing its insecure
# action, consent-gated data-src scripts counted as live resources).
SRC_RE = re.compile(r"""(?<![-\w])src\s*=\s*["']([^"']+)["']""", re.I)
HREF_RE = re.compile(r"""(?<![-\w])href\s*=\s*["']([^"']+)["']""", re.I)
ACTION_RE = re.compile(r"""(?<![-\w])action\s*=\s*["']([^"']+)["']""", re.I)
REL_RE = re.compile(r"""(?<![-\w])rel\s*=\s*["']([^"']*)["']""", re.I)
INTEGRITY_RE = re.compile(r"(?<![-\w])integrity\s*=", re.I)
# on<event>= attributes (onclick, onload, ...). Word boundary keeps this from
# matching words like "money=" inside attribute values.
INLINE_HANDLER_RE = re.compile(r"\son[a-z]+\s*=\s*[\"']", re.I)


def _cross_origin_resources(body, base):
    """(url, has_integrity) for cross-origin scripts and stylesheets."""
    page_domain = common.registrable_domain(common.host_of(base))
    out = []
    for attrs in SCRIPT_RE.findall(body):
        m = SRC_RE.search(attrs)
        if m:
            out.append((urljoin(base, m.group(1)), bool(INTEGRITY_RE.search(attrs))))
    for attrs in LINK_RE.findall(body):
        rel = REL_RE.search(attrs)
        if not rel or "stylesheet" not in rel.group(1).lower():
            continue
        m = HREF_RE.search(attrs)
        if m:
            out.append((urljoin(base, m.group(1)), bool(INTEGRITY_RE.search(attrs))))
    cross = []
    for url, has_sri in out:
        host = common.host_of(url)
        if urlparse(url).scheme in ("http", "https") and host \
                and common.registrable_domain(host) != page_domain:
            cross.append((url, has_sri))
    return cross


def check_subresource_integrity(body, base, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page is client-rendered; scripts load via JS and are not in static HTML."}
    cross = _cross_origin_resources(body, base)
    if not cross:
        return {"verdict": "info", "cross_origin": 0,
                "note": "No cross-origin scripts or stylesheets in the static HTML."}
    missing = [url for url, has_sri in cross if not has_sri]
    if missing:
        return {"verdict": "warn", "cross_origin": len(cross), "without_integrity": len(missing),
                "examples": missing[:MAX_EXAMPLES],
                "note": (f"{len(missing)} of {len(cross)} cross-origin script/style resource(s) "
                         "lack an integrity attribute; a compromised CDN could alter them undetected.")}
    return {"verdict": "pass", "cross_origin": len(cross), "without_integrity": 0,
            "note": f"All {len(cross)} cross-origin script/style resource(s) carry Subresource Integrity."}


def check_form_actions(body, base, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page is client-rendered; forms are not visible in static HTML."}
    if urlparse(base).scheme != "https":
        return {"verdict": "info", "note": "Page not served over HTTPS; form-action downgrade not applicable."}
    forms = FORM_RE.findall(body)
    if not forms:
        return {"verdict": "info", "count": 0, "note": "No forms in the static HTML."}
    insecure = []
    for attrs in forms:
        m = ACTION_RE.search(attrs)
        if m and m.group(1).strip().lower().startswith("http://"):
            insecure.append(m.group(1))
    if insecure:
        return {"verdict": "fail", "count": len(forms), "insecure_actions": insecure[:MAX_EXAMPLES],
                "note": (f"{len(insecure)} form(s) on this HTTPS page submit to plain http://; "
                         "submitted data would leave the page unencrypted.")}
    return {"verdict": "pass", "count": len(forms),
            "note": f"All {len(forms)} form(s) submit over HTTPS or relative URLs."}


def check_inline_handlers(body, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page is client-rendered; static handler count is not meaningful."}
    count = len(INLINE_HANDLER_RE.findall(body))
    if count:
        return {"verdict": "info", "count": count,
                "note": (f"{count} inline event handler attribute(s) (onclick and similar). "
                         "These require unsafe-inline and block a strict Content-Security-Policy.")}
    return {"verdict": "pass", "count": 0, "note": "No inline event handlers in the static HTML."}


def check_target_blank(anchors, inconclusive):
    if inconclusive:
        return {"verdict": "info",
                "note": "Page is client-rendered; links are not visible in static HTML."}
    # parsed anchors do not carry target/rel, so this check owns its extraction
    # at the caller via regex; anchors here is the pre-extracted list of
    # (target_blank, has_noopener) tuples.
    blank = [a for a in anchors if a[0]]
    if not blank:
        return {"verdict": "pass", "count": 0, "note": "No target=_blank links in the static HTML."}
    unprotected = sum(1 for a in blank if not a[1])
    if unprotected:
        return {"verdict": "info", "count": len(blank), "without_rel": unprotected,
                "note": (f"{unprotected} of {len(blank)} target=_blank link(s) lack rel=noopener. "
                         "Modern browsers imply noopener; older ones allow tab-nabbing.")}
    return {"verdict": "pass", "count": len(blank),
            "note": f"All {len(blank)} target=_blank link(s) carry rel=noopener or noreferrer."}


A_TAG_RE = common.tag_attrs_re("a")
TARGET_BLANK_RE = re.compile(r"""(?<![-\w])target\s*=\s*["']?_blank""", re.I)
NOOPENER_RE = re.compile(r"""(?<![-\w])rel\s*=\s*["'][^"']*(noopener|noreferrer)""", re.I)


def _anchor_targets(body):
    out = []
    for attrs in A_TAG_RE.findall(body):
        out.append((bool(TARGET_BLANK_RE.search(attrs)), bool(NOOPENER_RE.search(attrs))))
    return out


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, render = page["res"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_page_security", "target": url, "ok": False, "error": res["error"]}

    base = res["final_url"]
    body = res["body"] or ""
    inconclusive = render["likely_client_rendered"]

    checks = {
        "subresource_integrity": check_subresource_integrity(body, base, inconclusive),
        "insecure_form_action": check_form_actions(body, base, inconclusive),
        "inline_event_handlers": check_inline_handlers(body, inconclusive),
        "target_blank_rel": check_target_blank(_anchor_targets(body), inconclusive),
    }

    tally = common.summarize(checks)

    return {
        "tool": "scan_page_security",
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
        print("Usage: python scan_page_security.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
