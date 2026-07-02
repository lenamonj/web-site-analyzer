#!/usr/bin/env python3
"""
Offline unit tests for build_exec_report.py.

Builds a report from a synthetic data dict into a temp directory, reopens it
with python-docx, and asserts the document structure: masthead, glance tiles,
callout, chip fills, finding order, footer page field, and the evidence
appendix. Skipped entirely when python-docx is not installed (the scanners
must stay stdlib-only; only this builder depends on docx).

Run from this directory:
    python -m unittest test_exec_report
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from docx import Document
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False

if HAVE_DOCX:
    import build_exec_report as ber

SAMPLE = {
    "site": "example.com",
    "target_url": "https://example.com",
    "date": "2026-07-02",
    "bottom_line": "The site is sound overall; the one urgent item is consent.",
    "scorecard": {
        "overall": "Adequate",
        "rows": [
            {"category": "security", "band": "Poor", "detail": "1/1/6"},
            {"category": "seo", "band": "Strong", "detail": "9/1/0"},
        ],
    },
    "findings": [
        {"area": "SEO", "finding": "Low issue", "evidence": "scan.json", "severity": "Low"},
        {"area": "Security", "finding": "High issue", "evidence": "scan.json", "severity": "High"},
        {"area": "Privacy", "finding": "Critical issue", "evidence": "scan.json", "severity": "Critical"},
    ],
    "recommendations": [
        {"rank": 2, "recommendation": "Second", "impact": "B", "effort": "M"},
        {"rank": 1, "recommendation": "First", "impact": "A", "effort": "S"},
    ],
    "quick_wins": ["Fix titles", "Label the form"],
    "evidence": [
        {"caption": "Problem snippet", "code": "<img src=x>", "highlight": "src=x"},
        {"caption": "Missing shot", "image": "planning/_evidence/does_not_exist.png"},
    ],
}


def _cell_fill(cell):
    """The w:fill of a cell's shading, or None."""
    tc_pr = cell._tc.tcPr
    if tc_pr is None:
        return None
    shd = tc_pr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd")
    if shd is None:
        return None
    return shd.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill")


def _doc_text(document):
    parts = [p.text for p in document.paragraphs]
    for t in document.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    return "\n".join(parts)


@unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
class TestExecReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "report.docx"
        ber.build(SAMPLE, cls.out)
        cls.doc = Document(str(cls.out))
        cls.text = _doc_text(cls.doc)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_masthead_carries_site_and_kicker(self):
        self.assertIn("example.com", self.text)
        self.assertIn("WEBSITE REVIEW  /  EXECUTIVE REPORT", self.text)
        banner = self.doc.tables[0]
        self.assertEqual(_cell_fill(banner.rows[0].cells[0]), ber.ACCENT_HEX)

    def test_glance_tiles_report_counts_from_data(self):
        tiles = self.doc.tables[1]
        self.assertEqual(len(tiles.columns), 4)
        tile_text = "\n".join(p.text for c in tiles.rows[0].cells for p in c.paragraphs)
        self.assertIn("Adequate", tile_text)          # overall band
        self.assertIn("3", tile_text)                 # findings count
        self.assertIn("1 Critical / 1 High / 1 Low", tile_text)

    def test_bottom_line_renders_in_callout(self):
        self.assertIn(SAMPLE["bottom_line"], self.text)

    def test_scorecard_band_chips_use_band_fills(self):
        table = self._table_with_header("POSTURE")
        fills = [_cell_fill(row.cells[1]) for row in table.rows[1:]]
        self.assertEqual(fills, [ber.BAND_FILL["Poor"], ber.BAND_FILL["Strong"]])

    def test_findings_sorted_most_severe_first_with_chips(self):
        table = self._table_with_header("SEVERITY")
        sevs = [row.cells[0].text.strip() for row in table.rows[1:]]
        self.assertEqual(sevs, ["Critical", "High", "Low"])
        self.assertEqual(_cell_fill(table.rows[1].cells[0]), ber.SEVERITY_FILL["Critical"])

    def test_recommendations_sorted_by_rank(self):
        table = self._table_with_header("RECOMMENDATION")
        recs = [row.cells[1].text.strip() for row in table.rows[1:]]
        self.assertEqual(recs, ["First", "Second"])

    def test_footer_has_page_number_field(self):
        footer = self.doc.sections[0].footer
        xml = footer.paragraphs[0]._p.xml
        self.assertIn("PAGE", xml)
        self.assertIn("example.com Website Review", footer.paragraphs[0].text)

    def test_evidence_appendix_numbers_exhibits(self):
        self.assertIn("Exhibit 1.", self.text)
        self.assertIn("<img src=x>", self.text)
        self.assertIn("[missing image:", self.text)

    def test_minimal_data_builds_without_optional_sections(self):
        out = Path(self.tmp.name) / "minimal.docx"
        ber.build({"site": "bare.example"}, out)
        doc = Document(str(out))
        text = _doc_text(doc)
        self.assertIn("bare.example", text)
        # Only the masthead and glance tiles remain; every data-driven table
        # (scorecard, findings, recommendations) is skipped.
        self.assertEqual(len(doc.tables), 2)
        self.assertNotIn("BOTTOM LINE", text)

    def _table_with_header(self, header_text):
        """The table whose first-row cells include an exact header label.
        Exact match matters: the glance tiles carry labels like OVERALL
        POSTURE that would satisfy a substring lookup."""
        for table in self.doc.tables:
            if any(c.text.strip() == header_text for c in table.rows[0].cells):
                return table
        self.fail(f"No table with a header cell equal to {header_text!r}")


if __name__ == "__main__":
    unittest.main()
