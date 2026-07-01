#!/usr/bin/env python3
"""
Executive report builder for the website review scaffold.

Reads a JSON file of findings and recommendations and writes a one-to-two page,
CEO-level Word report with consistent formatting. Formatting lives here so the
report looks identical on every run regardless of who or what invokes it, and
regardless of which site was analyzed.

Usage:
    python build_exec_report.py <input_json> <output_docx>

Dependency:
    pip install python-docx
"""

import json
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Single accent color. Swap this hex to rebrand the whole report.
ACCENT_HEX = "0B1F3A"                       # deep navy
ACCENT_RGB = RGBColor(0x0B, 0x1F, 0x3A)
WHITE_RGB = RGBColor(0xFF, 0xFF, 0xFF)
BODY_RGB = RGBColor(0x22, 0x22, 0x22)
MARK_RGB = RGBColor(0xC0, 0x39, 0x2B)       # red, for the marked (problem) text
MONO_FONT = "Consolas"

# Background fill per severity for the severity cell.
SEVERITY_FILL = {
    "Critical": "C0392B",
    "High": "E67E22",
    "Medium": "F1C40F",
    "Low": "27AE60",
}
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# Background fill per measured posture band (from the scanner scorecard).
BAND_FILL = {
    "Strong": "27AE60",
    "Adequate": "F1C40F",
    "Weak": "E67E22",
    "Poor": "C0392B",
    "Not measured": "7F8C8D",
}


def add_run(paragraph, text, size=10, bold=False, color=BODY_RGB, italic=False):
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = "Calibri"
    return run


def shade_cell(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def set_cell_text(cell, text, size=9, bold=False, color=BODY_RGB, align=None):
    cell.text = ""
    para = cell.paragraphs[0]
    if align is not None:
        para.alignment = align
    add_run(para, text, size=size, bold=bold, color=color)


def section_heading(document, text):
    para = document.add_paragraph()
    para.paragraph_format.space_before = Pt(14)
    para.paragraph_format.space_after = Pt(4)
    add_run(para, text.upper(), size=12, bold=True, color=ACCENT_RGB)
    return para


def text_color_for_fill(hex_fill):
    # Amber background needs dark text for contrast; the rest use white.
    return BODY_RGB if hex_fill.upper() == "F1C40F" else WHITE_RGB


def set_col_widths(table, widths):
    # python-docx needs the width set on every cell to be reliable.
    for row in table.rows:
        for idx, width in enumerate(widths):
            row.cells[idx].width = width


def _add_marked_runs(paragraph, text, highlights, size=8):
    """Add `text` as monospace runs, marking every occurrence of any highlight
    substring with a yellow highlighter and bold red text so the exact problem
    is unmissable."""
    def style(run, marked=False):
        run.font.name = MONO_FONT
        run.font.size = Pt(size)
        if marked:
            run.font.bold = True
            run.font.color.rgb = MARK_RGB
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        else:
            run.font.color.rgb = BODY_RGB

    highlights = [h for h in (highlights or []) if h]
    i, n = 0, len(text)
    while i < n:
        nxt, nxt_h = None, None
        for h in highlights:
            idx = text.find(h, i)
            if idx != -1 and (nxt is None or idx < nxt):
                nxt, nxt_h = idx, h
        if nxt is None:
            style(paragraph.add_run(text[i:]))
            break
        if nxt > i:
            style(paragraph.add_run(text[i:nxt]))
        style(paragraph.add_run(nxt_h), marked=True)
        i = nxt + len(nxt_h)


def add_code_block(document, code, highlight=None):
    """A shaded monospace box holding a literal snippet, with the exact problem
    substring(s) highlighted. `highlight` is a string or list of strings. Each
    source line becomes its own paragraph so line breaks are preserved."""
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    shade_cell(cell, "F5F5F5")
    cell.text = ""
    for idx, line in enumerate(code.split("\n")):
        para = cell.paragraphs[0] if idx == 0 else cell.add_paragraph()
        _add_marked_runs(para, line, highlight)
    set_col_widths(table, [Inches(6.5)])


def build(data, out_path):
    document = Document()

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.font.color.rgb = BODY_RGB

    for section in document.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    site = data.get("site", "Website")
    target_url = data.get("target_url", "")
    date = data.get("date", "")

    title = document.add_paragraph()
    title.paragraph_format.space_after = Pt(2)
    add_run(title, f"{site} Website Review", size=20, bold=True, color=ACCENT_RGB)

    subtitle = document.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(2)
    add_run(subtitle, "Executive Report", size=12, bold=True, color=ACCENT_RGB)

    meta = document.add_paragraph()
    meta_bits = [b for b in [target_url, date] if b]
    add_run(meta, "   |   ".join(meta_bits), size=9, italic=True, color=BODY_RGB)

    # Bottom line
    section_heading(document, "Bottom line")
    bl = document.add_paragraph()
    add_run(bl, data.get("bottom_line", ""), size=10)

    # Measured posture scorecard (optional; only when the scan supplied one)
    scorecard = data.get("scorecard")
    if scorecard and scorecard.get("rows"):
        heading = "Measured posture"
        overall = scorecard.get("overall")
        if overall:
            heading += f" (overall: {overall})"
        section_heading(document, heading)
        table = document.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for cell, label in zip(table.rows[0].cells, ["Area", "Posture", "Measured detail"]):
            shade_cell(cell, ACCENT_HEX)
            set_cell_text(cell, label, size=9, bold=True, color=WHITE_RGB)
        for row in scorecard["rows"]:
            cells = table.add_row().cells
            set_cell_text(cells[0], row.get("category", ""), size=9)
            band = row.get("band", "Not measured")
            fill = BAND_FILL.get(band, BAND_FILL["Not measured"])
            shade_cell(cells[1], fill)
            set_cell_text(cells[1], band, size=9, bold=True,
                          color=text_color_for_fill(fill), align=WD_ALIGN_PARAGRAPH.CENTER)
            set_cell_text(cells[2], row.get("detail", ""), size=9)
        set_col_widths(table, [Inches(1.6), Inches(1.1), Inches(3.2)])

    # Key findings, most severe first
    findings = sorted(
        data.get("findings", []),
        key=lambda f: SEVERITY_ORDER.get(f.get("severity", "Low"), 9),
    )
    if findings:
        section_heading(document, "Key findings hurting the site")
        table = document.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for cell, label in zip(table.rows[0].cells,
                               ["Area", "Finding", "Evidence", "Severity"]):
            shade_cell(cell, ACCENT_HEX)
            set_cell_text(cell, label, size=9, bold=True, color=WHITE_RGB)
        for row_data in findings:
            cells = table.add_row().cells
            set_cell_text(cells[0], row_data.get("area", ""), size=9)
            set_cell_text(cells[1], row_data.get("finding", ""), size=9)
            set_cell_text(cells[2], row_data.get("evidence", ""), size=8)
            sev = row_data.get("severity", "Low")
            fill = SEVERITY_FILL.get(sev, SEVERITY_FILL["Low"])
            shade_cell(cells[3], fill)
            set_cell_text(cells[3], sev, size=9, bold=True,
                          color=text_color_for_fill(fill),
                          align=WD_ALIGN_PARAGRAPH.CENTER)
        set_col_widths(table, [Inches(1.0), Inches(3.4), Inches(1.6), Inches(0.9)])

    # Preferred recommendations, by rank
    recs = sorted(data.get("recommendations", []),
                  key=lambda r: r.get("rank", 999))
    if recs:
        section_heading(document, "Preferred recommendations")
        table = document.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for cell, label in zip(table.rows[0].cells,
                               ["#", "Recommendation", "Expected impact", "Effort"]):
            shade_cell(cell, ACCENT_HEX)
            set_cell_text(cell, label, size=9, bold=True, color=WHITE_RGB)
        for row_data in recs:
            cells = table.add_row().cells
            set_cell_text(cells[0], str(row_data.get("rank", "")), size=9,
                          align=WD_ALIGN_PARAGRAPH.CENTER)
            set_cell_text(cells[1], row_data.get("recommendation", ""), size=9)
            set_cell_text(cells[2], row_data.get("impact", ""), size=9)
            set_cell_text(cells[3], row_data.get("effort", ""), size=9,
                          align=WD_ALIGN_PARAGRAPH.CENTER)
        set_col_widths(table, [Inches(0.4), Inches(3.4), Inches(2.2), Inches(0.9)])

    # Quick wins
    quick = data.get("quick_wins", [])
    if quick:
        section_heading(document, "Quick wins")
        for item in quick:
            p = document.add_paragraph(style="List Bullet")
            add_run(p, item, size=10)

    # Evidence appendix (optional): captioned proof for significant findings. Each
    # item is {"caption": "..."} plus either an "image" (screenshot path) or a
    # "code" snippet with an optional "highlight" (string or list) that marks the
    # exact problem so the reader sees precisely where the error is.
    evidence = data.get("evidence", [])
    if evidence:
        document.add_page_break()
        section_heading(document, "Evidence appendix")
        for item in evidence:
            cap = document.add_paragraph()
            cap.paragraph_format.space_before = Pt(10)
            cap.paragraph_format.space_after = Pt(2)
            add_run(cap, item.get("caption", ""), size=9, bold=True, color=ACCENT_RGB)
            if item.get("code") is not None:
                add_code_block(document, item["code"], item.get("highlight"))
            elif item.get("image"):
                img = item["image"]
                if Path(img).exists():
                    try:
                        document.add_picture(img, width=Inches(6.5))
                    except Exception as e:
                        add_run(document.add_paragraph(), f"[image not embedded: {e}]", size=8, italic=True)
                else:
                    add_run(document.add_paragraph(), f"[missing image: {img}]", size=8, italic=True)

    document.save(str(out_path))


def main():
    if len(sys.argv) != 3:
        print("Usage: python build_exec_report.py <input_json> <output_docx>")
        sys.exit(1)
    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    if not in_path.exists():
        print(f"Input JSON not found: {in_path}")
        sys.exit(1)
    data = json.loads(in_path.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    build(data, out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
