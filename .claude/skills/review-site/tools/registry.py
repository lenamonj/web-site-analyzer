#!/usr/bin/env python3
"""
Central registry of passive evaluation tools.

Single source of truth for tool discovery. The orchestrator (scan_site.py)
builds its host-scan set and its page-scanner list from these entries instead of
hardcoding them, so adding a dimension means adding one entry here plus the
scanner module and its tests, with no edit to the orchestrator. See PLAN.md
sections 4 and 5 for the shared tool contract and this registry design.

Each entry:
  tool_id  - stable id, matches the module's own "tool" field (e.g. scan_seo)
  key      - key the result is stored under in the combined scan JSON
  module   - the imported scanner module; must expose scan(...)
  scope    - read from module.SCOPE: "host" (scan(target)) or "page" (scan(url, page=None))
  category - read from module.CATEGORY: scorecard bucket the result rolls up into
  label    - short tag used in the flat issue list

scope and category live on the scanner module (self-describing tools), so this
registry only names the id, JSON key, and issue label for each tool.
"""

from collections import namedtuple

import scan_accessibility
import scan_crawl
import scan_dns_email
import scan_http_security
import scan_links
import scan_page_security
import scan_performance
import scan_privacy
import scan_readability
import scan_seo
import scan_tls

ToolEntry = namedtuple("ToolEntry", ["tool_id", "key", "module", "scope", "category", "label"])


def _entry(tool_id, key, module, label):
    """Build an entry, reading scope and category from the module itself."""
    return ToolEntry(tool_id, key, module, module.SCOPE, module.CATEGORY, label)


REGISTRY = [
    _entry("scan_http_security", "http_security", scan_http_security, "http_security"),
    _entry("scan_tls", "tls", scan_tls, "tls"),
    _entry("scan_dns_email", "dns_email", scan_dns_email, "dns_email"),
    _entry("scan_crawl", "crawl", scan_crawl, "crawl"),
    _entry("scan_seo", "seo", scan_seo, "seo"),
    _entry("scan_accessibility", "accessibility", scan_accessibility, "a11y"),
    _entry("scan_links", "links", scan_links, "links"),
    _entry("scan_performance", "performance", scan_performance, "perf"),
    _entry("scan_readability", "readability", scan_readability, "readability"),
    _entry("scan_privacy", "privacy", scan_privacy, "privacy"),
    _entry("scan_page_security", "page_security", scan_page_security, "pagesec"),
]


def host_tools():
    return [e for e in REGISTRY if e.scope == "host"]


def page_tools():
    return [e for e in REGISTRY if e.scope == "page"]


def by_id(tool_id):
    for e in REGISTRY:
        if e.tool_id == tool_id:
            return e
    return None
