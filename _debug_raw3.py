import fitz, re
doc = fitz.open('input/report_B6.pdf')
for page_idx in range(len(doc)):
    text = doc[page_idx].get_text()
    if "职业价值观" in text or "MY WORK VALUES" in text:
        print(f"===== Page {page_idx+1} =====")
        # 打印包含数字的行
        for line in text.splitlines():
            if re.search(r"\d+\.?\d*", line) or "职业" in line or "分" in line or "价值" in line:
                print(repr(line))
doc.close()
