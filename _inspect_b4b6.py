"""查看 B4 和 B6 的关键页面"""
from __future__ import annotations
import fitz
from pathlib import Path

INPUT_DIR = Path("input")

for fname in ["B4", "B6"]:
    pdfs = sorted(INPUT_DIR.glob("{}*.pdf".format(fname)))
    if not pdfs:
        continue
    pdf_path = pdfs[0]
    doc = fitz.open(str(pdf_path))
    print("\n" + "=" * 70)
    print("PDF: {}".format(pdf_path.name))
    print("=" * 70)

    for i, page in enumerate(doc):
        text = page.get_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) > 3:
            print("\n  [Page {} ({} lines)]".format(i + 1, len(lines)))
            for line in lines:
                print("    | " + line)
    doc.close()
