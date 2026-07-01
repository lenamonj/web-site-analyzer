#!/usr/bin/env python3
"""
Passive email-authentication and DNS posture scanner.

Uses DNS-over-HTTPS so it needs no local resolver library and works the same on
any platform. Reads public records only: SPF, DMARC, DKIM (common selectors),
MX, and DNSSEC signing. DKIM absence is reported as "not found on probed
selectors", never as a hard negative, because selectors are provider specific.

Usage:
    python scan_dns_email.py <domain-or-url> [output.json]
"""

import sys

import common

# Common DKIM selectors across major providers. Absence here is not proof.
DKIM_SELECTORS = [
    "selector1", "selector2", "google", "default", "k1", "k2",
    "mail", "dkim", "s1", "s2", "mandrill", "mxvault", "dkim1", "smtp",
]

# Minimal multi-label public suffixes so registrable-domain guessing is sane.
MULTI_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au", "org.au",
    "co.jp", "co.nz", "co.za", "com.br", "com.cn", "com.mx",
}

CATEGORY = "dns_email"
SCOPE = "host"


def registrable_domain(host):
    """Best-effort organizational domain (no Public Suffix List dependency)."""
    labels = host.strip(".").split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _txt_records(name):
    res = common.doh_query(name, "TXT")
    # DoH returns TXT data wrapped in quotes; strip them and join split strings.
    cleaned = []
    for a in res["answers"]:
        cleaned.append(a.replace('" "', "").strip('"'))
    return cleaned, res


def check_spf(domain):
    records, _ = _txt_records(domain)
    spf = next((r for r in records if r.lower().startswith("v=spf1")), None)
    if not spf:
        return {"present": False, "record": None,
                "verdict": "fail", "note": "No SPF record. Sender spoofing is easier."}
    low = spf.lower()
    if "-all" in low:
        v, note = "pass", "SPF ends in -all (hard fail)."
    elif "~all" in low:
        v, note = "pass", "SPF ends in ~all (soft fail)."
    elif "?all" in low or "+all" in low:
        v, note = "warn", "SPF present but the 'all' qualifier is permissive."
    else:
        v, note = "warn", "SPF present but has no explicit 'all' mechanism."
    return {"present": True, "record": spf, "verdict": v, "note": note}


def check_dmarc(domain):
    records, _ = _txt_records(f"_dmarc.{domain}")
    dmarc = next((r for r in records if r.lower().startswith("v=dmarc1")), None)
    if not dmarc:
        return {"present": False, "record": None,
                "verdict": "fail", "note": "No DMARC record. No policy for spoofed mail."}
    policy = None
    for part in dmarc.split(";"):
        part = part.strip().lower()
        if part.startswith("p="):
            policy = part.split("=", 1)[1]
    has_rua = "rua=" in dmarc.lower()
    if policy == "reject":
        v, note = "pass", "DMARC policy is reject."
    elif policy == "quarantine":
        v, note = "pass", "DMARC policy is quarantine."
    else:
        v, note = "warn", f"DMARC policy is p={policy or 'none'} (monitor only)."
    return {"present": True, "record": dmarc, "policy": policy,
            "aggregate_reports": has_rua, "verdict": v, "note": note}


def check_dkim(domain):
    found = []
    for sel in DKIM_SELECTORS:
        records, _ = _txt_records(f"{sel}._domainkey.{domain}")
        if any("dkim1" in r.lower() or "k=rsa" in r.lower() or "p=" in r.lower() for r in records):
            found.append(sel)
    if found:
        return {"selectors_found": found, "selectors_probed": DKIM_SELECTORS,
                "verdict": "pass", "note": f"DKIM key published for selector(s): {', '.join(found)}."}
    return {"selectors_found": [], "selectors_probed": DKIM_SELECTORS,
            "verdict": "info",
            "note": "No DKIM key on the probed selectors. Provider-specific selectors may still exist."}


def check_mx(domain):
    res = common.doh_query(domain, "MX")
    hosts = [a.split()[-1].rstrip(".") for a in res["answers"] if a]
    if hosts:
        return {"records": hosts, "verdict": "info", "note": f"{len(hosts)} MX host(s)."}
    return {"records": [], "verdict": "info", "note": "No MX records; domain does not receive mail here."}


def check_dnssec(domain):
    res = common.doh_query(domain, "DNSKEY")
    if res["answers"]:
        return {"signed": True, "verdict": "pass", "note": "DNSSEC keys published (zone is signed)."}
    return {"signed": False, "verdict": "info", "note": "No DNSKEY; zone is not DNSSEC-signed."}


def _scan(target):
    host = common.host_of(target) or target.strip()
    domain = registrable_domain(host)
    checks = {
        "spf": check_spf(domain),
        "dmarc": check_dmarc(domain),
        "dkim": check_dkim(domain),
        "mx": check_mx(domain),
        "dnssec": check_dnssec(domain),
    }
    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1
    return {
        "tool": "scan_dns_email",
        "host": host,
        "domain_checked": domain,
        "resolver": "dns.google (DoH)",
        "summary": tally,
        "checks": checks,
    }


def scan(*args, **kwargs):
    """Public entry: run the scan and stamp the tool's own category so the
    result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    result["category"] = CATEGORY
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_dns_email.py <domain-or-url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
