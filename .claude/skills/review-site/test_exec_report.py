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
    "scope": {"pages_reviewed": 12, "method": "Passive external scan"},
    "progress": {"previous_date": "2026-06-01", "new_issues": 1, "resolved_issues": 4},
    "web_vitals": {"source": "field", "captured_note": "Real Chrome users, 28-day p75 (CrUX)",
                   "metrics": [{"label": "LCP", "value": "0.9s", "rating": "Good"},
                               {"label": "CLS", "value": "0.31", "rating": "Poor"},
                               {"label": "INP", "value": "350ms", "rating": "Needs work"}]},
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


def _cell_fill_of_run(cell):
    """The w:shd fill on any run inside a cell (the vitals rating chip), or None."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for r in cell._tc.iter(f"{ns}r"):
        shd = r.find(f"{ns}rPr/{ns}shd")
        if shd is not None:
            return shd.get(f"{ns}fill")
    return None


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
        # With scope present the fourth tile shows pages reviewed.
        self.assertIn("PAGES REVIEWED", tile_text)
        self.assertIn("12", tile_text)

    def test_scope_line_and_progress_strip(self):
        self.assertIn("12 page(s) reviewed  |  Passive external scan", self.text)
        self.assertIn("Since the previous review (2026-06-01):", self.text)
        self.assertIn("4 resolved", self.text)
        self.assertIn("1 new", self.text)

    def test_web_vitals_panel_renders_values_and_source(self):
        self.assertIn("CORE WEB VITALS", self.text)  # section headings render uppercase
        self.assertIn("0.9s", self.text)
        self.assertIn("350ms", self.text)
        self.assertIn("Real Chrome users, 28-day p75 (CrUX)", self.text)
        # The rating chips carry the vitals fill colors.
        panel = next(t for t in self.doc.tables
                     if any("0.9s" in c.text for c in t.rows[0].cells))
        chip_fills = {_cell_fill_of_run(c) for c in panel.rows[0].cells}
        self.assertIn(ber.VITALS_FILL["Good"], chip_fills)
        self.assertIn(ber.VITALS_FILL["Poor"], chip_fills)

    def test_section_headings_keep_with_next(self):
        heading = next(p for p in self.doc.paragraphs if p.text == "BOTTOM LINE")
        self.assertTrue(heading.paragraph_format.keep_with_next)

    def test_image_exhibit_renders_in_a_framed_cell(self):
        png_1x1 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
                   b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc"
                   b"\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        img_path = Path(self.tmp.name) / "shot.png"
        img_path.write_bytes(png_1x1)
        data = dict(SAMPLE)
        data["evidence"] = [{"caption": "Screenshot", "image": str(img_path)}]
        out = Path(self.tmp.name) / "framed.docx"
        ber.build(data, out)
        doc = Document(str(out))
        # The last table is the frame; it must contain exactly one drawing.
        frame_xml = doc.tables[-1]._tbl.xml
        self.assertIn("<pic:pic", frame_xml)

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
