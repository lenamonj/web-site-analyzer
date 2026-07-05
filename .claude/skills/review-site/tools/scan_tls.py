#!/usr/bin/env python3
"""
Passive TLS posture scanner.

Completes a normal TLS handshake and reports the negotiated protocol, the
certificate identity and validity window, days to expiry, and whether the
certificate actually covers the hostname. Optionally probes whether the server
still negotiates legacy TLS 1.0/1.1. A handshake is not an attack; nothing here
sends application data.

Usage:
    python scan_tls.py <host-or-url> [output.json]
"""

import calendar
import socket
import ssl
import sys
import time
import warnings

import common

EXPIRY_WARN_DAYS = 21

CATEGORY = "tls"
SCOPE = "host"


def _flatten_name(rdn_sequence):
    out = {}
    for rdn in rdn_sequence or ():
        for key, value in rdn:
            out[key] = value
    return out


def _host_matches(host, san_name):
    host = host.lower().rstrip(".")
    san = san_name.lower().rstrip(".")
    if san.startswith("*."):
        # A wildcard covers exactly one label to the left.
        return host.split(".", 1)[-1] == san[2:]
    return host == san


_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _parse_not_after(not_after):
    # Cert dates look like 'Aug 29 21:41:26 2026 GMT' and are UTC. OpenSSL always
    # emits English month names, so map them explicitly; strptime's %b reads the
    # process LC_TIME locale and raises on a non-English machine. split() also
    # collapses the double space OpenSSL uses to pad a single-digit day.
    mon, day, clock, year = not_after.split()[:4]
    hh, mm, ss = clock.split(":")
    struct = (int(year), _MONTHS[mon], int(day), int(hh), int(mm), int(ss), 0, 0, 0)
    epoch = calendar.timegm(struct)
    days_left = (epoch - time.time()) / 86400
    return epoch, round(days_left, 1)


def _probe_legacy(host, port=443, timeout=10):
    """Best-effort: does the server still negotiate TLS 1.0/1.1?"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            ctx.maximum_version = ssl.TLSVersion.TLSv1_1
    except (ValueError, AttributeError):
        return {"tested": False, "note": "Local OpenSSL will not offer TLS 1.0/1.1; cannot probe."}
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                return {"tested": True, "legacy_negotiated": True, "protocol": ss.version(),
                        "note": "Server negotiated a legacy TLS version. Disable TLS 1.0/1.1."}
    except Exception:
        return {"tested": True, "legacy_negotiated": False,
                "note": "Server refused legacy TLS 1.0/1.1 (or the local client blocked it)."}


def _restricts_issuance(record):
    """True if a CAA record actually restricts certificate issuance. Presentation
    format is "<flags> <tag> <value>"; only issue/issuewild restrict which CAs may
    issue. iodef (incident-reporting contact), contactemail/contactphone, and the
    like are present but restrict nothing, so a record set of only those still lets
    any public CA issue."""
    parts = record.split()
    tag = parts[1].lower() if len(parts) >= 2 else ""
    return tag in ("issue", "issuewild")


def check_caa(domain):
    """CAA record: which certificate authorities may issue for the domain.
    One passive DoH lookup; absence is common and reported as an observation."""
    res = common.doh_query(domain, "CAA")
    if not res["ok"]:
        return {"verdict": "info", "records": [],
                "note": f"CAA lookup failed ({res['error']}); issuance policy unknown."}
    records = [a for a in res["answers"] if a]
    restricting = [r for r in records if _restricts_issuance(r)]
    if restricting:
        return {"verdict": "pass", "records": records,
                "note": f"CAA restricts certificate issuance: {', '.join(restricting[:6])}."}
    if records:
        # CAA present but no issue/issuewild property (e.g. an iodef-only record),
        # so it does not restrict issuance: any public CA may still issue.
        return {"verdict": "info", "records": records,
                "note": ("CAA record present but no issue/issuewild property, so any public "
                         "CA may still issue; add an issue policy to restrict certificate issuance.")}
    return {"verdict": "info", "records": [],
            "note": "No CAA record; any public CA may issue certificates for this domain."}


def _scan(target):
    host = common.host_of(target) or target.strip()
    info = common.tls_info(host)
    if not info["ok"]:
        err = info["error"] or ""
        # An SSL/certificate error means the peer was reached but the TLS handshake
        # or cert validation genuinely failed - a real finding (fail). A connectivity
        # error (timeout, DNS gaierror, connection refused/reset, network unreachable)
        # means the handshake could not be measured at all, so grade it info -> Not
        # measured (surfaced as an errored scanner), matching how the header scanner
        # treats a non-response, rather than fabricate a Poor TLS posture from a
        # transient network hiccup. tls_info flattens the error to "<TypeName>: <msg>",
        # and every ssl error type name starts with SSL (or the older CertificateError).
        is_tls_error = err.startswith(("SSL", "Certificate"))
        return {
            "tool": "scan_tls", "host": host, "ok": False, "error": info["error"],
            "verdict": "fail" if is_tls_error else "info",
            "note": (f"TLS handshake failed: {err}" if is_tls_error
                     else f"TLS not measured: could not connect ({err})."),
        }

    cert = info["cert"] or {}
    subject = _flatten_name(cert.get("subject"))
    issuer = _flatten_name(cert.get("issuer"))
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    covered = any(_host_matches(host, s) for s in sans)

    not_after = cert.get("notAfter")
    expiry_epoch, days_left, expires_on = (None, None, None)
    expiry_verdict, expiry_note = "info", "Certificate expiry not reported by peer."
    if not_after:
        expiry_epoch, days_left = _parse_not_after(not_after)
        try:
            expires_on = time.strftime("%Y-%m-%d", time.gmtime(expiry_epoch))
        except (OSError, ValueError, OverflowError):
            # Windows time.gmtime raises OSError past ~year 3000; a pathological or
            # far-future notAfter must not abort the whole TLS scan. days_left is
            # plain arithmetic, so the verdict below still holds; only the
            # human-readable expiry date is dropped.
            expires_on = None
        if days_left < 0:
            expiry_verdict, expiry_note = "fail", f"Certificate expired {abs(days_left)} days ago."
        elif days_left < EXPIRY_WARN_DAYS:
            expiry_verdict, expiry_note = "warn", f"Certificate expires in {days_left} days."
        else:
            expiry_verdict, expiry_note = "pass", f"Certificate valid for {days_left} more days."

    protocol = info["protocol"]
    modern = protocol in ("TLSv1.3", "TLSv1.2")
    proto_verdict = "pass" if modern else "warn"
    proto_note = (f"Negotiated {protocol}." if modern
                  else f"Negotiated {protocol}, below TLS 1.2.")

    coverage_verdict = "pass" if covered else "fail"
    coverage_note = ("Certificate covers the hostname." if covered
                     else "Certificate SAN list does not cover this hostname.")

    alpn = info.get("alpn")
    if alpn == "h2":
        http2 = {"verdict": "pass", "alpn": alpn, "note": "HTTP/2 negotiated via ALPN."}
    else:
        http2 = {"verdict": "warn", "alpn": alpn,
                 "note": (f"Server negotiated {alpn or 'no ALPN protocol'}; requests "
                          "serialize over HTTP/1.1 without multiplexing.")}

    return {
        "tool": "scan_tls",
        "host": host,
        "ok": True,
        "error": None,
        "negotiated_protocol": protocol,
        "cipher": info["cipher"][0] if info["cipher"] else None,
        "issuer_org": issuer.get("organizationName") or issuer.get("commonName"),
        "subject_cn": subject.get("commonName"),
        "not_before": cert.get("notBefore"),
        "not_after": not_after,
        "expires_on": expires_on,
        "days_to_expiry": days_left,
        "san_dns": sans,
        "hostname_covered": covered,
        "legacy_probe": _probe_legacy(host),
        "checks": {
            "protocol": {"verdict": proto_verdict, "note": proto_note},
            "http2": http2,
            "expiry": {"verdict": expiry_verdict, "note": expiry_note},
            "hostname_coverage": {"verdict": coverage_verdict, "note": coverage_note},
            "caa": check_caa(common.registrable_domain(host)),
        },
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    return common.finalize(result, CATEGORY)


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_tls.py <host-or-url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
