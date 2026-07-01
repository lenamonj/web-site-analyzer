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
  scope    - "host" (scan(target)) or "page" (scan(url, page=None))
  category - scorecard bucket the result rolls up into
  label    - short tag used in the flat issue list
"""

from collections import namedtuple

import scan_accessibility
import scan_dns_email
import scan_http_security
import scan_links
import scan_performance
import scan_readability
import scan_seo
import scan_tls

ToolEntry = namedtuple("ToolEntry", ["tool_id", "key", "module", "scope", "category", "label"])

REGISTRY = [
    ToolEntry("scan_http_security", "http_security", scan_http_security, "host", "security", "http_security"),
    ToolEntry("scan_tls", "tls", scan_tls, "host", "tls", "tls"),
    ToolEntry("scan_dns_email", "dns_email", scan_dns_email, "host", "dns_email", "dns_email"),
    ToolEntry("scan_seo", "seo", scan_seo, "page", "seo", "seo"),
    ToolEntry("scan_accessibility", "accessibility", scan_accessibility, "page", "accessibility", "a11y"),
    ToolEntry("scan_links", "links", scan_links, "page", "links", "links"),
    ToolEntry("scan_performance", "performance", scan_performance, "page", "performance", "perf"),
    ToolEntry("scan_readability", "readability", scan_readability, "page", "readability", "readability"),
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
