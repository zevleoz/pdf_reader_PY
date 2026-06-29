"""生成 POINT_META 的 JSON 定义，再用它来构建 data_points.py。"""
import re
import json
from pathlib import Path

# 从 extract.py 提取 SCHEMA 定义
extract_path = Path(__file__).parent / "extract.py"
content = extract_path.read_text(encoding="utf-8")

schema_start = content.find("SCHEMA_124")
bracket_start = content.find("[", schema_start)
schema_block = content[bracket_start:]

item_pattern = r'\{\s*"code":\s*"(\d+)",\s*"label":\s*"([^"]+)"'
schema_items = []
for m in re.finditer(item_pattern, schema_block):
    schema_items.append({"code": m.group(1), "label": m.group(2)})

print(f"提取到 {len(schema_items)} 项")

# 分组判断
group_keywords = [
    ("认知能力", ["认知", "感知觉", "注意力", "记忆力", "推理", "空间能力", "加工速度"]),
    ("情绪稳定性", ["情绪稳定性", "自卑", "抑郁", "焦虑", "无力感"]),
    ("人格", ["开放性", "宜人性", "责任心", "外倾性", "神经质"]),
    ("依恋关系", ["母亲", "父亲", "同伴", "信任", "沟通", "亲近", "依恋"]),
    ("体质健康", ["BMI", "身高", "体重", "饮食", "睡眠", "运动", "体质健康"]),
    ("自我概念", ["自我概念", "行为表现", "能力与学校表现", "躯体外貌", "情绪状态", "合群", "幸福与满足"]),
    ("思维模式与自驱力", ["思维模式", "自主性", "胜任感", "归属感"]),
    ("执行功能", ["抑制控制", "工作记忆", "认知灵活性"]),
    ("学习动机", ["深层动机", "表面动机", "自我效能感"]),
    ("学习方法与策略", ["学习方法", "学习自我调节"]),
    ("职业兴趣", ["职业兴趣", "现实型", "研究型", "艺术型", "社会型", "事业型", "常规型"]),
    ("能力优势", ["能力优势", "语言能力", "逻辑数学能力", "音乐能力", "身体运动能力", "人际关系能力", "内省能力", "自然能力"]),
    ("职业价值观", ["职业价值观", "创造发明", "独立自主", "美的追求", "智力激发", "利他助人", "成就感", "管理权力", "工作环境", "同事关系", "上司关系", "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]),
]

def get_group(label: str) -> str:
    for g, keywords in group_keywords:
        for kw in keywords:
            if kw in label:
                return g
    return "其他"

# 为每个编号生成 POINT_META 定义
meta_lines = []
user_data_lines = []

for item in schema_items:
    code = item["code"]
    label = item["label"]
    group = get_group(label)
    
    # POINT_META
    meta_lines.append(f'    "{code}": {{"code": "{code}", "label": "{label}", "group": "{group}"}},')
    
    # USER_DATA
    user_data_lines.append(f'    "{code}": "",  # {label}')

# 生成完整的 data_points.py 文件内容
output = '''# -*- coding: utf-8 -*-
"""
data_points.py —— 综合测评报告 124 个基础数据点

⚠️  编号 001-124 必须与 extract.py 中的 SCHEMA_124 定义 100% 一致
    否则 generate.py 取到的数据会是错的

使用方式：
  >>> from data_points import USER_DATA, POINT_META, v
  >>> USER_DATA['001']  # 读取某个编号的值
  >>> v('001')           # 同上，更短
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


# ========================================================================
# 124 个数据点的元数据（编号、中文标签、分组）
# 编号和标签必须与 extract.py 中的 SCHEMA_124 完全一致
# ========================================================================
POINT_META: Dict[str, Dict[str, Any]] = {

'''

# 1) 认知能力（001-008）
output += "    # --- 1) 认知能力（001-008） ---\n"
for line in meta_lines[:8]:
    output += line + "\n"

# 2) 情绪稳定性（009-014）
output += "\n    # --- 2) 情绪稳定性（009-014） ---\n"
for line in meta_lines[8:14]:
    output += line + "\n"

# 3) 人格（015-019）
output += "\n    # --- 3) 人格（015-019） ---\n"
for line in meta_lines[14:19]:
    output += line + "\n"

# 4) 依恋关系（020-040）
output += "\n    # --- 4) 依恋关系（020-040） ---\n"
for line in meta_lines[19:40]:
    output += line + "\n"

# 5) 体质健康（041-052）
output += "\n    # --- 5) 体质健康（041-052） ---\n"
for line in meta_lines[40:52]:
    output += line + "\n"

# 6) 自我概念（053-067）
output += "\n    # --- 6) 自我概念（053-067） ---\n"
for line in meta_lines[52:67]:
    output += line + "\n"

# 7) 思维模式与自驱力（068-071）
output += "\n    # --- 7) 思维模式与自驱力（068-071） ---\n"
for line in meta_lines[67:71]:
    output += line + "\n"

# 8) 执行功能（072-074）
output += "\n    # --- 8) 执行功能（072-074） ---\n"
for line in meta_lines[71:74]:
    output += line + "\n"

# 9) 学习动机（075-077）
output += "\n    # --- 9) 学习动机（075-077） ---\n"
for line in meta_lines[74:77]:
    output += line + "\n"

# 10) 学习方法与策略（078-080）
output += "\n    # --- 10) 学习方法与策略（078-080） ---\n"
for line in meta_lines[77:80]:
    output += line + "\n"

# 11) 职业兴趣（081-087）
output += "\n    # --- 11) 职业兴趣（081-087） ---\n"
for line in meta_lines[80:87]:
    output += line + "\n"

# 12) 能力优势（088-103）
output += "\n    # --- 12) 能力优势（088-103） ---\n"
for line in meta_lines[87:103]:
    output += line + "\n"

# 13) 职业价值观（104-124）
output += "\n    # --- 13) 职业价值观（104-124） ---\n"
for line in meta_lines[103:]:
    output += line + "\n"

output += "\n}\n\n\n"

# USER_DATA
output += "# ========================================================================\n"
output += "# 学生数据值：编号 → 字符串值\n"
output += "# 初始为空，extract.py 运行后从 report_data.json 回填\n"
output += "# ========================================================================\n"
output += "USER_DATA: Dict[str, Any] = {\n\n"

for i, line in enumerate(user_data_lines):
    output += line + "\n"

output += "\n}\n\n\n"

# 便捷函数
output += '''# ========================================================================
# 便捷函数
# ========================================================================

def v(code: str) -> str:
    """读取某个编号的值。"""
    return USER_DATA.get(code, "")


def get_point(code: str) -> Dict[str, Any]:
    """读取某个编号的完整条目（元数据 + 值）。"""
    meta = POINT_META.get(code, {})
    return {**meta, "value": USER_DATA.get(code, "")}


def apply_report_data(report_data_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    从 report_data.json 中读取 schema_124，回填到 USER_DATA。
    这是最重要的一步：保证 extract.py 的输出与 generate.py 的输入一致。
    """
    if report_data_path is None:
        report_data_path = Path(__file__).resolve().parent / "data" / "report_data.json"
    result = {
        "applied": 0,
        "total_items": 0,
        "path": str(report_data_path),
    }
    if not report_data_path.exists():
        return result

    try:
        with open(report_data_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as exc:
        print(f"[data_points] 读取 report_data.json 失败: {exc}")
        return result

    # 从 schema_124 回填——这是最可靠的方式
    schema_124 = report.get("schema_124") or []
    applied = 0
    if schema_124:
        for item in schema_124:
            code = str(item.get("code", "")).strip()
            value = item.get("value")
            if not code:
                continue
            if code in USER_DATA:
                USER_DATA[code] = "" if value is None else str(value)
                applied += 1
        print(f"[data_points] schema_124 回填 {applied} 项")

    result["applied"] = applied
    result["total_items"] = len(schema_124)
    return result


def student_meta() -> Dict[str, str]:
    """返回 report_data.json 中的学生信息。"""
    path = Path(__file__).resolve().parent / "data" / "report_data.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("student", {})


# ========================================================================
# 模块加载时自动回填（如果 report_data.json 存在）
# ========================================================================
try:
    apply_report_data()
except Exception as _exc:
    print(f"[data_points] apply_report_data 异常: {_exc}")


if __name__ == "__main__":
    n_meta = len(POINT_META)
    n_user = len(USER_DATA)
    filled = sum(1 for v in USER_DATA.values() if v)
    print(f"POINT_META: {n_meta} 个条目")
    print(f"USER_DATA: {n_user} 个条目")
    print(f"已回填: {filled}/{n_user} 个值")
    for code, value in USER_DATA.items():
        label = POINT_META.get(code, {}).get("label", "")
        print(f"  {code} {label}: {value}")
'''

# 写入文件
output_path = Path(__file__).parent / "data_points.py"
output_path.write_text(output, encoding="utf-8")
print(f"✅ 已生成新的 data_points.py：{output_path}")
print(f"   共 {len(schema_items)} 项")

# 需要 import re
