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

MAX_FINDINGS = 15
# Transparent draft severity per verdict; a human reviews and adjusts these.
DRAFT_SEVERITY = {"fail": "High", "warn": "Medium"}


def _scorecard(scan):
    sc = scan.get("scorecard", {}) or {}
    overall = (sc.get("overall") or {}).get("band", "Not measured")
    rows = []
    for name, g in (sc.get("categories") or {}).items():
        score = g.get("score")
        detail = f"pass/warn/fail = {g.get('pass', 0)}/{g.get('warn', 0)}/{g.get('fail', 0)}"
        if score is not None:
            detail += f" (score {score})"
        rows.append({"category": name, "band": g.get("band", "Not measured"), "detail": detail})
    return {"overall": overall, "rows": rows}


def _finding_from_issue(issue, slug):
    scan_label = issue.get("scan", "")
    check = issue.get("check", "")
    note = issue.get("note", "")
    pages = issue.get("pages")
    if pages:
        # A grouped issue: one finding whose evidence names the affected pages.
        area = scan_label
        shown = ", ".join(pages[:3])
        more = len(pages) - 3
        evidence = (f"{len(pages)} page(s): {shown}" + (f", +{more} more" if more > 0 else "")
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


def draft(scan):
    """Build a first-draft exec_report_data dict from a scan_site result dict."""
    slug = scan.get("slug", "site")
    scorecard = _scorecard(scan)
    # Grouped issues (one finding per site-wide defect) when the scan provides
    # them; raw per-page issues as the fallback for older scan files.
    issues = scan.get("issues_grouped") or scan.get("issues", {}) or {}
    ordered = list(issues.get("fail", [])) + list(issues.get("warn", []))
    findings = [_finding_from_issue(i, slug) for i in ordered[:MAX_FINDINGS]]

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

    return {
        "site": scan.get("host", slug),
        "target_url": scan.get("target", ""),
        "date": date,
        "bottom_line": (f"DRAFT (rewrite for the CEO): measured posture is "
                        f"{scorecard['overall']} across {n_pages} page(s), with "
                        f"{totals.get('fail', 0)} failing checks and "
                        f"{totals.get('warn', 0)} warnings."),
        "scope": scope,
        "progress": progress,
        "scorecard": scorecard,
        "findings": findings,
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
    data = draft(scan)
    out_path = (Path(args[1]) if len(args) > 1
                else in_path.with_name(f"{scan.get('slug', 'site')}_exec_report_data.draft.json"))
    common.write_json(out_path, data)
    print(f"Wrote {out_path}")
    print(f"findings: {len(data['findings'])} | scorecard rows: {len(data['scorecard']['rows'])} "
          f"| overall: {data['scorecard']['overall']}")
    print("recommendations and quick_wins left empty for a human to author.")


if __name__ == "__main__":
    main()
