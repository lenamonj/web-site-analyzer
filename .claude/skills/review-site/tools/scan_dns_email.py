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

import datetime
import sys
from concurrent.futures import ThreadPoolExecutor

import common

# Common DKIM selectors across major providers: provider-name selectors plus
# the documented date-based and key-size families large providers rotate
# (Google 20230601-style, Yahoo s2048, Fastmail fm1-3, Proton, Zoho). Only
# published selector names; random per-account selectors (for example Amazon
# SES tokens) are unguessable by design. Absence here is not proof.
DKIM_SELECTORS = [
    "selector1", "selector2", "google", "default", "k1", "k2",
    "mail", "dkim", "s1", "s2", "mandrill", "mxvault", "dkim1", "smtp",
    "20230601", "20161025", "20120113", "s1024", "s2048",
    "fm1", "fm2", "fm3", "protonmail", "protonmail2", "protonmail3", "zoho",
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
    def probe(sel):
        records, _ = _txt_records(f"{sel}._domainkey.{domain}")
        return any("dkim1" in r.lower() or "k=rsa" in r.lower() or "p=" in r.lower()
                   for r in records)

    # Bounded fan-out over the selector list (14 serial DoH round trips
    # otherwise); executor.map preserves order so output stays deterministic.
    with ThreadPoolExecutor(max_workers=8) as pool:
        hits = list(pool.map(probe, DKIM_SELECTORS))
    found = [sel for sel, hit in zip(DKIM_SELECTORS, hits) if hit]
    if found:
        return {"selectors_found": found, "selectors_probed": DKIM_SELECTORS,
                "verdict": "pass", "note": f"DKIM key published for selector(s): {', '.join(found)}."}
    return {"selectors_found": [], "selectors_probed": DKIM_SELECTORS,
            "verdict": "info",
            "note": (f"No DKIM key on the {len(DKIM_SELECTORS)} probed selectors (provider names "
                     "plus Google/Yahoo/Fastmail/Proton/Zoho families). Random per-account "
                     "selectors cannot be probed, so absence is not proof.")}


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


def check_mta_sts(domain, has_mx):
    """MTA-STS (RFC 8461): protects inbound SMTP from TLS downgrade. Record
    in DNS plus a policy file at a standardized well-known URI. Absence is
    reported, not graded down (adoption is minority)."""
    if not has_mx:
        return {"verdict": "info", "note": "Domain has no MX records; MTA-STS not applicable."}
    records, _ = _txt_records(f"_mta-sts.{domain}")
    rec = next((r for r in records if r.lower().startswith("v=stsv1")), None)
    if not rec:
        return {"present": False, "verdict": "info",
                "note": "No MTA-STS record; SMTP delivery to this domain accepts silent TLS downgrade."}
    res = common.http_fetch(f"https://mta-sts.{domain}/.well-known/mta-sts.txt", want_body=True)
    body = res.get("body") or ""
    if res.get("final_status") != 200 or "version" not in body.lower():
        return {"present": True, "policy_reachable": False, "verdict": "info",
                "note": "MTA-STS record published but the policy file at mta-sts."
                        f"{domain} is not readable, so the policy cannot take effect."}
    mode = None
    for line in body.splitlines():
        if line.lower().strip().startswith("mode:"):
            mode = line.split(":", 1)[1].strip().lower()
    if mode == "enforce":
        return {"present": True, "policy_reachable": True, "mode": mode, "verdict": "pass",
                "note": "MTA-STS enforced (record plus policy in enforce mode)."}
    return {"present": True, "policy_reachable": True, "mode": mode, "verdict": "info",
            "note": f"MTA-STS present but the policy mode is {mode or 'unspecified'}, not enforce."}


def check_tls_rpt(domain, has_mx):
    """TLS-RPT (RFC 8460): where SMTP TLS failures get reported."""
    if not has_mx:
        return {"verdict": "info", "note": "Domain has no MX records; TLS-RPT not applicable."}
    records, _ = _txt_records(f"_smtp._tls.{domain}")
    rec = next((r for r in records if r.lower().startswith("v=tlsrptv1")), None)
    if rec:
        return {"present": True, "record": rec, "verdict": "pass",
                "note": "TLS-RPT record published; SMTP TLS failures are reported."}
    return {"present": False, "verdict": "info",
            "note": "No TLS-RPT record; SMTP TLS failures go unreported."}


def check_bimi(domain, has_mx):
    """BIMI: brand logo shown next to authenticated mail. Cosmetic but a
    signal of mature email posture; requires DMARC enforcement to work."""
    if not has_mx:
        return {"verdict": "info", "note": "Domain has no MX records; BIMI not applicable."}
    records, _ = _txt_records(f"default._bimi.{domain}")
    rec = next((r for r in records if r.lower().startswith("v=bimi1")), None)
    if rec:
        has_logo = "l=" in rec.lower()
        return {"present": True, "record": rec, "verdict": "pass",
                "note": "BIMI record published" + (" with a logo URL." if has_logo else " (no logo URL).")}
    return {"present": False, "verdict": "info", "note": "No BIMI record."}


def iso_days(iso):
    """(days_from_now, YYYY-MM-DD) for an ISO-8601 timestamp, or (None, None).
    Pure, so it is unit tested offline."""
    if not iso:
        return None, None
    try:
        s = iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        days = round((dt - now).total_seconds() / 86400, 1)
        return days, dt.date().isoformat()
    except (ValueError, TypeError):
        return None, None


def check_domain_registration(domain):
    """Public registration facts as conversation-starter info, never scored
    (info verdicts are not graded, so the email-auth band is untouched): when
    the domain registration expires and when it was first registered. RDAP is
    the public JSON successor to WHOIS; unsupported TLDs degrade to info."""
    rd = common.rdap_domain(domain)
    if not rd.get("ok"):
        return {"domain_expiry": {"verdict": "info", "date": None,
                                  "days_to_expiry": None,
                                  "note": f"Domain registration lookup unavailable "
                                          f"({rd.get('error', 'no RDAP data')})."}}
    exp_days, exp_date = iso_days(rd.get("expiration"))
    reg_days, reg_date = iso_days(rd.get("registration"))
    checks = {}
    if exp_date and exp_days is not None and exp_days < 0:
        note = f"Domain registration expired on {exp_date}."
    elif exp_date and exp_days is not None:
        note = f"Domain registration expires {exp_date} ({exp_days:.0f} days away)."
    elif exp_date:
        note = f"Domain registration expires {exp_date}."
    else:
        note = "Domain expiry date not published by the registry."
    checks["domain_expiry"] = {"verdict": "info", "date": exp_date,
                               "days_to_expiry": exp_days, "note": note}
    if reg_date:
        years = round(abs(reg_days) / 365.25, 1) if reg_days is not None else None
        rnote = (f"Domain first registered {reg_date}"
                 + (f" (about {years} years ago)." if years else "."))
        checks["domain_created"] = {"verdict": "info", "date": reg_date,
                                    "age_years": years, "note": rnote}
    return checks


def _scan(target):
    host = common.host_of(target) or target.strip()
    domain = registrable_domain(host)
    mx = check_mx(domain)
    has_mx = bool(mx["records"])
    checks = {
        "spf": check_spf(domain),
        "dmarc": check_dmarc(domain),
        "dkim": check_dkim(domain),
        "mx": mx,
        "dnssec": check_dnssec(domain),
        "mta_sts": check_mta_sts(domain, has_mx),
        "tls_rpt": check_tls_rpt(domain, has_mx),
        "bimi": check_bimi(domain, has_mx),
    }
    checks.update(check_domain_registration(domain))
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
    """Public entry: run the scan and stamp the tool's own category and grade so
    the result is self-describing (see PLAN.md section 4)."""
    result = _scan(*args, **kwargs)
    result["category"] = CATEGORY
    result["grade"] = common.grade(common.verdicts_of(result))
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
