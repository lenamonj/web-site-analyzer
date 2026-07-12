#!/usr/bin/env python3
"""
Orchestrator for the passive website evaluation tools.

Runs the host-level scans (HTTP security, TLS, DNS email-auth) once against the
primary target, and the page-level scans (SEO, accessibility, links, page
weight, readability) against the target plus any extra in-scope page URLs. Each
page is fetched and parsed once and that snapshot is shared across all page-level
scanners. Every scanner is wrapped so one failure cannot abort the run. Writes a
combined evidence JSON and a markdown digest under planning/_evidence, and prints
a compact console summary of every non-passing check plus a category scorecard.

Usage:
    python scan_site.py [url] [extra_page_url ...]
    # with no url, reads the first http line from TARGET.txt at the repo root
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import common
import htmlmeta
import registry


# Page-level scanners as (key, module, label), discovered from the central
# registry so adding a scanner never requires editing this orchestrator.
PAGE_SCANNERS = [(e.key, e.module, e.label) for e in registry.page_tools()]


def _safe_scan(fn, *args, tool_name="scan", **kwargs):
    """Run one scanner so a single failure cannot abort the whole review."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"tool": tool_name, "ok": False, "error": f"{type(e).__name__}: {e}"}


def _collect_issues(label, checks):
    """Pull every warn/fail from a checks dict into a flat, citable list."""
    issues = []
    for name, c in checks.items():
        verdict = c.get("verdict")
        if verdict in ("warn", "fail"):
            issues.append({"scan": label, "check": name, "verdict": verdict, "note": c.get("note", "")})
    return issues


def _dup_check(mapping, label, n_pages):
    if n_pages < 2:
        return {"verdict": "info", "note": f"Single page; cross-page {label} comparison not applicable."}
    dups = {value: urls for value, urls in mapping.items() if value and len(urls) >= 2}
    if dups:
        verb = "repeats" if len(dups) == 1 else "repeat"
        return {"verdict": "warn", "duplicates": {v: u for v, u in list(dups.items())[:5]},
                "note": f"{common.count_noun(len(dups), f'{label} value')} {verb} across "
                        f"pages; each page should have a unique {label}."}
    return {"verdict": "pass", "note": f"Each reviewed page has a distinct {label}."}


def load_rendered_snapshots(slug, min_capture_utc=None):
    """url -> rendered HTML captured by the agent's browser pass (PLAN.md
    section 26). Absence of the manifest is the normal case and returns
    empty; the scanners never launch a browser themselves. min_capture_utc,
    when given (a pipeline run's start stamp), drops snapshots captured before
    this run so a prior run's stale DOM is not scanned as current (P23)."""
    base = common.evidence_dir() / "rendered" / slug
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(manifest, dict):  # corrupt manifest: no snapshots, not a crash
        return {}
    out = {}
    for url, entry in (manifest.get("pages") or {}).items():
        if min_capture_utc and (entry.get("captured_at_utc") or "") < min_capture_utc:
            continue  # captured before this run started: stale DOM, skip
        f = base / (entry.get("file") or "")
        if f.is_file():
            out[url] = f.read_text(encoding="utf-8", errors="replace")
    return out


def group_issues(issues):
    """Collapse identical (label, check, verdict) findings that repeat across
    pages into one group carrying the affected pages, so a template-level
    defect is one finding, not one per page. Page issues use the "label:url"
    convention; host issues have no colon and pass through with no pages."""
    groups, order = {}, []
    for issue in issues:
        label, _, url = issue["scan"].partition(":")
        key = (label, issue["check"], issue["verdict"])
        if key not in groups:
            groups[key] = {"scan": label, "check": issue["check"],
                           "verdict": issue["verdict"], "note": issue["note"],
                           "pages": []}
            order.append(key)
        if url:
            groups[key]["pages"].append(url)
    out = []
    for key in order:
        g = groups[key]
        g["page_count"] = len(g["pages"])
        out.append(g)
    return out


def diff_issues(prev_result, result):
    """What changed since the previous run of the same target: issues present
    now but not before (new) and present before but not now (resolved), keyed by
    the grouped defect identity (label, check) with the per-page URL stripped from
    the scan label. The verdict is deliberately NOT part of the key: a defect that
    merely worsens or eases (warn<->fail) is the same persistent defect, so keying
    on the verdict too would report it as one resolved plus one new - a false
    "improvement" claim for a defect that is still there. Counting per-page would
    likewise report one template defect on 40 pages as 40 new, inconsistent with
    the grouped-finding view the report shows."""
    def keyed(res):
        # External ledger corruption can make issues, or its fail/warn sub-lists, or
        # a list item, the wrong type; guard every level so a corrupt entry degrades
        # to "no issues" rather than raising (this runs on every fresh run via
        # attach_delta, so one bad append-only line would otherwise poison all runs).
        issues = res.get("issues")
        if not isinstance(issues, dict):
            issues = {}
        fail, warn = issues.get("fail"), issues.get("warn")
        flat = (fail if isinstance(fail, list) else []) + (warn if isinstance(warn, list) else [])
        return {(i["scan"].partition(":")[0], i["check"]): i for i in flat
                if isinstance(i, dict) and isinstance(i.get("scan"), str) and isinstance(i.get("check"), str)}
    prev, curr = keyed(prev_result), keyed(result)
    return {
        "previous_measured_at": prev_result.get("measured_at_utc"),
        "new": [curr[k] for k in curr if k not in prev],
        "resolved": [prev[k] for k in prev if k not in curr],
    }


def check_cross_page(page_scans):
    """
    Cross-cutting checks no single-page scanner can make: the same title or meta
    description reused across multiple pages, which dilutes search relevance.
    """
    titles, descs = {}, {}
    for ps in page_scans:
        seo = ps.get("seo", {})
        if not seo.get("ok"):
            continue
        checks = seo.get("checks", {})
        t = ((checks.get("title") or {}).get("value") or "").strip()
        d = ((checks.get("meta_description") or {}).get("value") or "").strip()
        titles.setdefault(t, []).append(ps["url"])
        descs.setdefault(d, []).append(ps["url"])
    n = len(page_scans)
    return {
        "duplicate_titles": _dup_check(titles, "title", n),
        "duplicate_descriptions": _dup_check(descs, "meta description", n),
    }


def errored_scanners(host_scans, page_scans):
    """Every scanner that ran but produced no gradable verdict and reported
    failure: a crash caught by _safe_scan, or a scan that could not fetch its
    target. These measured nothing, so they are surfaced by name rather than
    silently graded around (the P7 fabrication-by-omission class)."""
    errors = []
    for e in registry.host_tools():
        sr = host_scans.get(e.key) or {}
        if sr.get("ok") is False and not common.verdicts_of(sr):
            errors.append({"tool": sr.get("tool", e.tool_id), "scope": "host",
                           "error": sr.get("error", "unknown error")})
    for ps in page_scans:
        for e in registry.page_tools():
            sr = ps.get(e.key) or {}
            if sr.get("ok") is False and not common.verdicts_of(sr):
                errors.append({"tool": sr.get("tool", e.tool_id), "scope": ps.get("url"),
                               "error": sr.get("error", "unknown error")})
    return errors


def build_scorecard(host_scans, page_scans):
    """Roll the per-check verdicts up into one band per category plus an overall band.

    Both scopes bucket by the tool's category, and buckets merge, so any number
    of tools can share a scorecard category (scan_crawl and scan_seo both roll
    into "seo"). Host categories always appear (Not measured when empty); a
    page category appears once any page produced verdicts for it.
    """
    cats = {}
    errored = {}  # category -> [tool_id] that ran but measured nothing (crash or unfetchable)
    for e in registry.host_tools():
        sr = host_scans.get(e.key)
        v = common.verdicts_of(sr)
        cats.setdefault(e.category, []).extend(v)
        if not v and (sr or {}).get("ok") is False:
            errored.setdefault(e.category, []).append((sr or {}).get("tool", e.tool_id))
    for e in registry.page_tools():
        acc = []
        for ps in page_scans:
            sr = ps.get(e.key)
            if sr and sr.get("ok"):
                acc += common.verdicts_of(sr)
            elif (sr or {}).get("ok") is False and not common.verdicts_of(sr):
                errored.setdefault(e.category, []).append((sr or {}).get("tool", e.tool_id))
        if acc:
            cats.setdefault(e.category, []).extend(acc)
    categories = {}
    for name, v in cats.items():
        g = common.grade(v)
        if name in errored:
            # A scanner in this category crashed or could not fetch its target, so
            # the category was not fully measured. Do not let the surviving sibling
            # scanners float the band to a clean posture: report it Not measured with
            # the errored tools named (charter: never report an unmeasured thing as a
            # pass). The real pass/warn/fail counts still travel for transparency.
            g = {**g, "band": "Not measured", "score": None,
                 "errors": sorted(set(errored[name]))}
        categories[name] = g
    overall = common.grade([v for lst in cats.values() for v in lst])
    all_errored = sorted({t for ts in errored.values() for t in ts})
    if all_errored:
        # A crash in any one category must be visible on the overall line too.
        overall = {**overall, "errors": all_errored}
    return {"overall": overall, "categories": categories}


def run(target, extra_pages, min_capture_utc=None):
    """Scan the target and its extra pages. min_capture_utc, when given by the
    pipeline (its run-start stamp), makes the scanners ignore rendered evidence
    captured before this run, so a prior run's stale DOM/metrics is never graded
    as a current measurement (P23). None (standalone / manual capture) uses any
    evidence on disk."""
    target = common.normalize_url(target)
    host = common.host_of(target)
    slug = common.slug_of(target)

    # One observation per URL per run (PLAN.md section 16): nav links and
    # shared assets repeat across pages and need not be re-fetched.
    common.enable_fetch_cache()
    try:
        snapshots = load_rendered_snapshots(slug, min_capture_utc)
        return _run(target, host, slug, extra_pages, snapshots, min_capture_utc)
    finally:
        common.disable_fetch_cache()


def _run(target, host, slug, extra_pages, snapshots, min_capture_utc=None):
    host_scans = {
        e.key: _safe_scan(e.module.scan, target, tool_name=e.tool_id)
        for e in registry.host_tools()
    }

    # Dedup the review set so one physical page is never scanned twice: an empty
    # path and "/" are the same resource, so https://h and https://h/ collapse (a
    # homepage almost always links to /), while distinct paths stay distinct.
    seen, page_urls = set(), []
    for u in [target] + [common.normalize_url(u) for u in extra_pages]:
        p = urlparse(u)
        key = (p.scheme, p.netloc.lower(), p.path or "/", p.query)
        if key not in seen:
            seen.add(key)
            page_urls.append(u)
    page_scans = []
    for url in page_urls:
        # Fetch and parse each page once, then share that snapshot with every
        # page-level scanner instead of each one re-fetching the same URL.
        ctx = _safe_scan(htmlmeta.fetch_page, url, tool_name="fetch_page")
        entry = {"url": url}
        # A client-rendered page with an agent-captured DOM snapshot gets its
        # structural scans run against the rendered DOM (PLAN.md section 26).
        # Performance keeps the static context: its numbers are transfer facts.
        rendered_ctx = None
        if isinstance(ctx, dict) and ctx.get("render", {}).get("likely_client_rendered"):
            # Recorded on the entry so a capture plan (PLAN.md section 34) can
            # be built from the scan JSON alone.
            entry["likely_client_rendered"] = True
        snap_html = snapshots.get(url)
        if snap_html and entry.get("likely_client_rendered"):
            rendered_ctx = htmlmeta.page_from_snapshot(url, snap_html, ctx.get("res"))
            entry["rendered_snapshot_used"] = True
        # Carry the run's freshness boundary on the context so the vitals scanner
        # rejects a prior run's stale metrics (P23); other scanners ignore it.
        if isinstance(ctx, dict):
            ctx["min_capture_utc"] = min_capture_utc
        if rendered_ctx is not None:
            rendered_ctx["min_capture_utc"] = min_capture_utc
        for key, module, _ in PAGE_SCANNERS:
            page_arg = ctx if isinstance(ctx, dict) and "res" in ctx else None
            if rendered_ctx is not None and key != "performance":
                page_arg = rendered_ctx
            sr = _safe_scan(module.scan, url, page=page_arg, tool_name=f"scan_{key}")
            if page_arg is rendered_ctx and isinstance(sr, dict):
                sr["evidence_source"] = "rendered_dom"
            entry[key] = sr
        page_scans.append(entry)

    issues = []
    for e in registry.host_tools():
        sr = host_scans[e.key]
        if "checks" in sr:
            issues += _collect_issues(e.label, sr["checks"])
        elif sr.get("verdict") in ("warn", "fail"):
            # A host scanner that could not produce checks but still graded itself
            # (for example a failed TLS handshake) contributes one issue.
            issues.append({"scan": e.label, "check": "handshake", "verdict": sr["verdict"],
                           "note": sr.get("note", "")})
    for ps in page_scans:
        for key, _, label in PAGE_SCANNERS:
            if ps[key].get("ok"):
                issues += _collect_issues(f"{label}:{ps['url']}", ps[key].get("checks", {}))

    cross_page = check_cross_page(page_scans)
    for c in cross_page.values():
        if c["verdict"] in ("warn", "fail"):
            issues.append({"scan": "cross_page", "check": "", "verdict": c["verdict"], "note": c["note"]})

    fails = [i for i in issues if i["verdict"] == "fail"]
    warns = [i for i in issues if i["verdict"] == "warn"]
    grouped_fails = group_issues(fails)
    grouped_warns = group_issues(warns)

    return {
        "tool": "scan_site",
        "target": target,
        "host": host,
        "slug": slug,
        "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pages_scanned": page_urls,
        "totals": {"fail": len(fails), "warn": len(warns),
                   "grouped_fail": len(grouped_fails), "grouped_warn": len(grouped_warns)},
        "scorecard": build_scorecard(host_scans, page_scans),
        "scanner_errors": errored_scanners(host_scans, page_scans),
        "cross_page": cross_page,
        "host_scans": host_scans,
        "page_scans": page_scans,
        "issues": {"fail": fails, "warn": warns},
        "issues_grouped": {"fail": grouped_fails, "warn": grouped_warns},
    }


def issue_line(group):
    """One digest/console line for a grouped issue, naming affected pages."""
    line = f"- [{group['scan']}] {group['check']}: {group['note']}"
    pages = group.get("pages") or []
    if pages:
        shown = ", ".join(pages[:2])
        more = len(pages) - 2
        line += (f" (on {common.count_noun(len(pages), 'page')}: {shown}"
                 + (f", +{more} more)" if more > 0 else ")"))
    return line


def _median(values):
    """Median of the numeric values present; None when none are."""
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    n, mid = len(vals), len(vals) // 2
    if n % 2:
        return vals[mid]
    return round((vals[mid - 1] + vals[mid]) / 2, 3)


def _page_check(ps, tool_key, check_name):
    return ((ps.get(tool_key) or {}).get("checks") or {}).get(check_name) or {}


def collect_metrics(result):
    """Site-level numeric rollups for the trend ledger. Medians for
    continuous metrics so page-set drift between runs cannot masquerade as
    change; sums, unions, or per-page maxima for counts, with the sample
    size stored beside sampled counts. A metric nobody measured stays None:
    a gap in the trend, never a fabricated zero."""
    sc = result.get("scorecard", {}) or {}
    scores = {"overall": (sc.get("overall") or {}).get("score")}
    for name, g in (sc.get("categories") or {}).items():
        scores[name] = g.get("score")

    lcp, cls_vals, tbt, weight, ease = [], [], [], [], []
    broken_counts, checked_counts, mixed_counts, tp_counts = [], [], [], []
    trackers = set()
    trk_seen = vitals_captured = False
    for ps in result.get("page_scans", []) or []:
        if (ps.get("vitals") or {}).get("captured"):
            vitals_captured = True
            for key, acc in (("lcp", lcp), ("cls", cls_vals), ("tbt", tbt)):
                val = _page_check(ps, "vitals", key).get("value")
                if isinstance(val, (int, float)):
                    acc.append(val)
        w = _page_check(ps, "performance", "static_weight").get("total_floor_kb")
        if isinstance(w, (int, float)):
            weight.append(w)
        e = _page_check(ps, "readability", "reading_ease").get("flesch_reading_ease")
        if isinstance(e, (int, float)):
            ease.append(e)
        lh = _page_check(ps, "links", "link_health")
        if isinstance(lh.get("checked"), (int, float)):
            checked_counts.append(lh["checked"])
            broken_counts.append((lh.get("counts") or {}).get("broken") or 0)
        mc = _page_check(ps, "links", "mixed_content")
        if isinstance(mc.get("count"), (int, float)):
            mixed_counts.append(mc["count"])
        # The scanner truncates the per-page domains list (MAX_LIST), so a
        # cross-page union would undercount. The per-page count field is
        # untruncated; the ledger records the max across reviewed pages.
        val = _page_check(ps, "privacy", "third_party_origins").get("count")
        if isinstance(val, (int, float)):
            tp_counts.append(val)
        kt = _page_check(ps, "privacy", "known_trackers")
        if "trackers" in kt:
            trk_seen = True
            trackers.update((kt.get("trackers") or {}).keys())

    return {
        "scores": scores,
        "pages": {
            "median_lcp_ms": _median(lcp),
            "median_cls": _median(cls_vals),
            "median_tbt_ms": _median(tbt),
            "median_weight_kb": _median(weight),
            "max_weight_kb": max(weight) if weight else None,
            "median_reading_ease": _median(ease),
            "broken_links": sum(broken_counts) if checked_counts else None,
            "links_checked": sum(checked_counts) if checked_counts else None,
            "mixed_content": sum(mixed_counts) if mixed_counts else None,
            "third_party_origins": max(tp_counts) if tp_counts else None,
            "known_trackers": len(trackers) if trk_seen else None,
        },
        "vitals_captured": vitals_captured,
    }


def history_entry(result):
    """One ledger line for this run: identity and context for every issue
    (note truncated to bound line size), totals, and the scorecard bands."""
    def slim(issues):
        return [{"scan": i["scan"], "check": i["check"], "verdict": i["verdict"],
                 "note": (i.get("note") or "")[:160]} for i in issues]
    sc = result.get("scorecard", {}) or {}
    bands = {"overall": (sc.get("overall") or {}).get("band")}
    for name, g in (sc.get("categories") or {}).items():
        bands[name] = g.get("band")
    issues = result.get("issues", {}) or {}
    return {
        "measured_at_utc": result.get("measured_at_utc"),
        "target": result.get("target"),
        "pages_scanned": len(result.get("pages_scanned", []) or []),
        "totals": result.get("totals", {}),
        "bands": bands,
        "metrics": collect_metrics(result),
        "issues": {"fail": slim(issues.get("fail", [])),
                   "warn": slim(issues.get("warn", []))},
    }


def append_history(result, path):
    entry = history_entry(result)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_history(path):
    """All ledger entries, oldest first; malformed lines are skipped. A ledger
    entry is a JSON object, so a valid-JSON non-dict line (external corruption)
    is skipped too - consumers do entry.get(...) and would crash on a bare int
    or list."""
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def attach_delta(result, json_path, history_path=None):
    """Attach the new/resolved diff against the previous run. The history
    ledger is the preferred comparison source (it survives the scan-JSON
    overwrite); the old scan JSON is the fallback for evidence dirs from
    before the ledger existed."""
    prev = None
    if history_path:
        entries = read_history(history_path)
        if entries:
            prev = entries[-1]
    if prev is None:
        path = Path(json_path)
        if not path.exists():
            return
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(prev, dict):  # corrupt scan JSON: no delta, not a crash
            return
    result["delta"] = diff_issues(prev, result)


def archive_scan(result, out_dir):
    """Immutable per-run copy of the full scan JSON. The ledger keeps the
    chosen metrics; the archive keeps everything, so a metric not in today's
    ledger schema can still be backfilled into future trends. The archive is
    irreplaceable business data, so a run with no timestamp is refused
    rather than silently stamped (and later overwritten) as "unknown"."""
    if not result.get("measured_at_utc"):
        raise ValueError("scan result has no measured_at_utc; refusing to "
                          "archive without a timestamp")
    stamp = re.sub(r"[-:]", "", result["measured_at_utc"])
    archive_dir = Path(out_dir) / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{result['slug']}_scan_{stamp}.json"
    common.write_json(path, result)
    return path


def write_run_outputs(result, out_dir):
    """Every per-run artifact for a scan result: delta, scan JSON, archive
    copy, ledger line, digest. The one write path shared by scan_site.main
    and run_review so the artifacts can never diverge."""
    out_dir = Path(out_dir)
    slug = result["slug"]
    json_path = out_dir / f"{slug}_scan.json"
    md_path = out_dir / f"{slug}_scan_summary.md"
    history_path = out_dir / f"{slug}_history.jsonl"
    attach_delta(result, json_path, history_path)
    common.write_json(json_path, result)
    archive_scan(result, out_dir)
    append_history(result, history_path)
    write_digest_md(result, md_path, history=read_history(history_path))
    return {"json_path": json_path, "digest_path": md_path,
            "history_path": history_path}


def write_digest_md(result, path, history=None):
    totals = result["totals"]
    lines = [f"# Passive scan digest: {result['host']}", "",
             f"- Target: {result['target']}",
             f"- Measured (UTC): {result['measured_at_utc']}",
             f"- Pages scanned: {len(result['pages_scanned'])}",
             f"- Failing checks: {totals['fail']} ({totals.get('grouped_fail', totals['fail'])} distinct)"
             f"  |  Warnings: {totals['warn']} ({totals.get('grouped_warn', totals['warn'])} distinct)",
             ""]
    rendered_pages = sum(1 for ps in result.get("page_scans", [])
                         if ps.get("rendered_snapshot_used"))
    if rendered_pages:
        lines.insert(5, "- Rendered DOM snapshots used for "
                        f"{common.count_noun(rendered_pages, 'page')}; "
                        "those structural verdicts are measured from the browser-built DOM.")
    sc = result.get("scorecard", {})
    if sc:
        o = sc["overall"]
        lines.append(f"## Scorecard (overall: {o['band']})")
        lines.append("")
        lines.append("| Category | Band | Checks (pass/warn/fail) |")
        lines.append("| --- | --- | --- |")
        for name, g in sc["categories"].items():
            lines.append(f"| {name} | {g['band']} | {g['pass']}/{g['warn']}/{g['fail']} |")
        lines.append("")
    errs = result.get("scanner_errors") or []
    if errs:
        lines += ["## Scanner errors", "",
                  "These scanners did not complete, so their checks were not measured "
                  "and their categories read Not measured, never a clean pass:", ""]
        for e in errs:
            lines.append(f"- [{e['tool']}] {e['scope']}: {e['error']}")
        lines.append("")
    grouped = result.get("issues_grouped", result["issues"])
    lines += ["## Failing checks", ""]
    if grouped["fail"]:
        for g in grouped["fail"]:
            lines.append(issue_line(g))
    else:
        lines.append("- None.")
    lines += ["", "## Warnings", ""]
    if grouped["warn"]:
        for g in grouped["warn"]:
            lines.append(issue_line(g))
    else:
        lines.append("- None.")
    delta = result.get("delta")
    if delta:
        lines += ["", f"## Changes since previous scan ({delta.get('previous_measured_at')})", "",
                  f"New: {len(delta['new'])}  |  Resolved: {len(delta['resolved'])}", ""]
        for i in delta["new"][:20]:
            lines.append(f"- NEW [{i['scan']}] {i['check']}: {i['note']}")
        for i in delta["resolved"][:20]:
            lines.append(f"- RESOLVED [{i['scan']}] {i['check']}")
    if history and len(history) >= 2:
        recent = history[-5:]
        lines += ["", f"## Trend (last {len(recent)} runs)", ""]
        for e in recent:
            bands = e.get("bands", {}) or {}
            totals = e.get("totals", {}) or {}
            lines.append(f"- {e.get('measured_at_utc')}: overall {bands.get('overall')}, "
                         f"fail {totals.get('fail')}, warn {totals.get('warn')}")
        prev_band = (recent[-2].get("bands") or {}).get("overall")
        curr_band = (recent[-1].get("bands") or {}).get("overall")
        if prev_band and curr_band and prev_band != curr_band:
            lines.append(f"- Overall band moved: {prev_band} -> {curr_band}.")
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    if args and ("." in args[0] or args[0].lower().startswith("http")):
        target, extra = args[0], args[1:]
    else:
        target, extra = common.read_target_file(), args
    if not target:
        print("No target given and no http line found in TARGET.txt")
        sys.exit(1)

    result = run(target, extra)

    out_dir = common.evidence_dir()
    paths = write_run_outputs(result, out_dir)

    print_console_summary(result)
    print(f"\nWrote {paths['json_path']}")
    print(f"Wrote {paths['digest_path']}")


def print_console_summary(result):
    """The stdout run summary. A seam so the summary (including the scanner-error
    block) is testable without driving main's argv and evidence-dir side effects."""
    print(f"Target: {result['target']}")
    print(f"Pages scanned: {len(result['pages_scanned'])}")
    print(f"Failing checks: {result['totals']['fail']} | Warnings: {result['totals']['warn']}")
    sc = result.get("scorecard", {})
    if sc:
        print(f"\nScorecard (overall: {sc['overall']['band']}):")
        for name, g in sc["categories"].items():
            score = "n/a" if g["score"] is None else f"{g['score']:.2f}"
            print(f"  {name:14s} {g['band']:10s} pass/warn/fail = {g['pass']}/{g['warn']}/{g['fail']}  ({score})")
    errs = result.get("scanner_errors") or []
    if errs:
        print("\nSCANNER ERRORS (checks not measured):")
        for e in errs:
            print(f"  [{e['tool']}] {e['scope']}: {e['error']}")
    grouped = result.get("issues_grouped", result["issues"])
    if grouped["fail"]:
        print("\nFAIL:")
        for g in grouped["fail"]:
            print("  " + issue_line(g)[2:])
    if grouped["warn"]:
        print("\nWARN:")
        for g in grouped["warn"]:
            print("  " + issue_line(g)[2:])
    delta = result.get("delta")
    if delta:
        print(f"\nSince previous scan ({delta.get('previous_measured_at')}): "
              f"{len(delta['new'])} new, {len(delta['resolved'])} resolved.")


if __name__ == "__main__":
    main()
