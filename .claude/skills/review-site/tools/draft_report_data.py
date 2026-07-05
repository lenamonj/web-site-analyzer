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

import common
import trends

# Transparent draft severity per verdict; a human reviews and adjusts these.
DRAFT_SEVERITY = {"fail": "High", "warn": "Medium"}
RATING = {"pass": "Good", "warn": "Needs work", "fail": "Poor"}
MAX_ACTIONS = 10

# Plain-language names for the scorecard categories in the summary.
CATEGORY_LABEL = {
    "security": "Security posture", "tls": "TLS and certificates",
    "dns_email": "Email authentication", "seo": "SEO and on-page",
    "accessibility": "Accessibility", "links": "Link health",
    "performance": "Performance and delivery", "readability": "Content readability",
    "privacy": "Privacy and tracking", "design": "Design signals",
}

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
}


# Reports must say exactly what and where; never hide subjects behind
# "+N more". Full enumeration up to this ceiling (a crawl-scale run), then an
# explicit pointer to where the complete list lives.
LIST_ALL_PAGES = 40


def _page_list(pages, slug):
    if len(pages) <= LIST_ALL_PAGES:
        return ", ".join(pages)
    rest = len(pages) - LIST_ALL_PAGES
    return (", ".join(pages[:LIST_ALL_PAGES])
            + f", and {rest} more listed in {slug}_scan_summary.md")


def _affects(issue):
    pages = issue.get("pages")
    if not pages:
        return "site-wide"
    if len(pages) <= 3:
        return ", ".join(pages)
    return f"{len(pages)} page(s)"


# Issue-list labels differ from scorecard category names; map back so the
# worst-finding lookup lands on the right category.
LABEL_TO_CATEGORY = {"http_security": "security", "a11y": "accessibility",
                     "perf": "performance", "pagesec": "security", "crawl": "seo",
                     "vitals": "performance", "crux": "performance"}


def _worst_by_category(scan):
    """category name -> first (worst) finding note affecting it."""
    grouped = scan.get("issues_grouped") or scan.get("issues", {}) or {}
    worst = {}
    for i in grouped.get("fail", []) + grouped.get("warn", []):
        label = (i.get("scan") or "").split(":", 1)[0]
        category = LABEL_TO_CATEGORY.get(label, label)
        worst.setdefault(category, i.get("note"))
    return worst


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
    strengths = [f"{CATEGORY_LABEL.get(name, name)}: strong ({g.get('pass', 0)} checks pass)"
                 for _, name, g in reversed(strong)]
    weaknesses = []
    for _, name, g in weak:
        note = worst.get(name)
        detail = f"{g.get('fail', 0)} failing, {g.get('warn', 0)} warnings"
        weaknesses.append(f"{CATEGORY_LABEL.get(name, name)}: {g['band'].lower()} ({detail})"
                          + (f". Example: {note}" if note else ""))
    wv = _web_vitals(scan)
    if wv and all(m["rating"] == "Good" for m in wv["metrics"]):
        strengths.insert(0, "Core Web Vitals all in the Good range")
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
            "affects": _affects(i),
        })
        if len(plan) >= MAX_ACTIONS:
            break
    return plan


def _vitals_metrics(checks, spec):
    """One report metric per measured (non-info) vitals check, in order."""
    out = []
    for key, label, fmt in spec:
        c = checks.get(key) or {}
        if c.get("verdict") in RATING and c.get("value") is not None:
            out.append({"label": label, "value": fmt(c["value"]),
                        "rating": RATING[c["verdict"]]})
    return out


def _web_vitals(scan):
    """Core Web Vitals for the report, preferring real-user field data (CrUX)
    over a lab capture. Returns None when neither was measured."""
    crux = (scan.get("host_scans") or {}).get("crux") or {}
    field = _vitals_metrics(crux.get("checks", {}), [
        ("field_lcp", "LCP", lambda v: f"{v / 1000:.1f}s"),
        ("field_cls", "CLS", lambda v: f"{v:.2f}"),
        ("field_inp", "INP", lambda v: f"{int(v)}ms")])
    if field:
        return {"source": "field", "metrics": field,
                "captured_note": "Real Chrome users, 28-day p75 (CrUX)"}
    for ps in scan.get("page_scans", []) or []:
        lab = _vitals_metrics((ps.get("vitals") or {}).get("checks", {}), [
            ("lcp", "LCP", lambda v: f"{v / 1000:.1f}s"),
            ("cls", "CLS", lambda v: f"{v:.2f}"),
            ("tbt", "TBT", lambda v: f"{int(v)}ms")])
        if lab:
            return {"source": "lab", "metrics": lab,
                    "captured_note": "Lab capture, one load"}
    return None


def _scorecard(scan):
    sc = scan.get("scorecard", {}) or {}
    overall = (sc.get("overall") or {}).get("band", "Not measured")
    rows = []
    for name, g in (sc.get("categories") or {}).items():
        score = g.get("score")
        detail = f"pass/warn/fail = {g.get('pass', 0)}/{g.get('warn', 0)}/{g.get('fail', 0)}"
        if score is not None:
            detail += f" (score {score})"
        row = {"category": name, "band": g.get("band", "Not measured"), "detail": detail}
        if score is not None:
            # Numeric copy of the measured score so the report can draw a
            # truthful score bar without parsing the display string.
            row["score"] = score
        rows.append(row)
    return {"overall": overall, "rows": rows}


def _finding_from_issue(issue, slug):
    scan_label = issue.get("scan", "")
    check = issue.get("check", "")
    note = issue.get("note", "")
    pages = issue.get("pages")
    if pages:
        # A grouped issue: one finding whose evidence names EVERY affected
        # page (a severity-ranked finding must say exactly where it applies).
        area = scan_label
        evidence = (f"{len(pages)} page(s): {_page_list(pages, slug)}"
                    if len(pages) > 1 else pages[0])
    elif ":" in scan_label:
        area, url = scan_label.split(":", 1)
        evidence = url
    else:
        area = scan_label
        evidence = f"{check} ({slug}_scan.json)" if check else f"{slug}_scan.json"
    return {
        "area": area,
        "finding": f"{check}: {note}" if check else note,
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
    findings = [_finding_from_issue(i, slug) for i in ordered]

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
    strongest = assessment["strengths"][0].split(":")[0] if assessment["strengths"] else None
    top_priority = action_plan[0]["action"] if action_plan else None
    bits = [f"DRAFT (sharpen for the CEO): measured posture is {scorecard['overall']} "
            f"across {n_pages} page(s)"]
    if strongest:
        bits.append(f"the strongest area is {strongest.lower()}")
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
    if not in_path.exists():
        print(f"Scan JSON not found: {in_path}")
        sys.exit(1)
    scan = json.loads(in_path.read_text(encoding="utf-8"))
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
