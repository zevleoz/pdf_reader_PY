"""从 PDF 提取文本检查中文是否正常。"""
import fitz

for f in ["output/test_cn.pdf", "output/综合评估报告.pdf", "output/report.pdf"]:
    print("=" * 50)
    print("FILE:", f)
    try:
        doc = fitz.open(f)
        for i in range(min(3, len(doc))):
            t = doc[i].get_text()
            print(f"-- page {i+1} --")
            for ln in [l for l in t.splitlines() if l.strip()][:6]:
                print(" |", ln[:140])
        print("fonts info:")
        for i in range(min(2, len(doc))):
            for font in doc[i].get_fonts():
                print("   font:", font)
        doc.close()
    except Exception as e:
        print("ERR:", e)
