#!/usr/bin/env python3
"""
Passive HTTP security-posture scanner.

Checks the HTTP-to-HTTPS redirect, the standard security response headers,
cookie flags, and version-disclosure banners. Every result is an observed fact
plus a defensible verdict (pass / warn / fail / info). No active probing.

Usage:
    python scan_http_security.py <url> [output.json]
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common

# Recommended HSTS floor: 180 days in seconds.
HSTS_MIN_AGE = 15552000

CATEGORY = "security"
SCOPE = "host"


def _verdict(status, note):
    return {"verdict": status, "note": note}


def check_https_redirect(host):
    """Fetch http://host and confirm it upgrades to https."""
    res = common.http_fetch(f"http://{host}", want_body=False)
    if not res["ok"] and not res["hops"]:
        return {"reachable_over_http": False, "detail": res["error"],
                **_verdict("info", "Host did not answer on plain HTTP.")}
    chain = [f'{h["status"]} {h["url"]}' for h in res["hops"]]
    if not res["ok"]:
        # A hop was recorded but the fetch did not complete: the last hop is a
        # 3xx whose target failed at connect, and final_url is the pre-redirect
        # http URL. Never grade a fail off that - if the redirect points at https
        # the upgrade is present, otherwise it could not be verified this run.
        last = res["hops"][-1]
        target = urljoin(last["url"], common.header_value(last["headers"], "location", ""))
        if urlparse(target).scheme == "https":
            return {"reachable_over_http": True, "redirect_chain": chain,
                    **_verdict("pass", "Plain HTTP redirects to HTTPS (the redirect "
                                       "target was not reachable this run).")}
        return {"reachable_over_http": True, "redirect_chain": chain,
                **_verdict("info", "Plain HTTP responded but the redirect could not "
                                   "be followed to verify an HTTPS upgrade.")}
    final_scheme = urlparse(res["final_url"]).scheme
    if final_scheme == "https":
        return {"reachable_over_http": True, "redirect_chain": chain, "final_url": res["final_url"],
                **_verdict("pass", "Plain HTTP redirects to HTTPS.")}
    return {"reachable_over_http": True, "redirect_chain": chain, "final_url": res["final_url"],
            **_verdict("fail", "Plain HTTP is served without a redirect to HTTPS.")}


def check_hsts(headers):
    val = common.header_value(headers, "strict-transport-security")
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


def check_simple_header(headers, name, expected=None, absent_note="Header missing.",
                        absent_verdict="fail"):
    # absent_verdict lets an optional header (one no major scorer penalizes, e.g.
    # Permissions-Policy) grade its absence as info rather than a hard fail, while
    # a genuinely expected header (X-Content-Type-Options) keeps the fail default.
    val = common.header_value(headers, name)
    if not val:
        return {"present": False, "value": None, **_verdict(absent_verdict, absent_note)}
    if expected and expected.lower() not in val.lower():
        return {"present": True, "value": val,
                **_verdict("warn", f"Present but expected to contain '{expected}'.")}
    return {"present": True, "value": val, **_verdict("pass", "Present.")}


def check_referrer_policy(headers):
    val = common.header_value(headers, "referrer-policy")
    if not val:
        return {"present": False, "value": None, **_verdict("fail", "No Referrer-Policy set.")}
    # A comma-separated value is a fallback list; the browser uses the last token it
    # supports, so grade the effective (last) one. Both unsafe-url and the legacy
    # default no-referrer-when-downgrade send the full URL (path and query) to
    # cross-origin destinations - the leak the modern strict-origin-* default fixed.
    effective = val.split(",")[-1].strip().lower()
    if effective in ("unsafe-url", "no-referrer-when-downgrade"):
        return {"present": True, "value": val,
                **_verdict("warn", f"Referrer-Policy {effective} leaks full URLs (path and query) "
                                   "to cross-origin destinations.")}
    return {"present": True, "value": val, **_verdict("pass", "Present.")}


def check_clickjacking(headers):
    xfo = common.header_value(headers, "x-frame-options")
    # Only DENY and SAMEORIGIN actually protect: ALLOW-FROM is deprecated and
    # ignored by Chrome/Edge/Safari, and any unknown value is ignored too, so
    # matching mere presence would pass a page that browsers leave framable.
    xfo_protects = (xfo or "").strip().lower() in ("deny", "sameorigin")
    # Repeated CSP headers are combined (every policy enforced), not last-wins,
    # so parse the raw value - which may be a list - via _parse_csp and match the
    # frame-ancestors directive by name rather than taking header_value's last.
    raw_csp = headers.get("content-security-policy")
    fa = _parse_csp(raw_csp).get("frame-ancestors") if raw_csp else None
    # frame-ancestors protects unless it allows every origin (a bare '*'); an
    # empty source list is 'none' (deny all), which protects.
    fa_protects = fa is not None and "*" not in fa
    if xfo_protects or fa_protects:
        src = "X-Frame-Options" if xfo_protects else "CSP frame-ancestors"
        return {"x_frame_options": xfo, "csp_frame_ancestors": fa_protects,
                **_verdict("pass", f"Clickjacking protection via {src}.")}
    if xfo or fa is not None:
        # A directive is present but ineffective, which is worse than absent: the
        # site looks protected but browsers still allow framing.
        return {"x_frame_options": xfo, "csp_frame_ancestors": fa is not None,
                **_verdict("fail", "Framing directive present but ineffective: X-Frame-Options "
                           "must be DENY or SAMEORIGIN (ALLOW-FROM and unknown values are ignored), "
                           "and CSP frame-ancestors must not allow all origins (*).")}
    return {"x_frame_options": None, "csp_frame_ancestors": False,
            **_verdict("fail", "No X-Frame-Options and no CSP frame-ancestors. Clickjacking exposure.")}


def _parse_csp(value):
    """Directive name -> source token list. Repeated headers arrive as a list
    and combine like a semicolon-joined policy; the first occurrence of a
    directive wins, per the CSP spec."""
    if isinstance(value, list):
        value = "; ".join(value)
    directives = {}
    for part in value.split(";"):
        tokens = part.strip().split()
        if tokens:
            directives.setdefault(tokens[0].lower(),
                                  [t.lower().strip("'") for t in tokens[1:]])
    return directives


def check_csp(headers):
    """Grade what the policy actually enforces for scripts, not just its
    presence: report-only delivery, a missing script/default directive,
    wildcard script origins, and unsafe-inline/eval in the directive that
    governs scripts (unsafe-inline in style-src alone is not a script hole)."""
    val = headers.get("content-security-policy")
    report_only = headers.get("content-security-policy-report-only")
    if not val:
        if report_only:
            return {"present": False, "report_only": True,
                    "value": report_only if isinstance(report_only, str) else "; ".join(report_only),
                    **_verdict("warn", "CSP is delivered Report-Only; the policy monitors but does not enforce.")}
        return {"present": False, "value": None,
                **_verdict("warn", "No Content-Security-Policy. XSS mitigation is weaker.")}

    directives = _parse_csp(val)
    script_directive = ("script-src" if "script-src" in directives
                        else "default-src" if "default-src" in directives else None)
    problems = []
    weak = []
    if script_directive is None:
        problems.append("no script-src and no default-src fallback, so scripts are unrestricted")
    else:
        sources = directives[script_directive]
        strict_dynamic = "strict-dynamic" in sources
        nonce_or_hash = any(s.startswith(("nonce-", "sha256-", "sha384-", "sha512-"))
                            for s in sources)
        # With 'strict-dynamic', supporting browsers ignore host/scheme allowlists
        # entirely (trust propagates through nonces/hashes), so a wildcard origin
        # is a legacy fallback, not an active hole.
        if not strict_dynamic:
            wild = [s for s in sources if s in ("*", "http:", "https:")]
            if wild:
                problems.append(f"{script_directive} allows any origin ({', '.join(wild)})")
        # 'unsafe-inline' is ignored when a nonce/hash or 'strict-dynamic' is present,
        # so only flag it otherwise. 'unsafe-eval' is unaffected by both and is always
        # a real weakness.
        weak = []
        if "unsafe-inline" in sources and not (strict_dynamic or nonce_or_hash):
            weak.append("unsafe-inline")
        if "unsafe-eval" in sources:
            weak.append("unsafe-eval")
        if weak:
            problems.append(f"{script_directive} permits {', '.join(weak)}")

    out = {"present": True,
           "value": val if isinstance(val, str) else "; ".join(val),
           "directives": sorted(directives),
           "script_directive": script_directive,
           "weak_directives": weak}
    if problems:
        return {**out, **_verdict("warn", "CSP present but weakened: " + "; ".join(problems) + ".")}
    return {**out, **_verdict("pass", "Content-Security-Policy restricts script sources.")}


def _parse_cookies(headers):
    raw = headers.get("set-cookie")
    if raw is None:
        return []
    cookies = raw if isinstance(raw, list) else [raw]
    parsed = []
    for c in cookies:
        name = c.split("=", 1)[0].strip()
        # Attributes are ;-delimited tokens after the name=value pair; match the
        # Secure/HttpOnly flags by whole token, not substring, so a cookie named
        # __Secure-* or a value containing "secure"/"httponly" is not miscredited
        # with a flag it lacks.
        attrs = [p.strip() for p in c.lower().split(";")[1:]]
        same_site = next((a.split("=", 1)[1] for a in attrs
                          if a.startswith("samesite=")), None)
        parsed.append({
            "name": name,
            "secure": "secure" in attrs,
            "http_only": "httponly" in attrs,
            "same_site": same_site,
        })
    return parsed


def check_cookies(headers):
    cookies = _parse_cookies(headers)
    if not cookies:
        return {"count": 0, "cookies": [],
                **_verdict("info", "No cookies set on this response.")}
    insecure = [c["name"] for c in cookies if not c["secure"] or not c["http_only"]]
    no_samesite = [c["name"] for c in cookies if c["same_site"] is None]
    if insecure:
        return {"count": len(cookies), "cookies": cookies, "insecure": insecure,
                "missing_samesite": no_samesite,
                **_verdict("warn", f"Cookies missing Secure/HttpOnly: {', '.join(insecure)}.")}
    if no_samesite:
        return {"count": len(cookies), "cookies": cookies, "insecure": [],
                "missing_samesite": no_samesite,
                **_verdict("warn", (f"Cookies without a SameSite attribute: {', '.join(no_samesite)}. "
                                    "Browsers default to Lax, but the CSRF intent is undeclared."))}
    return {"count": len(cookies), "cookies": cookies, "insecure": [], "missing_samesite": [],
            **_verdict("pass", "All cookies on this response carry Secure, HttpOnly, and SameSite.")}


def check_security_txt(base):
    """RFC 9116 vulnerability-disclosure file at a standardized well-known URI
    (like robots.txt, not path guessing). Absence is common, so it is reported
    as an observation, never graded down."""
    res = common.http_fetch(urljoin(base, "/.well-known/security.txt"), want_body=True)
    if res.get("final_status") is None:
        return {"present": None, "status": None,
                **_verdict("info", f"security.txt could not be fetched ({res.get('error')}); presence unknown.")}
    body = res.get("body") or ""
    if res["final_status"] == 200 and "contact:" in body.lower():
        return {"present": True, "status": 200,
                **_verdict("pass", "security.txt published at /.well-known/security.txt (RFC 9116).")}
    return {"present": False, "status": res["final_status"],
            **_verdict("info", "No security.txt (RFC 9116); publishing one gives researchers "
                               "a vulnerability-disclosure channel.")}


# A software version is a dotted numeric token (nginx/1.25.3, PHP/8.1.2, IIS/10.0),
# not any digit: a bare integer in a CDN node id (Akamai "ECAcc (nyd/D179)") or a
# build hash is not a version banner, so require at least two numeric components.
VERSION_RE = re.compile(r"\b\d+(?:\.\d+)+\b")


def check_disclosure(headers):
    findings = {}
    for name in ("server", "x-powered-by", "x-aspnet-version", "x-generator"):
        val = common.header_value(headers, name)
        if val:
            has_version = bool(VERSION_RE.search(val))
            findings[name] = {"value": val, "reveals_version": has_version}
    if not findings:
        return {"banners": {}, **_verdict("pass", "No version-revealing banners observed.")}
    versiony = [k for k, v in findings.items() if v["reveals_version"]]
    if versiony:
        return {"banners": findings,
                **_verdict("warn", f"Version banners present: {', '.join(versiony)}.")}
    return {"banners": findings, **_verdict("info", "Server banners present without versions.")}


def _scan(url):
    url = common.normalize_url(url)
    host = common.host_of(url)
    res = common.http_fetch(url, want_body=False)
    headers = res.get("final_headers", {}) or {}
    # http_fetch returns ok=True for any completed response, 4xx/5xx included
    # (their headers are real and gradable); ok=False means no response arrived.
    # When nothing arrived, an absent header is "not measured", never a
    # fabricated fail or a false "clean" pass on data we never saw.
    # https_redirect and security_txt make their own fetches and degrade on their
    # own, so only the header-derived checks are gated here.
    measured = res["ok"]

    def header_check(fn, *fn_args):
        if not measured:
            return _verdict("info", "Target did not respond to the HTTPS request; "
                                    "this header could not be measured.")
        return fn(*fn_args)

    checks = {
        "https_redirect": check_https_redirect(host),
        "hsts": header_check(check_hsts, headers),
        "content_security_policy": header_check(check_csp, headers),
        "clickjacking": header_check(check_clickjacking, headers),
        "x_content_type_options": header_check(
            check_simple_header, headers, "X-Content-Type-Options", "nosniff",
            "No X-Content-Type-Options. MIME sniffing possible."),
        "referrer_policy": header_check(check_referrer_policy, headers),
        "permissions_policy": header_check(
            check_simple_header, headers, "Permissions-Policy", None,
            "No Permissions-Policy set; an advanced, optional header that major "
            "scorers (Mozilla Observatory) do not penalize.", "info"),
        "cookies": header_check(check_cookies, headers),
        "information_disclosure": header_check(check_disclosure, headers),
        "security_txt": check_security_txt(res.get("final_url") or url),
    }

    tally = common.summarize(checks)

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


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    return common.finalize(result, CATEGORY)


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
