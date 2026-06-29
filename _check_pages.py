"""查看关键页面的精确文本。"""
from __future__ import annotations
import fitz
from pathlib import Path

INPUT_DIR = Path("input")

pdfs = sorted(INPUT_DIR.glob("*.pdf"))
for pdf in pdfs:
    doc = fitz.open(str(pdf))
    print("\n" + "=" * 70)
    print("PDF: {}".format(pdf.name))
    print("=" * 70)
    print("Total pages: {}".format(len(doc)))
    for i in range(len(doc)):
        text = doc[i].get_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        print("\n  [Page {} ({} lines)".format(i + 1, len(lines)))
        # Print first 40 lines
        for line in lines[:40]:
            print("    " + line)
    doc.close()
