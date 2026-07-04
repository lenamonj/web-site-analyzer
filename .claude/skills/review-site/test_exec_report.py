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

try:
    import report_charts
    HAVE_MPL = report_charts.HAVE_MPL
except ImportError:
    HAVE_MPL = False

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
    "key_dates": {"note": "Public certificate and domain-registration facts, passively measured.",
                  "items": [{"label": "SSL certificate renews", "value": "2026-09-10",
                             "detail": "in 70 days"},
                            {"label": "Domain renews", "value": "2027-04-02",
                             "detail": "in 640 days"},
                            {"label": "Domain registered", "value": "2015-04-02",
                             "detail": "about 11.0 years ago"}]},
    "bottom_line": "The site is sound overall; the one urgent item is consent.",
    "assessment": {
        "strengths": ["TLS and certificates: strong (4 checks pass)"],
        "weaknesses": ["Security posture: poor (6 failing, 1 warnings). Worst: No HSTS."],
    },
    "action_plan": [
        {"priority": "High", "action": "Add an HSTS response header", "affects": "site-wide"},
        {"priority": "Medium", "action": "Right-size page titles", "affects": "2 page(s)"},
    ],
    "scorecard": {
        "overall": "Adequate",
        "rows": [
            {"category": "security", "band": "Poor", "detail": "1/1/6", "score": 0.28},
            {"category": "seo", "band": "Strong", "detail": "9/1/0", "score": 1.0},
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

    def test_cover_carries_site_kicker_and_posture(self):
        self.assertIn("example.com", self.text)
        self.assertIn("WEBSITE REVIEW  /  EXECUTIVE REPORT", self.text)
        # The measured overall posture appears on the cover as an uppercase chip.
        self.assertIn("OVERALL POSTURE", self.text)
        self.assertIn("ADEQUATE", self.text)
        # The cover ends with a page break so content starts on its own page.
        body_xml = self.doc.element.body.xml
        self.assertIn('w:br w:type="page"', body_xml)

    def test_cover_contents_list_names_rendered_sections_in_order(self):
        self.assertIn("IN THIS REPORT", self.text)
        idx = self.text.index("IN THIS REPORT")
        listing = self.text[idx:idx + 600]
        for name in ("Executive summary", "Measured posture", "Core Web Vitals",
                     "Key dates", "Key findings hurting the site",
                     "Preferred recommendations", "Quick wins", "Evidence appendix"):
            self.assertIn(name, listing)

    def test_running_header_skips_the_cover(self):
        section = self.doc.sections[0]
        self.assertTrue(section.different_first_page_header_footer)
        self.assertIn("example.com   |   Website Review   |   2026-07-02",
                      section.header.paragraphs[0].text)
        # The cover's own header stays empty.
        self.assertEqual(section.first_page_header.paragraphs[0].text.strip(), "")

    def test_glance_tiles_report_counts_from_data(self):
        tiles = self.doc.tables[0]
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

    def test_key_dates_panel_renders_cert_and_domain_dates(self):
        self.assertIn("KEY DATES", self.text)  # section heading, uppercased
        self.assertIn("2026-09-10", self.text)   # cert renewal date
        self.assertIn("2027-04-02", self.text)   # domain renewal date
        self.assertIn("about 11.0 years ago", self.text)
        panel = next(t for t in self.doc.tables
                     if any("2026-09-10" in c.text for c in t.rows[0].cells))
        self.assertEqual(len(panel.columns), 3)

    def test_section_headings_are_numbered_and_keep_with_next(self):
        heading = next(p for p in self.doc.paragraphs
                       if p.text.endswith("EXECUTIVE SUMMARY"))
        self.assertTrue(heading.paragraph_format.keep_with_next)
        self.assertTrue(heading.text.startswith("01"))

    def test_scorecard_draws_measured_score_bars(self):
        table = self._table_with_header("MEASURED SCORE")
        bar = table.rows[1].cells[2]  # security, score 0.28
        self.assertEqual(bar.text.count(ber.SCORE_BAR_BLOCK), ber.SCORE_BAR_SEGMENTS)
        self.assertTrue(bar.text.endswith("0.28"))
        # The filled segments carry the band color (Poor), in the first
        # non-empty run (cell.text = "" leaves an empty placeholder run).
        first_run = next(r for r in bar.paragraphs[0].runs if r.text)
        self.assertEqual(str(first_run.font.color.rgb), ber.BAND_FILL["Poor"])
        self.assertEqual(len(first_run.text), round(0.28 * ber.SCORE_BAR_SEGMENTS))

    def test_bottom_line_kicker_renders(self):
        self.assertIn("THE BOTTOM LINE", self.text)

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

    def test_executive_summary_shows_strengths_and_priorities(self):
        self.assertIn("EXECUTIVE SUMMARY", self.text)
        self.assertIn("STRENGTHS", self.text)
        self.assertIn("PRIORITIES TO FIX", self.text)
        self.assertIn("TLS and certificates: strong", self.text)
        self.assertIn("Security posture: poor", self.text)

    def test_action_plan_renders_when_no_recommendations(self):
        data = {k: v for k, v in SAMPLE.items() if k != "recommendations"}
        out = Path(self.tmp.name) / "plan.docx"
        ber.build(data, out)
        text = _doc_text(Document(str(out)))
        self.assertIn("RECOMMENDED PLAN OF ACTION", text)
        self.assertIn("Add an HSTS response header", text)

    def test_hand_authored_recommendations_win_over_action_plan(self):
        # SAMPLE has recommendations; the auto plan must not also render.
        self.assertIn("PREFERRED RECOMMENDATIONS", self.text)
        self.assertNotIn("RECOMMENDED PLAN OF ACTION", self.text)

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
        # Only the glance tiles remain (the cover holds no tables); every
        # data-driven table (scorecard, findings, recommendations) is skipped.
        self.assertEqual(len(doc.tables), 1)
        self.assertNotIn("THE BOTTOM LINE", text)

    def _table_with_header(self, header_text):
        """The table whose first-row cells include an exact header label.
        Exact match matters: the glance tiles carry labels like OVERALL
        POSTURE that would satisfy a substring lookup."""
        for table in self.doc.tables:
            if any(c.text.strip() == header_text for c in table.rows[0].cells):
                return table
        self.fail(f"No table with a header cell equal to {header_text!r}")


TREND_2Q = {
    "quarters": ["2026-Q2", "2026-Q3"],
    "series": {"overall_score": [0.72, 0.84]},
    "latest_delta": {
        "prev_quarter": "2026-Q2", "quarter": "2026-Q3",
        "scorecard": [{"category": "security", "prev_band": "Adequate",
                       "band": "Strong", "prev_score": 0.7, "score": 0.9,
                       "direction": "improved"},
                      {"category": "seo", "prev_band": "Strong",
                       "band": "Strong", "prev_score": 0.9, "score": 0.9,
                       "direction": "held"}],
        "new_findings": 1, "resolved_findings": 2,
        "resolved_examples": [
            "[a11y] link_text: 2 link(s) have no discernible text.",
            "[seo] headings: No H1 on the page."],
        "pages_scanned": {"prev": 12, "current": 12},
    },
}

TREND_3Q = {
    "quarters": ["2026-Q1", "2026-Q2", "2026-Q3"],
    "series": {"overall_score": [0.61, 0.72, 0.84],
               "security_score": [0.5, 0.7, 0.9],
               "median_lcp_ms": [3400, 2600, 2100],
               "median_weight_kb": [3100.0, 2500.0, 2400.0],
               "broken_links": [9, 4, 3]},
    "latest_delta": TREND_2Q["latest_delta"],
}


@unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
class TestTrendSection(unittest.TestCase):
    def _data(self, trend):
        data = {k: v for k, v in SAMPLE.items() if k != "evidence"}
        data["slug"] = "example-com"
        data["progress"] = dict(SAMPLE["progress"], trend=trend)
        return data

    def _doc(self, data, tmp):
        out = Path(tmp) / "r.docx"
        ber.build(data, out, chart_dir=Path(tmp) / "charts")
        return Document(str(out))

    def test_trend_table_and_named_resolved_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        texts = [p.text for p in doc.paragraphs]
        self.assertTrue(any("Progress this quarter" in t for t in texts))
        headers = [t.rows[0].cells[0].text.strip() for t in doc.tables]
        self.assertIn("AREA", headers)
        self.assertTrue(any("No H1 on the page." in t for t in texts))
        self.assertTrue(any(
            "2 finding(s) resolved since 2026-Q2; 1 new." in t for t in texts))
        self.assertTrue(any("Pages reviewed: 12 in 2026-Q2, 12 in 2026-Q3"
                            in t for t in texts))

    def test_progress_strip_suppressed_when_trend_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        texts = [p.text for p in doc.paragraphs]
        self.assertFalse(any("Since the previous review" in t for t in texts))

    def test_two_quarters_embed_no_charts(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        self.assertEqual(len(doc.inline_shapes), 0)

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_three_quarters_embed_charts(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_3Q), tmp)
        # overall + categories (one drawable category) + metrics figure
        self.assertEqual(len(doc.inline_shapes), 3)

    def test_three_quarter_trend_without_slug_raises(self):
        """K4: chart file names are prefixed with the slug so two clients'
        trend PNGs can never collide under the shared rendered/ directory;
        a missing slug must fail loudly rather than fall back to "site"."""
        data = self._data(TREND_3Q)
        del data["slug"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self._doc(data, tmp)

    def test_two_quarter_trend_without_slug_still_builds(self):
        """No charts render below three quarters, so the missing slug never
        matters and the report must still build."""
        data = self._data(TREND_2Q)
        del data["slug"]
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(data, tmp)
        self.assertEqual(len(doc.inline_shapes), 0)

    def test_cover_contents_list_includes_progress_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(self._data(TREND_2Q), tmp)
        texts = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("Progress this quarter", texts)


@unittest.skipUnless(HAVE_DOCX, "python-docx not installed")
class TestReportLabel(unittest.TestCase):
    def _doc(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.docx"
            ber.build(data, out)
            return Document(str(out))

    def test_sample_label_renders_on_cover_and_header(self):
        data = dict(SAMPLE, report_label="SAMPLE REPORT",
                    cover_note="Sample copy: prior-quarter history is illustrative.")
        doc = self._doc(data)
        texts = [p.text for p in doc.paragraphs]
        self.assertTrue(any("WEBSITE REVIEW  /  SAMPLE REPORT" in t for t in texts))
        self.assertTrue(any(t.strip() == "SAMPLE REPORT" for t in texts))
        self.assertTrue(any("prior-quarter history is illustrative" in t for t in texts))
        self.assertFalse(any("nothing is estimated" in t for t in texts))
        header = doc.sections[0].header
        self.assertIn("SAMPLE REPORT", header.paragraphs[0].text)

    def test_default_build_keeps_executive_kicker_and_pledge(self):
        doc = self._doc(dict(SAMPLE))
        texts = [p.text for p in doc.paragraphs]
        self.assertTrue(any("WEBSITE REVIEW  /  EXECUTIVE REPORT" in t for t in texts))
        self.assertTrue(any("nothing is estimated" in t for t in texts))
        self.assertFalse(any(t.strip() == "SAMPLE REPORT" for t in texts))


    def test_recommendations_table_keeps_together(self):
        doc = self._doc(dict(SAMPLE))
        table = next(t for t in doc.tables
                     if len(t.rows[0].cells) > 1
                     and t.rows[0].cells[1].text.strip() == "RECOMMENDATION")
        for row in list(table.rows)[:-1]:
            for cell in row.cells:
                for para in cell.paragraphs:
                    self.assertTrue(para.paragraph_format.keep_with_next)


class TestBuilderDependencies(unittest.TestCase):
    """M3: every third-party import in the builder modules must be declared in
    requirements.txt, so a report never fails on an undeclared dependency (the
    matplotlib gap that made M3). This is the builder analog of the scanner
    charter guard (PLAN section 38); before the fix matplotlib was imported by
    report_charts.py but absent from requirements.txt, and this test would fail."""

    REVIEW = Path(__file__).resolve().parent
    ROOT = REVIEW.parents[2]
    IMPORT_TO_PACKAGE = {"docx": "python-docx"}  # import name -> pip package name

    def _third_party_imports(self, path):
        import ast
        local = {p.stem for p in self.REVIEW.glob("*.py")}
        local |= {p.stem for p in (self.REVIEW / "tools").glob("*.py")}
        mods = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
        return {m for m in mods
                if m not in sys.stdlib_module_names and m not in local}

    def _declared_packages(self):
        pkgs = set()
        for line in (self.ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = line
            for sep in ("<", ">", "=", "!", "~", " "):
                name = name.split(sep)[0]
            pkgs.add(name.strip().lower())
        return pkgs

    def test_builder_third_party_imports_are_declared(self):
        declared = self._declared_packages()
        found = set()
        for module in ("build_exec_report.py", "report_charts.py"):
            found |= self._third_party_imports(self.REVIEW / module)
        self.assertTrue(found, "no third-party imports discovered; the ast/glob "
                               "scan is broken (it should find docx and matplotlib)")
        for imp in found:
            pkg = self.IMPORT_TO_PACKAGE.get(imp, imp).lower()
            self.assertIn(pkg, declared,
                          f"builder imports {imp!r} ({pkg}) but requirements.txt "
                          f"does not declare it")
        self.assertIn("python-docx", declared)
        self.assertIn("matplotlib", declared)


if __name__ == "__main__":
    unittest.main()
