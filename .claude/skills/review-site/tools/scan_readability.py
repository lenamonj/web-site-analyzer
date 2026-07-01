#!/usr/bin/env python3
"""
Content readability scanner.

Computes standard, deterministic readability metrics on the page's visible text:
Flesch Reading Ease, Flesch-Kincaid grade level, and average sentence length.
These are approximations (sentence and syllable counting are heuristic), so the
output labels them as such. Client-rendered pages have no static body text, so
the scanner reports inconclusive rather than scoring an empty string.

Usage:
    python scan_readability.py <url> [output.json]
"""

import re
import sys
from html.parser import HTMLParser

import common
import htmlmeta

SKIP_TAGS = {"script", "style", "noscript", "template"}
MIN_WORDS = 100          # below this, readability metrics are not meaningful
LONG_SENTENCE_WORDS = 25

CATEGORY = "readability"
SCOPE = "page"


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buf = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in SKIP_TAGS and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            self.buf.append(data)


def _visible_text(html):
    p = _TextExtractor()
    try:
        p.feed(html or "")
    except Exception:
        pass
    return re.sub(r"\s+", " ", " ".join(p.buf)).strip()


def _syllables(word):
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups)
    if word.endswith("e") and not word.endswith("le"):
        n -= 1  # rough silent-e correction, but keep "le" endings (table, simple)
    return max(1, n)


def _sentences(text):
    parts = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    return parts


def _scan(url, page=None):
    url = common.normalize_url(url)
    if page is None:
        page = htmlmeta.fetch_page(url)
    res, parsed, render = page["res"], page["parsed"], page["render"]
    if not res["ok"] and not res["body"]:
        return {"tool": "scan_readability", "target": url, "ok": False, "error": res["error"]}

    html = res["body"] or ""
    text = _visible_text(html)
    words = re.findall(r"[A-Za-z']+", text)
    sentences = _sentences(text)
    word_count, sentence_count = len(words), len(sentences)

    if render["likely_client_rendered"] or word_count < MIN_WORDS:
        why = ("page is client-rendered" if render["likely_client_rendered"]
               else f"only {word_count} words of static text")
        return {
            "tool": "scan_readability", "target": url, "final_url": res["final_url"], "ok": True,
            "render": render, "word_count": word_count,
            "checks": {"readability": {"verdict": "info",
                       "note": f"Not assessable ({why}). Capture the rendered page for real content."}},
        }

    syllables = sum(_syllables(w) for w in words)
    wps = word_count / sentence_count
    spw = syllables / word_count
    flesch = round(206.835 - 1.015 * wps - 84.6 * spw, 1)
    fk_grade = round(0.39 * wps + 11.8 * spw - 15.59, 1)
    long_sentences = sorted(sentences, key=lambda s: len(s.split()), reverse=True)[:3]

    if flesch >= 50:
        rv, rnote = "pass", f"Flesch Reading Ease {flesch} (fairly readable)."
    elif flesch >= 30:
        rv, rnote = "warn", f"Flesch Reading Ease {flesch} (difficult; dense for a public site)."
    else:
        rv, rnote = "fail", f"Flesch Reading Ease {flesch} (very difficult, graduate-level density)."

    sv = "warn" if wps > LONG_SENTENCE_WORDS else "pass"
    snote = (f"Average sentence length {round(wps, 1)} words"
             + (" (long; over 25 hurts comprehension)." if wps > LONG_SENTENCE_WORDS else "."))

    checks = {
        "reading_ease": {"flesch_reading_ease": flesch, "fk_grade_level": fk_grade,
                         "verdict": rv, "note": rnote},
        "sentence_length": {"avg_words_per_sentence": round(wps, 1),
                            "longest_examples": [s[:160] for s in long_sentences],
                            "verdict": sv, "note": snote},
    }
    tally = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks.values():
        tally[c["verdict"]] = tally.get(c["verdict"], 0) + 1

    return {
        "tool": "scan_readability",
        "target": url,
        "final_url": res["final_url"],
        "ok": True,
        "render": render,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "note": "Sentence and syllable counts are heuristic approximations.",
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
        print("Usage: python scan_readability.py <url> [output.json]")
        sys.exit(1)
    result = scan(sys.argv[1])
    if len(sys.argv) >= 3:
        common.write_json(sys.argv[2], result)
        print(f"Wrote {sys.argv[2]}")
    else:
        common.print_json(result)


if __name__ == "__main__":
    main()
