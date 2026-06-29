"""从 extract.py 中提取完整 SCHEMA，然后生成新的 data_points.py。"""
import re
import json
from pathlib import Path

# 1) 提取 extract.py 中的 SCHEMA_124 定义（所有 code/label 对）
extract_path = Path(__file__).parent / "extract.py"
content = extract_path.read_text(encoding="utf-8")

# 找到 SCHEMA_124 开始的位置
schema_start = content.find("SCHEMA_124")
if schema_start < 0:
    print("⚠️  找不到 SCHEMA_124 定义")
    exit(1)

# 找到第一个 "["
bracket_start = content.find("[", schema_start)
if bracket_start < 0:
    print("⚠️  找不到 SCHEMA_124 的 [")
    exit(1)

# 找到匹配的 "]" - 从第一个 "{" 开始数
# 简化：提取 SCHEMA_124 块内的所有 code/label 对
schema_block = content[bracket_start:]

# 提取每个 {"code": "xxx", "label": "yyy", ...}
item_pattern = r'\{\s*"code":\s*"(\d+)",\s*"label":\s*"([^"]+)"'
schema_items = re.findall(item_pattern, schema_block)
schema_list = [{"code": code, "label": label} for code, label in schema_items]

print(f"从 extract.py 提取了 {len(schema_list)} 个 SCHEMA 项")
for i, item in enumerate(schema_list):
    print(f"  {item['code']:>3}: {item['label']}")

# 2) 现在生成新的 data_points.py
# 我们需要把 POINT_META 和 USER_DATA 的编号与 extract.py 完全一致
# 即：POINT_META 包含 code, label, group（用于分组展示）
# 而 USER_DATA 是 code -> value

# 先根据标签判断分组
group_keywords = {
    "认知": "认知能力",
    "感知觉": "认知能力",
    "注意力": "认知能力",
    "记忆力": "认知能力",
    "推理": "认知能力",
    "空间能力": "认知能力",
    "加工速度": "认知能力",
    
    "情绪稳定性": "情绪稳定性",
    "自卑": "情绪稳定性",
    "抑郁": "情绪稳定性",
    "焦虑": "情绪稳定性",
    "无力感": "情绪稳定性",
    
    "开放性": "人格",
    "宜人性": "人格",
    "责任心": "人格",
    "外倾性": "人格",
    "神经质": "人格",
    
    "母亲": "依恋关系",
    "父亲": "依恋关系",
    "同伴": "依恋关系",
    "信任": "依恋关系",
    "沟通": "依恋关系",
    "亲近": "依恋关系",
    "依恋": "依恋关系",
    
    "BMI": "体质健康",
    "身高": "体质健康",
    "体重": "体质健康",
    "饮食": "体质健康",
    "睡眠": "体质健康",
    "运动": "体质健康",
    "体质健康": "体质健康",
    
    "自我概念": "自我概念",
    "行为表现": "自我概念",
    "能力与学校表现": "自我概念",
    "躯体外貌": "自我概念",
    "情绪状态": "自我概念",
    "合群": "自我概念",
    "幸福与满足": "自我概念",
    
    "思维模式": "思维模式与自驱力",
    "自主性": "思维模式与自驱力",
    "胜任感": "思维模式与自驱力",
    "归属感": "思维模式与自驱力",
    
    "抑制控制": "执行功能",
    "工作记忆": "执行功能",
    "认知灵活性": "执行功能",
    
    "深层动机": "学习动机",
    "表面动机": "学习动机",
    "自我效能感": "学习动机",
    
    "学习方法": "学习方法与策略",
    "学习自我调节": "学习方法与策略",
    
    "职业兴趣": "职业兴趣",
    "现实型": "职业兴趣",
    "研究型": "职业兴趣",
    "艺术型": "职业兴趣",
    "社会型": "职业兴趣",
    "事业型": "职业兴趣",
    "常规型": "职业兴趣",
    
    "能力优势": "能力优势",
    "语言能力": "能力优势",
    "逻辑数学能力": "能力优势",
    "音乐能力": "能力优势",
    "身体运动能力": "能力优势",
    "人际关系能力": "能力优势",
    "内省能力": "能力优势",
    "自然能力": "能力优势",
    
    "职业价值观": "职业价值观",
    "创造发明": "职业价值观",
    "独立自主": "职业价值观",
    "美的追求": "职业价值观",
    "智力激发": "职业价值观",
    "利他助人": "职业价值观",
    "成就感": "职业价值观",
    "管理权力": "职业价值观",
    "工作环境": "职业价值观",
    "同事关系": "职业价值观",
    "上司关系": "职业价值观",
    "多样变化": "职业价值观",
    "经济报酬": "职业价值观",
    "安全稳定": "职业价值观",
    "声望地位": "职业价值观",
    "生活方式": "职业价值观",
}

def get_group(label: str) -> str:
    for keyword, group in group_keywords.items():
        if keyword in label:
            return group
    return "其他"

# 生成 data_points.py 的代码
lines = []
lines.append("# -*- coding: utf-8 -*-")
lines.append('"""')
lines.append("data_points.py —— 综合测评报告 124 个基础数据点")
lines.append("")
lines.append("⚠️  编号 001-124 必须与 extract.py 中的 SCHEMA 定义 100% 一致")
lines.append("    否则 generate.py 取到的数据会是错的")
lines.append("")
lines.append("使用方式：")
lines.append("  >>> from data_points import USER_DATA, POINT_META, v")
lines.append("  >>> USER_DATA['001']  # 读取某个编号的值")
lines.append("  >>> v('001')           # 同上，更短")
lines.append('"""')
lines.append("from __future__ import annotations")
lines.append("")
lines.append("from pathlib import Path")
lines.append("from typing import Any, Dict, List, Optional")
lines.append("")
lines.append("")
lines.append("# ========================================================================")
lines.append("# 124 个数据点的元数据（编号、中文标签、分组）")
lines.append("# 这个字典是不可变的——对所有学生相同")
lines.append("# 编号和标签必须与 extract.py 中的 SCHEMA 完全一致")
lines.append("# ========================================================================")
lines.append("POINT_META: Dict[str, Dict[str, Any]] = {")
lines.append("")

group_headers = {
    "认知能力": "1) 认知能力（001-008）",
    "情绪稳定性": "2) 情绪稳定性（009-014）",
    "人格": "3) 人格（015-019）",
    "依恋关系": "4) 依恋关系（020-040）",
    "体质健康": "5) 体质健康（041-052）",
    "自我概念": "6) 自我概念（053-067）",
    "思维模式与自驱力": "7) 思维模式与自驱力（068-071）",
    "执行功能": "8) 执行功能（072-074）",
    "学习动机": "9) 学习动机（075-077）",
    "学习方法与策略": "10) 学习方法与策略（078-080）",
    "职业兴趣": "11) 职业兴趣（081-087）",
    "能力优势": "12) 能力优势（088-103）",
    "职业价值观": "13) 职业价值观（104-124）",
}

current_group = None
for item in schema_list:
    code = item["code"]
    label = item["label"]
    group = get_group(label)
    
    if group != current_group:
        current_group = group
        header = group_headers.get(group, f"其他")
        lines.append("")
        lines.append(f"    # --- {header} ---")
    
    lines.append(f'    "{code}": {{"code": "{code}", "label": "{label}", "group": "{group}"}},')

lines.append("")
lines.append("}")
lines.append("")
lines.append("")
lines.append("# ========================================================================")
lines.append("# 学生数据值：编号 → 字符串值")
lines.append("# 初始为空，extract.py 运行后从 report_data.json 回填")
lines.append("# ========================================================================")
lines.append("USER_DATA: Dict[str, Any] = {")

for item in schema_list:
    code = item["code"]
    label = item["label"]
    lines.append(f'    "{code}": "",  # {label}')

lines.append("}")
lines.append("")
lines.append("")
lines.append("# ========================================================================")
lines.append("# 便捷函数")
lines.append("# ========================================================================")
lines.append("")
lines.append("def v(code: str) -> str:")
lines.append('    """读取某个编号的值。"""')
lines.append('    return USER_DATA.get(code, "")')
lines.append("")
lines.append("")
lines.append("def get_point(code: str) -> Dict[str, Any]:")
lines.append('    """读取某个编号的完整条目（元数据 + 值）。"""')
lines.append("    meta = POINT_META.get(code, {})")
lines.append('    return {**meta, "value": USER_DATA.get(code, "")}')
lines.append("")
lines.append("")
lines.append("def apply_report_data(report_data_path: Optional[Path] = None) -> Dict[str, Any]:")
lines.append('    """')
lines.append("    从 report_data.json 中读取 schema_124，回填到 USER_DATA。")
lines.append("    这是最重要的一步：保证 extract.py 的输出与 generate.py 的输入一致。")
lines.append('    """')
lines.append("    if report_data_path is None:")
lines.append("        report_data_path = Path(__file__).resolve().parent / 'data' / 'report_data.json'")
lines.append("    result = {")
lines.append('        "applied": 0,')
lines.append('        "total_items": 0,')
lines.append('        "path": str(report_data_path),')
lines.append("    }")
lines.append("    if not report_data_path.exists():")
lines.append("        return result")
lines.append("")
lines.append('    try:')
lines.append("        with open(report_data_path, 'r', encoding='utf-8') as f:")
lines.append("            report = json.load(f)")
lines.append("    except Exception as exc:")
lines.append('        print(f"[data_points] 读取 report_data.json 失败: {exc}")')
lines.append("        return result")
lines.append("")
lines.append("    # 从 schema_124 回填——这是最可靠的方式")
lines.append("    schema_124 = report.get('schema_124') or []")
lines.append("    if schema_124:")
lines.append("        for item in schema_124:")
lines.append('            code = str(item.get("code", "")).strip()')
lines.append('            value = item.get("value")')
lines.append("            if not code:")
lines.append("                continue")
lines.append("            if code in USER_DATA:")
lines.append("                USER_DATA[code] = '' if value is None else str(value)")
lines.append('                result["applied"] += 1')
lines.append('        print(f"[data_points] schema_124 回填 {result[\"applied\"]} 项")')
lines.append("")
lines.append('    result["total_items"] = len(schema_124)')
lines.append("    return result")
lines.append("")
lines.append("")
lines.append("def student_meta() -> Dict[str, str]:")
lines.append('    """返回 report_data.json 中额外的学生信息。"""')
lines.append("    path = Path(__file__).resolve().parent / 'data' / 'report_data.json'")
lines.append("    if not path.exists():")
lines.append("        return {}")
lines.append("    with open(path, 'r', encoding='utf-8') as f:")
lines.append("        data = json.load(f)")
lines.append('    return data.get("student", {})')
lines.append("")
lines.append("")
lines.append("# ========================================================================")
lines.append("# 模块加载时自动回填（如果 report_data.json 存在）")
lines.append("# ========================================================================")
lines.append("try:")
lines.append("    apply_report_data()")
lines.append("except Exception as _exc:")
lines.append(f'    print(f"[data_points] apply_report_data 异常: {{_exc}}")')
lines.append("")
lines.append("")
lines.append("if __name__ == '__main__':")
lines.append("    print(f'共 {len(POINT_META)} 个 POINT_META 条目')")
lines.append("    print(f'共 {len(USER_DATA)} 个 USER_DATA 条目')")
lines.append("    filled = sum(1 for v in USER_DATA.values() if v)")
lines.append(f'    print(f"已回填 {{filled}}/{len(USER_DATA)} 个值")')
lines.append("    for code, value in USER_DATA.items():")
lines.append("        label = POINT_META.get(code, {}).get('label', '')")
lines.append(f'        print(f"  {code} {label}: {value}")')

# 写入文件
output_path = Path(__file__).parent / "data_points.py"
output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n✅ 已生成新的 data_points.py：{output_path}")
