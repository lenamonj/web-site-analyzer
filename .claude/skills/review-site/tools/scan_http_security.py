#!/usr/bin/env python3
"""
Passive HTTP security-posture scanner.

Checks the HTTP-to-HTTPS redirect, the standard security response headers,
cookie flags, and version-disclosure banners. Every result is an observed fact
plus a defensible verdict (pass / warn / fail / info). No active probing.

Usage:
    python scan_http_security.py <url> [output.json]
"""

import sys
from urllib.parse import urlparse

import common

# Recommended HSTS floor: 180 days in seconds.
HSTS_MIN_AGE = 15552000


def _verdict(status, note):
    return {"verdict": status, "note": note}


def check_https_redirect(host):
    """Fetch http://host and confirm it upgrades to https."""
    res = common.http_fetch(f"http://{host}", want_body=False)
    if not res["ok"] and not res["hops"]:
        return {"reachable_over_http": False, "detail": res["error"],
                **_verdict("info", "Host did not answer on plain HTTP.")}
    final_scheme = urlparse(res["final_url"]).scheme
    chain = [f'{h["status"]} {h["url"]}' for h in res["hops"]]
    if final_scheme == "https":
        return {"reachable_over_http": True, "redirect_chain": chain, "final_url": res["final_url"],
                **_verdict("pass", "Plain HTTP redirects to HTTPS.")}
    return {"reachable_over_http": True, "redirect_chain": chain, "final_url": res["final_url"],
            **_verdict("fail", "Plain HTTP is served without a redirect to HTTPS.")}


def check_hsts(headers):
    val = headers.get("strict-transport-security")
    if not val:
        return {"present": False, "value": None,
                **_verdict("fail", "No HSTS header. Browsers may connect over HTTP.")}
    max_age = 0
    for part in val.split(";"):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                max_age = 0
    includes_sub = "includesubdomains" in val.lower()
    preload = "preload" in val.lower()
    if max_age < HSTS_MIN_AGE:
        note = f"HSTS present but max-age {max_age}s is below the 180-day floor."
        verdict = "warn"
    else:
        note = f"HSTS max-age {max_age}s."
        verdict = "pass"
    return {"present": True, "value": val, "max_age": max_age,
            "include_subdomains": includes_sub, "preload": preload,
            **_verdict(verdict, note)}


def check_simple_header(headers, name, expected=None, fail_note="Header missing."):
    val = headers.get(name.lower())
    if not val:
        return {"present": False, "value": None, **_verdict("fail", fail_note)}
    if expected and expected.lower() not in val.lower():
        return {"present": True, "value": val,
                **_verdict("warn", f"Present but expected to contain '{expected}'.")}
    return {"present": True, "value": val, **_verdict("pass", "Present.")}


def check_clickjacking(headers):
    xfo = headers.get("x-frame-options")
    csp = headers.get("content-security-policy", "")
    has_fa = "frame-ancestors" in csp.lower()
    if xfo or has_fa:
        src = "X-Frame-Options" if xfo else "CSP frame-ancestors"
        return {"x_frame_options": xfo, "csp_frame_ancestors": has_fa,
                **_verdict("pass", f"Clickjacking protection via {src}.")}
    return {"x_frame_options": None, "csp_frame_ancestors": False,
            **_verdict("fail", "No X-Frame-Options and no CSP frame-ancestors. Clickjacking exposure.")}


def check_csp(headers):
    val = headers.get("content-security-policy")
    if not val:
        return {"present": False, "value": None,
                **_verdict("warn", "No Content-Security-Policy. XSS mitigation is weaker.")}
    low = val.lower()
    weak = [t for t in ("unsafe-inline", "unsafe-eval") if t in low]
    if weak:
        return {"present": True, "value": val, "weak_directives": weak,
                **_verdict("warn", f"CSP present but weakened by {', '.join(weak)}.")}
    return {"present": True, "value": val, "weak_directives": [],
            **_verdict("pass", "Content-Security-Policy present.")}


def _parse_cookies(headers):
    raw = headers.get("set-cookie")
    if raw is None:
        return []
    cookies = raw if isinstance(raw, list) else [raw]
    parsed = []
    for c in cookies:
        low = c.lower()
        name = c.split("=", 1)[0].strip()
        same_site = None
        for part in low.split(";"):
            part = part.strip()
            if part.startswith("samesite="):
                same_site = part.split("=", 1)[1]
        parsed.append({
            "name": name,
            "secure": "secure" in low,
            "http_only": "httponly" in low,
            "same_site": same_site,
        })
    return parsed


def check_cookies(headers):
    cookies = _parse_cookies(headers)
    if not cookies:
        return {"count": 0, "cookies": [],
                **_verdict("info", "No cookies set on this response.")}
    insecure = [c["name"] for c in cookies if not c["secure"] or not c["http_only"]]
    if insecure:
        return {"count": len(cookies), "cookies": cookies, "insecure": insecure,
                **_verdict("warn", f"Cookies missing Secure/HttpOnly: {', '.join(insecure)}.")}
    return {"count": len(cookies), "cookies": cookies, "insecure": [],
            **_verdict("pass", "All cookies on this response carry Secure and HttpOnly.")}


def check_disclosure(headers):
    findings = {}
    for name in ("server", "x-powered-by", "x-aspnet-version", "x-generator"):
        val = headers.get(name)
        if val:
            has_version = any(ch.isdigit() for ch in val)
            findings[name] = {"value": val, "reveals_version": has_version}
    if not findings:
        return {"banners": {}, **_verdict("pass", "No version-revealing banners observed.")}
    versiony = [k for k, v in findings.items() if v["reveals_version"]]
    if versiony:
        return {"banners": findings,
                **_verdict("warn", f"Version banners present: {', '.join(versiony)}.")}
    return {"banners": findings, **_verdict("info", "Server banners present without versions.")}


def scan(url):
    url = common.normalize_url(url)
    host = common.host_of(url)
    res = common.http_fetch(url, want_body=False)
    headers = res.get("final_headers", {}) or {}

    checks = {
        "https_redirect": check_https_redirect(host),
        "hsts": check_hsts(headers),
        "content_security_policy": check_csp(headers),
        "clickjacking": check_clickjacking(headers),
        "x_content_type_options": check_simple_header(
            headers, "X-Content-Type-Options", "nosniff",
            "No X-Content-Type-Options. MIME sniffing possible."),
        "referrer_policy": check_simple_header(
            headers, "Referrer-Policy", None, "No Referrer-Policy set."),
        "permissions_policy": check_simple_header(
            headers, "Permissions-Policy", None, "No Permissions-Policy set."),
        "cookies": check_cookies(headers),
        "information_disclosure": check_disclosure(headers),
    }

    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c.get("verdict", "info")] = tally.get(c.get("verdict", "info"), 0) + 1

    return {
        "tool": "scan_http_security",
        "target": url,
        "host": host,
        "reachable": res["ok"],
        "fetch_error": res["error"],
        "final_url": res["final_url"],
        "final_status": res["final_status"],
        "summary": tally,
        "checks": checks,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_http_security.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
