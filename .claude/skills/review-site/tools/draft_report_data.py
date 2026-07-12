#!/usr/bin/env python3
"""
Draft the executive-report data file from a passive scan result.

Turns a <slug>_scan.json (from scan_site.py) into a first-draft
exec_report_data.json: it fills only the mechanical, measured parts - the
scorecard rows and the findings drawn from failing and warning checks - and
leaves the judgement parts (recommendations, quick wins, and the final CEO
narrative) for a human to author on top. It invents nothing: every field is
copied or derived from measured scan data, draft severities use a stated
fail/warn default, and draft-only text is marked as such. See PLAN.md section 8.

Usage:
    python draft_report_data.py <scan.json> [output.json]
    # default output: <slug>_exec_report_data.draft.json next to the input
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import common
import trends

# Transparent draft severity per verdict; a human reviews and adjusts these.
DRAFT_SEVERITY = {"fail": "High", "warn": "Medium"}
RATING = {"pass": "Good", "warn": "Needs work", "fail": "Poor"}
MAX_ACTIONS = 10

# Plain-language names for the scorecard categories (shared with trends so the
# QoQ table and the scorecard speak the same names; see common.CATEGORY_LABEL).
CATEGORY_LABEL = common.CATEGORY_LABEL

# Standard remediation for each measured failure. The imperative restates the
# measured problem as its accepted fix (not invented advice); unmapped checks
# fall back to the observed note.
ACTION = {
    "https_redirect": "Redirect all plain HTTP traffic to HTTPS",
    "hsts": "Add an HSTS response header (at least 180 days)",
    "content_security_policy": "Add and enforce a Content-Security-Policy that restricts script sources",
    "clickjacking": "Add X-Frame-Options or a CSP frame-ancestors directive",
    "x_content_type_options": "Add the X-Content-Type-Options: nosniff header",
    "referrer_policy": "Set a Referrer-Policy header",
    "permissions_policy": "Set a Permissions-Policy header",
    "cookies": "Add Secure, HttpOnly, and SameSite flags to cookies",
    "subresource_integrity": "Add integrity attributes to cross-origin scripts and styles",
    "insecure_form_action": "Point every form action to an HTTPS URL",
    "mixed_content": "Replace insecure http resources with https",
    "link_health": "Repair or remove the broken links",
    "information_disclosure": "Suppress version-revealing server banners",
    "security_txt": "Publish a security.txt disclosure contact",
    "http2": "Enable HTTP/2 for multiplexed delivery",
    "headings": "Give every page a single H1 with an ordered heading structure",
    "heading_order": "Fix the heading order so levels are not skipped",
    "landmarks": "Add main and nav landmarks to the page template",
    "form_labels": "Add a programmatic label to every form control",
    "image_alt": "Add alt text to images that lack it",
    "link_text": "Give every link descriptive text",
    "anchor_fragments": "Fix in-page links that point to anchors that do not exist",
    "meta_description": "Write a unique, well-sized meta description per page",
    "title": "Right-size and de-duplicate page titles",
    "viewport": "Add a mobile viewport meta tag",
    "sitemap": "Publish an XML sitemap",
    "robots_txt": "Publish a usable robots.txt",
    "host_canonicalization": "Redirect the apex and www hosts to one canonical host",
    "asset_caching": "Set Cache-Control lifetimes on static assets",
    "static_weight": "Reduce page weight on the heaviest pages",
    "image_dimensions": "Set width and height on images to prevent layout shift",
    "reading_ease": "Simplify dense copy toward plainer language",
    "sentence_length": "Shorten long sentences",
    "known_trackers": "Gate third-party trackers behind consent",
    "cookie_consent": "Add a consent mechanism before loading trackers",
    "inline_style_density": "Move inline styles into the stylesheet",
    "document_language": "Declare the document language on the html element",
    "document_title": "Give every page a title",
    "viewport_zoom": "Allow pinch zoom (remove maximum-scale and user-scalable restrictions)",
    "positive_tabindex": "Remove positive tabindex values",
    "empty_buttons": "Give every button an accessible name",
    "spf": "Publish an SPF record",
    "dmarc": "Publish a DMARC policy",
    "protocol": "Raise the minimum TLS version to 1.2",
    "expiry": "Renew the TLS certificate",
    "hostname_coverage": "Reissue the certificate to cover the hostname",
    "compression": "Serve the HTML compressed (gzip or brotli)",
    "redirect_chain": "Collapse the redirect chain to a single hop",
    "tracking_pixels": "Gate tracking pixels behind consent",
    "deprecated_presentational_tags": "Replace deprecated presentational tags with CSS",
    "font_families": "Consolidate the typography to fewer font families",
    "favicon": "Add a favicon",
    "field_lcp": "Improve Largest Contentful Paint for real users",
    "field_cls": "Reduce Cumulative Layout Shift for real users",
    "field_inp": "Improve Interaction to Next Paint for real users",
    "lcp": "Improve Largest Contentful Paint",
    "cls": "Reduce Cumulative Layout Shift",
    "tbt": "Reduce Total Blocking Time",
    "contrast": "Fix low-contrast text to meet WCAG 1.4.3",
    "canonical": "Add a canonical link to every indexable page",
    "robots_meta": "Confirm the noindex robots meta on the affected pages is intentional",
    "open_graph": "Complete the Open Graph tags (title, description, image)",
    "twitter_card": "Add Twitter card tags",
    "structured_data": "Add JSON-LD structured data",
    "dkim": "Publish DKIM keys for the sending domain",
    "dnssec": "Enable DNSSEC on the zone",
    "mta_sts": "Publish an MTA-STS policy",
    "tls_rpt": "Publish a TLS-RPT reporting record",
    "caa": "Publish a CAA record naming the allowed certificate authorities",
}


def _compact_page(url, host):
    """A page reference for the report: the path alone when the page lives on
    the reviewed host (the report names that host once, on the cover), the full
    URL when it does not. The homepage compacts to '/'. Nothing is dropped;
    every page stays individually identifiable."""
    if not host:
        return url
    parsed = urlparse(url)
    if parsed.netloc.lower() == host.lower():
        path = parsed.path or "/"
        return path + (f"?{parsed.query}" if parsed.query else "")
    return url


def _page_list(pages, host):
    # Reports must name every subject; never hide affected pages behind "+N more".
    # Full enumeration, however many pages a finding touches (a severity-ranked
    # finding must say exactly where it applies, even at crawl scale). Same-host
    # pages compact to their path so the enumeration stays readable.
    return ", ".join(_compact_page(p, host) for p in pages)


# One pluralization used everywhere a count reaches the report.
_plural = common.count_noun


def _affects(issue, host):
    pages = issue.get("pages")
    if not pages:
        return "site-wide"
    if len(pages) <= 3:
        return _page_list(pages, host)
    return _plural(len(pages), "page")


# Issue-list labels differ from scorecard category names; the shared map in
# common also serves the trend layer's resolved-item lines.
LABEL_TO_CATEGORY = common.ISSUE_LABEL_TO_CATEGORY


def _area_label(scan_label):
    """Reader-facing area for a finding row: the scan label mapped to its
    scorecard category and shown by its short name (a11y -> Accessibility,
    crux -> Performance). An unknown label passes through unchanged."""
    return common.issue_area(scan_label)


def _worst_by_category(scan):
    """category name -> first (worst) finding note affecting it."""
    grouped = scan.get("issues_grouped") or scan.get("issues", {}) or {}
    worst = {}
    for i in grouped.get("fail", []) + grouped.get("warn", []):
        label = (i.get("scan") or "").split(":", 1)[0]
        category = LABEL_TO_CATEGORY.get(label, label)
        worst.setdefault(category, i.get("note"))
    return worst


def _graded_counts(g):
    p, w, f = g.get("pass", 0), g.get("warn", 0), g.get("fail", 0)
    return p, w, f, (g.get("graded") or p + w + f)


def _checks_phrase(g):
    """'11 of 13 checks pass' from a category's measured counts; a category
    with nothing graded says so instead of the absurd '0 of 0 checks pass'."""
    p, _, _, total = _graded_counts(g)
    if total == 0:
        return "no checks measured"
    return f"{p} of {_plural(total, 'check')} pass"


def _weakness_phrase(g):
    """The failure story in plain words: '3 of 6 checks failing, 2 warnings'.
    Zero counts are dropped instead of printed as noise."""
    p, w, f, total = _graded_counts(g)
    bits = []
    if f:
        bits.append(f"{f} of {_plural(total, 'check')} failing")
    if w:
        bits.append(_plural(w, "warning"))
    return ", ".join(bits) if bits else _checks_phrase(g)


def _assessment(scan):
    """Strengths and weaknesses read straight from the measured scorecard.
    Ordered by score so 'strongest' and 'weakest' claims are true: strengths
    best-first, weaknesses worst-first."""
    cats = (scan.get("scorecard", {}) or {}).get("categories", {}) or {}
    worst = _worst_by_category(scan)
    strong = sorted((g.get("score") or 0, name, g) for name, g in cats.items()
                    if g.get("band") == "Strong")
    weak = sorted((g.get("score") or 0, name, g) for name, g in cats.items()
                  if g.get("band") in ("Weak", "Poor"))
    strengths = [f"{CATEGORY_LABEL.get(name, name)}: strong "
                 f"({_checks_phrase(g)})"
                 for _, name, g in reversed(strong)]
    weaknesses = []
    for _, name, g in weak:
        note = worst.get(name)
        weaknesses.append(f"{CATEGORY_LABEL.get(name, name)}: {g['band'].lower()} "
                          f"({_weakness_phrase(g)})"
                          + (f". Example: {note}" if note else ""))
    wv = _web_vitals(scan)
    # Claim "all Good" only when every expected metric for the source was measured
    # (not a partial subset) and rated Good. A lab capture measures TBT, which is
    # not a Core Web Vital (the interactivity CWV is INP, never available in lab),
    # so phrase a lab pass as lab metrics, never as Core Web Vitals.
    if wv and wv["complete"] and all(m["rating"] == "Good" for m in wv["metrics"]):
        strengths.insert(0, "Core Web Vitals all in the Good range"
                         if wv["source"] == "field"
                         else "Lab performance metrics all in the Good range")
    return {"strengths": strengths, "weaknesses": weaknesses}


# Tie-break tier at equal breadth: compliance and security exposure outranks
# structural and cosmetic findings. An explicit, stated rule, not a score.
PRIORITY_LABELS = {"privacy", "http_security", "pagesec", "tls", "dns_email"}


def _plan_order(issue):
    """Sort key: broadest measured impact first (host-level = whole site),
    then compliance/security labels before the rest at equal breadth."""
    pages = issue.get("pages")
    breadth = float("inf") if not pages else len(pages)
    label = (issue.get("scan") or "").split(":", 1)[0]
    tier = 0 if label in PRIORITY_LABELS else 1
    return (-breadth, tier)


def _action_for(issue):
    check = issue.get("check", "")
    if check:
        return ACTION.get(check) or (issue.get("note") or check)
    if issue.get("scan") == "cross_page":
        return "De-duplicate titles and meta descriptions across pages"
    return issue.get("note") or "See the scan digest"


def _action_plan(scan):
    """A prioritized plan from the grouped findings: fails before warns; within
    each verdict the broadest measured impact first, with compliance/security
    ahead of cosmetics at equal breadth, so a site-wide consent exposure never
    falls off the capped list behind a heading-order warning."""
    grouped = scan.get("issues_grouped") or scan.get("issues", {}) or {}
    host = scan.get("host", "")
    ordered = (sorted(grouped.get("fail", []), key=_plan_order)
               + sorted(grouped.get("warn", []), key=_plan_order))
    plan, seen = [], set()
    for i in ordered:
        key = (i.get("scan", "").split(":", 1)[0], i.get("check", ""))
        if key in seen:
            continue
        seen.add(key)
        plan.append({
            "priority": "High" if i.get("verdict") == "fail" else "Medium",
            "action": _action_for(i),
            "affects": _affects(i, host),
        })
        if len(plan) >= MAX_ACTIONS:
            break
    return plan


def _vitals_metrics(checks, spec):
    """One report metric per measured (non-info) vitals check, in order. The
    target is the published Good threshold the verdict was graded against
    (Google's Core Web Vitals thresholds; Lighthouse's for lab TBT), so the
    report can show how far a number is from good, not just a color."""
    out = []
    for key, label, fmt, target in spec:
        c = checks.get(key) or {}
        if c.get("verdict") in RATING and c.get("value") is not None:
            out.append({"label": label, "value": fmt(c["value"]),
                        "rating": RATING[c["verdict"]], "target": target})
    return out


def _web_vitals(scan):
    """Core Web Vitals for the report, preferring real-user field data (CrUX)
    over a lab capture. Returns None when neither was measured."""
    crux = (scan.get("host_scans") or {}).get("crux") or {}
    field = _vitals_metrics(crux.get("checks", {}), [
        ("field_lcp", "LCP", lambda v: f"{v / 1000:.1f}s", "good is 2.5s or less"),
        ("field_cls", "CLS", lambda v: f"{v:.2f}", "good is 0.10 or less"),
        ("field_inp", "INP", lambda v: f"{int(v)}ms", "good is 200ms or less")])
    if field:
        # complete == all three of LCP, CLS, INP were measured; only then is an
        # "all in the Good range" claim about the full Core Web Vitals honest.
        return {"source": "field", "metrics": field, "complete": len(field) == 3,
                "captured_note": "Real Chrome users, 28-day p75 (CrUX)"}
    for ps in scan.get("page_scans", []) or []:
        lab = _vitals_metrics((ps.get("vitals") or {}).get("checks", {}), [
            ("lcp", "LCP", lambda v: f"{v / 1000:.1f}s", "good is 2.5s or less"),
            ("cls", "CLS", lambda v: f"{v:.2f}", "good is 0.10 or less"),
            ("tbt", "TBT", lambda v: f"{int(v)}ms", "good is 200ms or less")])
        if lab:
            return {"source": "lab", "metrics": lab, "complete": len(lab) == 3,
                    "captured_note": "Lab capture, one load"}
    return None


def _scorecard(scan):
    sc = scan.get("scorecard", {}) or {}
    overall = (sc.get("overall") or {}).get("band", "Not measured")
    rows = []
    for name, g in (sc.get("categories") or {}).items():
        score = g.get("score")
        # Plain-English measured detail; the raw counts stay verifiable in the
        # scan JSON, the report reads like a document rather than a debug dump.
        errors = g.get("errors")
        if errors:
            detail = "scanner error: " + ", ".join(str(e) for e in errors)
        else:
            detail = _checks_phrase(g)
            p, w, f, _ = _graded_counts(g)
            extra = ([_plural(f, "failure")] if f else []) + \
                    ([_plural(w, "warning")] if w else [])
            if extra:
                detail += ", " + ", ".join(extra)
        row = {"category": CATEGORY_LABEL.get(name, name),
               "band": g.get("band", "Not measured"), "detail": detail}
        if score is not None:
            # Numeric copy of the measured score so the report can draw a
            # truthful score bar without parsing the display string.
            row["score"] = score
        rows.append(row)
    # Carry the scanner crashes into the report so a Not-measured category is
    # explained, not silently graded around at the overall level (the P7 class,
    # one layer up: the digest/console surfaced these but the deliverable did not).
    return {"overall": overall, "rows": rows,
            "scanner_errors": scan.get("scanner_errors") or []}


def _finding_from_issue(issue, slug, host):
    scan_label = issue.get("scan", "")
    check = issue.get("check", "")
    note = issue.get("note", "")
    pages = issue.get("pages")
    if pages:
        # A grouped issue: one finding whose evidence names EVERY affected
        # page (a severity-ranked finding must say exactly where it applies).
        area = scan_label
        evidence = (f"{len(pages)} pages: {_page_list(pages, host)}"
                    if len(pages) > 1 else pages[0])
    elif ":" in scan_label:
        area, url = scan_label.split(":", 1)
        evidence = url
    else:
        area = scan_label
        evidence = f"{check} ({slug}_scan.json)" if check else f"{slug}_scan.json"
    return {
        "area": _area_label(area),
        # The note alone is the finding; it is the scanner's own sentence and
        # stays verbatim-traceable to the scan JSON without a check_id: prefix
        # turning a boardroom document into tool output.
        "finding": note or check,
        "evidence": evidence,
        "severity": DRAFT_SEVERITY.get(issue.get("verdict"), "Low"),
    }


def _in_days(days):
    """A short relative-time phrase for a day count, or '' when unknown."""
    if days is None:
        return ""
    d = round(days)
    if d < 0:
        return f"expired {abs(d)} days ago"
    return f"in {d} days"


def _key_dates(scan):
    """Conversation-starter facts for the report: when the SSL certificate and
    the domain registration renew, and how long the domain has been held. All
    passively measured; nothing here is a posture judgement."""
    host_scans = scan.get("host_scans") or {}
    items = []

    tls = host_scans.get("tls") or {}
    if tls.get("expires_on"):
        items.append({"label": "SSL certificate renews", "value": tls["expires_on"],
                      "detail": _in_days(tls.get("days_to_expiry"))})

    dns = (host_scans.get("dns_email") or {}).get("checks") or {}
    de = dns.get("domain_expiry") or {}
    if de.get("date"):
        items.append({"label": "Domain renews", "value": de["date"],
                      "detail": _in_days(de.get("days_to_expiry"))})
    dc = dns.get("domain_created") or {}
    if dc.get("date"):
        detail = f"about {dc['age_years']} years ago" if dc.get("age_years") else ""
        items.append({"label": "Domain registered", "value": dc["date"], "detail": detail})

    if not items:
        return None
    return {"items": items,
            "note": "Public certificate and domain-registration facts, passively measured."}


def draft(scan, trend=None):
    """Build a first-draft exec_report_data dict from a scan_site result dict. trend is the quarterly block from trends.build_trend, when history has one."""
    slug = scan.get("slug", "site")
    scorecard = _scorecard(scan)
    # Grouped issues (one finding per site-wide defect) when the scan provides
    # them; raw per-page issues as the fallback for older scan files. Every
    # distinct finding is named, not a top-N slice: the grouped list is already
    # deduplicated to one entry per defect, so it is naturally bounded, and the
    # builder sorts by severity and renders the whole set. Silently dropping a
    # real finding (a poor site can have more than a dozen) is exactly what the
    # deliverable must not do.
    issues = scan.get("issues_grouped") or scan.get("issues", {}) or {}
    ordered = list(issues.get("fail", [])) + list(issues.get("warn", []))
    findings = [_finding_from_issue(i, slug, scan.get("host", "")) for i in ordered]

    measured_at = scan.get("measured_at_utc", "")
    date = measured_at.split("T", 1)[0] if "T" in measured_at else measured_at
    totals = scan.get("totals", {}) or {}
    n_pages = len(scan.get("pages_scanned", []) or [])

    rendered = any(ps.get("rendered_snapshot_used")
                   for ps in scan.get("page_scans", []) or [])
    scope = {"pages_reviewed": n_pages,
             "method": ("Passive external scan with rendered-DOM capture"
                        if rendered else "Passive external scan")}

    progress = None
    delta = scan.get("delta")
    if delta:
        prev = delta.get("previous_measured_at") or ""
        progress = {"previous_date": prev.split("T", 1)[0] if "T" in prev else prev,
                    "new_issues": len(delta.get("new", [])),
                    "resolved_issues": len(delta.get("resolved", []))}

    if trend:
        # The quarterly trend lives inside the progress area; the builder
        # renders it as its own report section.
        progress = dict(progress or {})
        progress["trend"] = trend

    assessment = _assessment(scan)
    action_plan = _action_plan(scan)
    # The strongest AREA comes from a category strength ("Label: strong (...)"),
    # never from the colon-free Core Web Vitals line inserted ahead of them.
    cat_strengths = [s for s in assessment["strengths"] if ":" in s]
    strongest = cat_strengths[0].split(":")[0] if cat_strengths else None
    top_priority = action_plan[0]["action"] if action_plan else None
    bits = [f"DRAFT (sharpen for the CEO): measured posture is {scorecard['overall']} "
            f"across {_plural(n_pages, 'page')}"]
    # A crashed scanner leaves its category Not measured, so the overall posture
    # covers only what was measured; say so rather than let an uncaveated band read
    # as a clean bill for a category that never ran.
    sc_errors = scorecard.get("scanner_errors") or []
    if sc_errors:
        tools = ", ".join(sorted({str(e.get("tool")) for e in sc_errors}))
        bits.append(f"{common.count_noun(len(sc_errors), 'scanner')} ({tools}) could "
                    "not measure, so this posture covers only the measured categories")
    if strongest:
        # Mid-sentence case: lowercase the label unless it opens with an
        # acronym (TLS, SEO) that must keep its capitals.
        first_word = strongest.split(" ", 1)[0]
        shown = strongest if first_word.isupper() else strongest[0].lower() + strongest[1:]
        bits.append(f"the strongest area is {shown}")
    if top_priority:
        bits.append(f"the top priority is to {top_priority[0].lower() + top_priority[1:]}")
    bottom_line = "; ".join(bits) + "."

    return {
        "site": scan.get("host", slug),
        "slug": slug,
        "target_url": scan.get("target", ""),
        "date": date,
        "bottom_line": bottom_line,
        "scope": scope,
        "progress": progress,
        "web_vitals": _web_vitals(scan),
        "key_dates": _key_dates(scan),
        "assessment": assessment,
        "scorecard": scorecard,
        "findings": findings,
        "action_plan": action_plan,
        "recommendations": [],
        "quick_wins": [],
    }


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python draft_report_data.py <scan.json> [output.json]")
        sys.exit(1)
    in_path = Path(args[0])
    if not in_path.is_file():
        print(f"Scan JSON not found: {in_path}")
        sys.exit(1)
    try:
        scan = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {in_path}: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Could not read {in_path}: {e}")
        sys.exit(1)
    if not isinstance(scan, dict):
        print(f"Scan JSON must be a JSON object, got {type(scan).__name__}: {in_path}")
        sys.exit(1)
    history_path = in_path.with_name(f"{scan.get('slug', 'site')}_history.jsonl")
    trend = trends.trend_from_ledger(history_path) if history_path.exists() else None
    data = draft(scan, trend=trend)
    out_path = (Path(args[1]) if len(args) > 1
                else in_path.with_name(f"{scan.get('slug', 'site')}_exec_report_data.draft.json"))
    common.write_json(out_path, data)
    print(f"Wrote {out_path}")
    print(f"findings: {len(data['findings'])} | scorecard rows: {len(data['scorecard']['rows'])} "
          f"| overall: {data['scorecard']['overall']}")
    print("recommendations and quick_wins left empty for a human to author.")


if __name__ == "__main__":
    main()
