#!/usr/bin/env python3
"""
Browser-measured web vitals and contrast consumer.

Reads the metrics the agent's browser pass captured for this page
(planning/_evidence/rendered/<slug>/metrics.json, schema in PLAN.md section
27 and tools/CAPTURE.md) and grades them against the published Core Web
Vitals and Lighthouse thresholds. This tool measures nothing itself and
never launches a browser: when no capture exists for the page, every check
is info and the grade is Not measured. Metrics are lab measurements of one
load and are labeled as such.

Usage:
    python scan_vitals.py <url> [output.json]
"""

import json
import sys

import common

CATEGORY = "performance"
SCOPE = "page"
MAX_EXAMPLES = 5

# Published thresholds: Core Web Vitals (web.dev) for LCP and CLS,
# Lighthouse for TBT. (good, needs-improvement) boundaries.
LCP_MS = (2500, 4000)
CLS = (0.1, 0.25)
TBT_MS = (200, 600)

NOT_CAPTURED = ("No browser-captured metrics for this page; run the browser "
                "pass per SKILL.md to measure it.")


def load_metrics(url):
    """The captured metrics entry for this exact url, or None."""
    slug = common.slug_of(url)
    path = common.evidence_dir() / "rendered" / slug / "metrics.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):  # corrupt metrics.json: not measured, not a crash
        return None
    return (data.get("pages") or {}).get(common.normalize_url(url))


def _threshold_check(value, bounds, unit, name):
    if value is None:
        return {"verdict": "info", "value": None, "note": NOT_CAPTURED}
    good, needs_improvement = bounds
    if value <= good:
        verdict = "pass"
        judgement = f"within the {good}{unit} good threshold"
    elif value <= needs_improvement:
        verdict = "warn"
        judgement = f"above the {good}{unit} good threshold (needs improvement)"
    else:
        verdict = "fail"
        judgement = f"above the {needs_improvement}{unit} poor threshold"
    return {"verdict": verdict, "value": value,
            "note": f"{name} measured {value}{unit}, {judgement} (lab measurement, one load)."}


def check_contrast(contrast):
    if not contrast:
        return {"verdict": "info", "note": NOT_CAPTURED}
    checked = contrast.get("checked", 0)
    violations = contrast.get("violations") or []
    if violations:
        examples = "; ".join(
            f"{v.get('sample', '?')} ({v.get('ratio')}:1, needs {v.get('required')}:1)"
            for v in violations[:MAX_EXAMPLES])
        return {"verdict": "fail", "checked": checked, "violations": len(violations),
                "examples": violations[:MAX_EXAMPLES],
                "note": (f"{len(violations)} of {checked} sampled text elements fail "
                         f"WCAG 1.4.3 contrast: {examples}.")}
    if checked:
        return {"verdict": "pass", "checked": checked, "violations": 0,
                "note": f"All {checked} sampled text elements meet WCAG 1.4.3 contrast."}
    return {"verdict": "info", "note": "Contrast was not sampled in the capture."}


def _scan(url, page=None):
    url = common.normalize_url(url)
    metrics = load_metrics(url)
    if metrics is None:
        checks = {name: {"verdict": "info", "note": NOT_CAPTURED}
                  for name in ("lcp", "cls", "tbt", "contrast")}
        captured = False
    else:
        checks = {
            "lcp": _threshold_check(metrics.get("lcp_ms"), LCP_MS, "ms",
                                    "Largest Contentful Paint"),
            "cls": _threshold_check(metrics.get("cls"), CLS, "",
                                    "Cumulative Layout Shift"),
            "tbt": _threshold_check(metrics.get("tbt_ms"), TBT_MS, "ms",
                                    "Total Blocking Time"),
            "contrast": check_contrast(metrics.get("contrast")),
        }
        captured = True

    tally = common.summarize(checks)

    return {
        "tool": "scan_vitals",
        "target": url,
        "ok": True,
        "captured": captured,
        "captured_at_utc": (metrics or {}).get("captured_at_utc"),
        "summary": tally,
        "checks": checks,
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    return common.finalize(result, CATEGORY)


def main():
    common.enable_utf8_stdout()
    if len(sys.argv) < 2:
        print("Usage: python scan_vitals.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
