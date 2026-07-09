"""Generate MEDEXA_PROJECT_SUMMARY.pdf from the markdown summary."""
from __future__ import annotations

import re
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    import subprocess
    import sys

    subprocess.check_call([sys.executable, "-m", "pip", "install", "fpdf2", "-q"])
    from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "docs" / "MEDEXA_PROJECT_SUMMARY.md"
PDF_PATH = ROOT / "docs" / "MEDEXA_PROJECT_SUMMARY.pdf"


class SummaryPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, "Medexa MVP - Project Summary", align="R", new_x="LMARGIN", new_y="NEXT")

    def footer(self) -> None:
        self.set_y(-10)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")
    
def sanitize(text: str) -> str:
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2192": "->", "\u2190": "<-",
        "\u2022": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u26a0": "[!]", "\u2705": "[OK]", "\u274c": "[X]",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def chunk_text(text: str, width: int = 85) -> list[str]:
    if not text:
        return [""]
    out: list[str] = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        if cut <= 0:
            cut = width
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out or [""]


def write_lines(pdf: SummaryPDF, lines: list[str], line_height: float = 5) -> None:
    w = pdf.epw
    for line in lines:
        if pdf.get_y() > pdf.eph - 20:
            pdf.add_page()
        pdf.multi_cell(w, line_height, line)


def render_markdown(pdf: SummaryPDF, md: str) -> None:
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)

    in_code = False
    for raw in md.splitlines():
        line = sanitize(raw.rstrip())

        if line.strip().startswith("```"):
            in_code = not in_code
            continue

        if in_code:
            pdf.set_font("Courier", "", 8)
            write_lines(pdf, chunk_text(line, 80), 4)
            continue

        if line.startswith("# "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 16)
            write_lines(pdf, chunk_text(line[2:], 70), 8)
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 13)
            write_lines(pdf, chunk_text(line[3:], 75), 7)
            pdf.ln(1)
        elif line.startswith("### "):
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 11)
            write_lines(pdf, chunk_text(line[4:], 78), 6)
        elif line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue
            pdf.set_font("Helvetica", "", 8)
            write_lines(pdf, chunk_text(" | ".join(cells), 95), 4)
        elif line.startswith("- "):
            pdf.set_font("Helvetica", "", 10)
            write_lines(pdf, chunk_text("  * " + line[2:]), 5)
        elif line.strip() == "---":
            pdf.ln(2)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(3)
        elif line.strip() == "":
            pdf.ln(2)
        else:
            text = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
            text = re.sub(r"`([^`]+)`", r"\1", text)
            pdf.set_font("Helvetica", "", 10)
            write_lines(pdf, chunk_text(text), 5)


def main() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    pdf = SummaryPDF()
    pdf.set_margins(18, 18, 18)
    render_markdown(pdf, md)
    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(PDF_PATH))
    print(f"Wrote {PDF_PATH}")

if __name__ == "__main__":
    main()

