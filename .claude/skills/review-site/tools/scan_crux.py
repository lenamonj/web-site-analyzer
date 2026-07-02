#!/usr/bin/env python3
"""
Chrome UX Report (CrUX) field-data scanner.

Queries Google's public dataset of real-user Chrome experience for the
target origin (one documented API call; passive data retrieval, not a probe
of the target) and grades the p75 Core Web Vitals against the published
thresholds. Needs a GOOGLE_API_KEY (environment or repo-root .env); without
one, or when the origin has insufficient traffic to appear in the dataset,
every check is an honest info and the grade is Not measured. The key is
never logged and never included in results. See PLAN.md section 30.

Usage:
    python scan_crux.py <url> [output.json]
"""

import sys

import common

CATEGORY = "performance"
SCOPE = "host"

API = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
PROVENANCE = "p75 of real Chrome users, 28-day collection (CrUX)"

# Published Core Web Vitals thresholds (web.dev): (good, needs-improvement).
LCP_MS = (2500, 4000)
CLS = (0.1, 0.25)
INP_MS = (200, 500)


def _p75(record, metric):
    m = (record.get("metrics") or {}).get(metric) or {}
    p = (m.get("percentiles") or {}).get("p75")
    if p is None:
        return None
    try:
        return float(p)
    except (TypeError, ValueError):
        return None


def _threshold_check(value, bounds, unit, name):
    if value is None:
        return {"verdict": "info", "value": None,
                "note": f"{name} is not reported for this origin in the CrUX record."}
    good, needs_improvement = bounds
    if value <= good:
        verdict, judgement = "pass", f"within the {good}{unit} good threshold"
    elif value <= needs_improvement:
        verdict, judgement = "warn", f"above the {good}{unit} good threshold (needs improvement)"
    else:
        verdict, judgement = "fail", f"above the {needs_improvement}{unit} poor threshold"
    shown = int(value) if unit == "ms" else value
    return {"verdict": verdict, "value": shown,
            "note": f"{name} {shown}{unit} at p75, {judgement} ({PROVENANCE})."}


def _scan(target):
    host = common.host_of(target) or target.strip()
    origin = f"https://{host}"
    key = common.env_value("GOOGLE_API_KEY")

    if not key:
        note = "Field data not queried: no GOOGLE_API_KEY in the environment or .env."
        checks = {name: {"verdict": "info", "note": note}
                  for name in ("field_lcp", "field_cls", "field_inp")}
        return _result(host, origin, queried=False, checks=checks)

    res = common.http_post_json(f"{API}?key={key}", {"origin": origin})
    if not res["ok"]:
        if res.get("status") == 404:
            note = ("Origin is not in the CrUX dataset (insufficient real-user "
                    "traffic); field data is unavailable, which is an observation, "
                    "not a fault.")
        elif res.get("status") == 403:
            note = ("CrUX query refused (HTTP 403): the API key's Google Cloud "
                    "project likely does not have the Chrome UX Report API "
                    "enabled. Field data not available until it is.")
        else:
            note = f"CrUX query failed ({res.get('error')}); field data unavailable."
        checks = {name: {"verdict": "info", "note": note}
                  for name in ("field_lcp", "field_cls", "field_inp")}
        return _result(host, origin, queried=True, checks=checks)

    record = (res.get("json") or {}).get("record") or {}
    checks = {
        "field_lcp": _threshold_check(_p75(record, "largest_contentful_paint"),
                                      LCP_MS, "ms", "Largest Contentful Paint"),
        "field_cls": _threshold_check(_p75(record, "cumulative_layout_shift"),
                                      CLS, "", "Cumulative Layout Shift"),
        "field_inp": _threshold_check(_p75(record, "interaction_to_next_paint"),
                                      INP_MS, "ms", "Interaction to Next Paint"),
    }
    return _result(host, origin, queried=True, checks=checks)


def _result(host, origin, queried, checks):
    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1
    return {
        "tool": "scan_crux",
        "host": host,
        "origin": origin,
        "queried": queried,
        "summary": tally,
        "checks": checks,
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    result["category"] = CATEGORY
    result["grade"] = common.grade(common.verdicts_of(result))
    return result


def main():
    common.enable_utf8_stdout()
    if len(sys.argv) < 2:
        print("Usage: python scan_crux.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
