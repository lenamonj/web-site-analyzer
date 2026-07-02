#!/usr/bin/env python3
"""
Polite, opt-in site crawler (PLAN.md section 29).

Breadth-first discovery of same-domain pages to widen a review beyond the
default sampled set. Strictly serial, one request per delay period (raised
to the robots.txt Crawl-delay when larger), robots.txt compliant via the
stdlib robotparser, bounded by a hard page ceiling, and resumable from a
state file written after every page. This is a discovery tool, not a
scanner: it grades nothing and is not registered. The authorization rules in
CLAUDE.md apply unchanged; crawling is only for sites you are authorized to
assess.

Usage:
    python crawler.py <url> [max_pages]
"""

import json
import sys
import time
import urllib.robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import common
import htmlmeta
import scan_dns_email as dns

DEFAULT_DELAY = 1.0          # seconds between requests; Crawl-delay can raise it
MAX_PAGES_CEILING = 500      # absolute cap regardless of the caller's ask
UA_TOKEN = "website-review-bot"
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "#", "data:")
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".avif",
    ".zip", ".gz", ".tar", ".rar", ".mp3", ".mp4", ".webm", ".mov", ".avi",
    ".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def _load_robots(base):
    rp = urllib.robotparser.RobotFileParser()
    res = common.http_fetch(urljoin(base, "/robots.txt"), want_body=True)
    if res.get("final_status") == 200 and res.get("body"):
        rp.parse(res["body"].splitlines())
    else:
        rp.parse([])  # no usable robots.txt: everything is allowed
    return rp


def _eligible(url, domain):
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return False
    if dns.registrable_domain(parts.hostname or "") != domain:
        return False
    path = parts.path.lower()
    return not any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


def _load_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def crawl(target, max_pages=100, delay=DEFAULT_DELAY, state_path=None,
          fresh=False, sleep=time.sleep):
    """Breadth-first same-domain crawl. Returns the collected page list and
    counters; persists resumable state after every page when state_path is
    given."""
    target = common.normalize_url(target)
    max_pages = min(max_pages, MAX_PAGES_CEILING)
    domain = dns.registrable_domain(common.host_of(target))

    state = {"target": target, "visited": [], "queue": [target],
             "collected": [], "skipped_by_robots": 0, "errors": 0}
    if state_path and not fresh:
        loaded = _load_state(state_path)
        if loaded and loaded.get("target") == target:
            state = loaded

    rp = _load_robots(target)
    crawl_delay = rp.crawl_delay(UA_TOKEN) or rp.crawl_delay("*") or 0
    wait = max(delay, float(crawl_delay))

    visited = set(state["visited"])
    queue = [u for u in state["queue"] if u not in visited]
    queued = set(queue)

    while queue and len(state["collected"]) < max_pages:
        url = queue.pop(0)
        queued.discard(url)
        visited.add(url)

        if not rp.can_fetch(UA_TOKEN, url):
            state["skipped_by_robots"] += 1
        else:
            page = htmlmeta.fetch_page(url)
            res = page["res"]
            if not res["ok"] and not res.get("body"):
                state["errors"] += 1
            else:
                state["collected"].append(url)
                base = res.get("final_url") or url
                for a in page["parsed"]["anchors"]:
                    href = (a.get("href") or "").strip()
                    if not href or href.lower().startswith(SKIP_SCHEMES):
                        continue
                    absolute = urldefrag(urljoin(base, href))[0]
                    if _eligible(absolute, domain) and absolute not in visited \
                            and absolute not in queued:
                        queue.append(absolute)
                        queued.add(absolute)
            if queue and len(state["collected"]) < max_pages:
                sleep(wait)

        state["visited"] = sorted(visited)
        state["queue"] = queue
        if state_path:
            common.write_json(state_path, state)

    return {
        "tool": "crawler",
        "target": target,
        "domain": domain,
        "pages": list(state["collected"]),
        "stats": {"collected": len(state["collected"]),
                  "visited": len(visited),
                  "frontier_remaining": len(queue),
                  "skipped_by_robots": state["skipped_by_robots"],
                  "errors": state["errors"],
                  "delay_seconds": wait},
    }


def main():
    common.enable_utf8_stdout()
    args = sys.argv[1:]
    if not args:
        print("Usage: python crawler.py <url> [max_pages]")
        sys.exit(1)
    target = args[0]
    max_pages = int(args[1]) if len(args) > 1 else 100
    state_path = common.evidence_dir() / f"{common.slug_of(target)}_crawl_state.json"
    result = crawl(target, max_pages=max_pages, state_path=state_path)
    print(f"Collected {result['stats']['collected']} page(s) from {result['domain']} "
          f"(visited {result['stats']['visited']}, "
          f"robots-skipped {result['stats']['skipped_by_robots']}, "
          f"frontier remaining {result['stats']['frontier_remaining']}).")
    for u in result["pages"]:
        print(f"  {u}")


if __name__ == "__main__":
    main()
