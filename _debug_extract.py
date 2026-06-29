"""临时调试：看看 PDF 文本里关键字附近内容"""
import fitz
from pathlib import Path

def show(doc_path, title, keywords, width_left=40, width_right=250):
    doc = fitz.open(str(doc_path))
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    print(f"\n===== {title} ({doc_path}) =====")
    for kw in keywords:
        idx = 0
        found = 0
        while True:
            j = text.find(kw, idx)
            if j < 0 or found >= 2:
                break
            print(f"[{kw}] #{found} -> {text[max(0,j-width_left):j+width_right]!r}")
            idx = j + len(kw)
            found += 1
        if found == 0:
            print(f"[{kw}] -> NOT FOUND")

show(Path("input/report_A2.pdf"), "A2 体质健康",
     ["BMI", "身高", "体重", "饮食习惯", "均衡饮食", "运动习惯", "运动习惯得分", "睡眠习惯"])

show(Path("input/report_B4.pdf"), "B4 自我概念/思维模式/自驱力",
     ["自我概念", "自我概念整体", "思维模式", "成长型思维", "固定型思维",
      "自主性", "胜任感", "归属感", "行为表现", "能力与学校表现",
      "躯体外貌", "情绪状态", "合群", "幸福与满足"])

show(Path("input/report_B6.pdf"), "B6 职业价值观",
     ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
      "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
      "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"])
