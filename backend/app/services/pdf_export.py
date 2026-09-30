"""Markdown / plain text → PDF (中英混排，Windows 字体)."""
from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsunb.ttf"),
]


def _pick_font() -> Path:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("未找到中文字体（simhei/simsunb）")


def _strip_md(line: str) -> tuple[str, str]:
    s = line.rstrip()
    if not s.strip():
        return "blank", ""
    if re.match(r"^---+$", s.strip()):
        return "hr", ""
    if s.startswith("### "):
        return "h3", s[4:].strip()
    if s.startswith("## "):
        return "h2", s[3:].strip()
    if s.startswith("# "):
        return "h1", s[2:].strip()
    if s.startswith("- ") or s.startswith("* "):
        return "li", "- " + s[2:].strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return "body", text


class TradePDF(FPDF):
    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("DocFont", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"TradePilot · Page {self.page_no()}/{{nb}}", align="C")


def markdown_to_pdf(
    markdown: str,
    out_path: Path,
    *,
    title: str = "TradePilot Document",
) -> str:
    font_path = _pick_font()
    pdf = TradePDF(format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(left=16, top=16, right=16)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.add_font("DocFont", style="", fname=str(font_path))
    usable = pdf.epw

    pdf.set_font("DocFont", size=16)
    pdf.set_text_color(15, 55, 75)
    pdf.multi_cell(usable, 10, title)
    pdf.ln(2)
    y = pdf.get_y()
    pdf.set_draw_color(20, 120, 130)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, y, pdf.l_margin + usable, y)
    pdf.ln(6)

    for raw in markdown.splitlines():
        style, text = _strip_md(raw)
        if style == "blank":
            pdf.ln(3)
            continue
        if style == "hr":
            pdf.ln(2)
            y = pdf.get_y()
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, y, pdf.l_margin + usable, y)
            pdf.ln(4)
            continue
        if style == "h1":
            pdf.set_font("DocFont", size=14)
            pdf.set_text_color(15, 55, 75)
            pdf.multi_cell(usable, 9, text)
            pdf.ln(2)
        elif style == "h2":
            pdf.set_font("DocFont", size=12)
            pdf.set_text_color(20, 90, 100)
            pdf.multi_cell(usable, 8, text)
            pdf.ln(1)
        elif style == "h3":
            pdf.set_font("DocFont", size=11)
            pdf.set_text_color(40, 70, 80)
            pdf.multi_cell(usable, 7, text)
        else:
            pdf.set_font("DocFont", size=10)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(usable, 6, text if text else " ")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return str(out_path)


def export_bundle_pdfs(
    out_dir: Path,
    *,
    contract_md: str,
    docs: dict[str, dict],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    paths["contract"] = markdown_to_pdf(
        contract_md,
        out_dir / "contract_zh_en.pdf",
        title="Sales Contract / 购销合同",
    )
    titles = {
        "pi": "Proforma Invoice (PI)",
        "ci": "Commercial Invoice (CI)",
        "pl": "Packing List (PL)",
        "customs": "Customs Declare Elements / 报关要素",
    }
    for key, doc in docs.items():
        paths[key] = markdown_to_pdf(
            doc.get("body_md") or "",
            out_dir / f"{key}.pdf",
            title=titles.get(key, key.upper()),
        )
    return paths
