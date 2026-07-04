#!/usr/bin/env python3
"""Guard against README test-count drift (BACKLOG L11).

Counts the test cases in both suites (without running them) and checks that
README.md cites the same numbers in its badge, summary line, per-suite command
comments, and file-tree annotation. Exits non-zero on any mismatch so CI fails
the moment a test is added or removed without the README being updated - the
exact drift that made L7 necessary.

Run from anywhere: paths are resolved from this file's location.
"""
import importlib
import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent          # .../review-site/tools
REVIEW = TOOLS.parent                             # .../review-site
ROOT = REVIEW.parents[2]                          # repo root
README = ROOT / "README.md"


def count_tests(module_dir, module_name):
    """Number of test cases in a module, loaded (not run) from its directory."""
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
    module = importlib.import_module(module_name)
    return unittest.TestLoader().loadTestsFromModule(module).countTestCases()


def readme_mismatches(text, scanner, builder, scanners, categories):
    """Which documented counts in the README text disagree with the measured
    values. Pure (no IO), so the CI gate has unit coverage. Returns a list of
    human-readable mismatch strings; an empty list means everything is in sync.
    """
    total = scanner + builder
    expected = {
        "badge": f"tests-{total}%20passing",
        "summary line": f"{total} tests total",
        "scanner suite comment": f"# {scanner} tests",
        "builder suite comment": f"# {builder} tests",
        "file-tree annotation": f"({scanner} tests)",
        "registered-scanner count (line 17)": f"{scanners} registered scanners",
        "scorecard-category count (line 17)": f"{categories} scorecard categories",
    }
    return [f"{where}: expected '{needle}' not found in README"
            for where, needle in expected.items() if needle not in text]


def fixed_readme(text, scanner, builder, scanners, categories):
    """Rewrite the documented counts in the README text to the measured values,
    the write-side of readme_mismatches so a contributor runs one command instead
    of hand-editing every site. Pure (no IO) and idempotent: each site is matched
    by pattern and only its number replaced, so an already-correct README returns
    unchanged. The scanner and builder suite comments are disambiguated by the
    test module named earlier on their line. A site the README does not contain
    is left as-is; --fix corrects drifted numbers, it does not restructure the
    file.
    """
    total = scanner + builder
    subs = [
        (r"tests-\d+%20passing", f"tests-{total}%20passing"),
        (r"\d+ tests total", f"{total} tests total"),
        (r"(test_review_tools[^\n#]*#\s*)\d+(\s+tests)", rf"\g<1>{scanner}\g<2>"),
        (r"(test_exec_report[^\n#]*#\s*)\d+(\s+tests)", rf"\g<1>{builder}\g<2>"),
        (r"\(\d+ tests\)", f"({scanner} tests)"),
        (r"\d+ registered scanners", f"{scanners} registered scanners"),
        (r"\d+ scorecard categories", f"{categories} scorecard categories"),
    ]
    for pattern, repl in subs:
        text = re.sub(pattern, repl, text)
    return text


def main():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    import registry
    scanner = count_tests(TOOLS, "test_review_tools")
    builder = count_tests(REVIEW, "test_exec_report")
    total = scanner + builder
    tools = registry.host_tools() + registry.page_tools()
    scanners = len(tools)
    categories = len({t.category for t in tools})

    text = README.read_text(encoding="utf-8")

    if "--fix" in sys.argv[1:]:
        fixed = fixed_readme(text, scanner, builder, scanners, categories)
        if fixed != text:
            README.write_text(fixed, encoding="utf-8")
            print(f"README counts rewritten: scanner {scanner}, builder {builder}, "
                  f"total {total}; {scanners} scanners, {categories} categories.")
        else:
            print("README counts already in sync; nothing to rewrite.")
        return 0

    problems = readme_mismatches(text, scanner, builder, scanners, categories)

    if problems:
        print("README count drift detected:")
        for p in problems:
            print("  -", p)
        print(f"Actual: scanner {scanner}, builder {builder}, total {total}; "
              f"{scanners} scanners, {categories} categories.")
        print("Update README.md to match (test counts: BACKLOG L7 sites; "
              "registry counts: line 17).")
        return 1
    print(f"README counts in sync: scanner {scanner}, builder {builder}, "
          f"total {total}; {scanners} scanners, {categories} categories.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
