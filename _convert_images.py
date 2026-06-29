import fitz
from pathlib import Path

INPUT_DIR = Path("input")
PAGES_DIR = Path("pages")
PAGES_DIR.mkdir(exist_ok=True)

pdfs = sorted(INPUT_DIR.glob("*.pdf"))
print("Found {} PDFs".format(len(pdfs)))

for pdf in pdfs:
    stem = pdf.stem
    out_dir = PAGES_DIR / stem
    out_dir.mkdir(exist_ok=True)
    doc = fitz.open(str(pdf))
    print("  {}: {} pages".format(stem, len(doc)))
    mat = fitz.Matrix(200.0 / 72.0, 200.0 / 72.0)
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(out_dir / "page_{:02d}.png".format(i)))
    doc.close()

print("\nDone converting all PDFs to images (200 DPI)")
print()
for pdf in pdfs:
    stem = pdf.stem
    out_dir = PAGES_DIR / stem
    sizes = []
    for p in sorted(out_dir.glob("*.png")):
        sizes.append(p.stat().st_size / 1024)
    print("  {}: {} images, avg {:.0f} KB, total {:.0f} KB".format(
        stem, len(sizes), sum(sizes)/len(sizes) if sizes else 0, sum(sizes)))
