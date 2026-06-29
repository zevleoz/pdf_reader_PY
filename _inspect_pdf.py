"""抽样检查 4 份 PDF 的原始文本质量。"""
import fitz
from pathlib import Path

BASE = Path("/Users/jefflau/projects/pdf_report_converter/PDF_converter")
INPUT = BASE / "input"

for pdf in sorted(INPUT.glob("*.pdf")):
    doc = fitz.open(pdf)
    print("=" * 60)
    print("FILE:", pdf.name, "| pages:", len(doc))
    for i in range(min(3, len(doc))):
        t = doc[i].get_text()
        lines = [l for l in t.splitlines() if l.strip()]
        print(f"-- page {i+1} --")
        for ln in lines[:6]:
            print(" |", ln[:120])
    doc.close()
