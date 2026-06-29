"""检查 generate.py 中 v() 调用的编号与 report_data_124.txt 是否一致。"""
import re
from pathlib import Path

# 1) 读取 generate.py 中所有 v("xxx") 调用
generate_path = Path(__file__).parent / "generate.py"
gen_content = generate_path.read_text(encoding="utf-8")
v_calls = set(re.findall(r'v\("(\d+)"\)', gen_content))

# 2) 读取 report_data_124.txt 中所有编号
report_path = Path(__file__).parent / "data" / "report_data_124.txt"
report_items = {}
for line in report_path.read_text(encoding="utf-8").splitlines():
    m = re.match(r'^(\d+)\s+(.+?):\s*(.*)$', line)
    if m:
        code, label, value = m.group(1), m.group(2), m.group(3)
        report_items[code] = (label, value)

# 3) 读取 data_points.py 中 POINT_META 的定义
data_points_path = Path(__file__).parent / "data_points.py"
dp_content = data_points_path.read_text(encoding="utf-8")
reg_calls = re.findall(r'_reg\("(\d+)",\s*"(.+?)"', dp_content)
meta_labels = {code: label for code, label in reg_calls}

print("=" * 80)
print("generate.py 中使用的编号（v("") 调用）:", sorted(v_calls))
print("共", len(v_calls), "个编号")
print()

print("report_data_124.txt 中的编号:", sorted(report_items.keys()))
print("共", len(report_items), "个编号")
print()

print("POINT_META 中注册的编号:", sorted(meta_labels.keys()))
print("共", len(meta_labels), "个编号")
print()

# 检查差异
all_codes = set(report_items.keys()) | set(meta_labels.keys()) | v_calls
print("\n=== 交叉检查 ===")
print()
print("1) generate.py 使用但 report_data 中没有:")
for code in sorted(v_calls - set(report_items.keys())):
    label = meta_labels.get(code, "???")
    print(f"  {code} ({label})")
print()
print("2) report_data 中有但 generate.py 未使用:")
for code in sorted(set(report_items.keys()) - v_calls):
    label, value = report_items[code]
    print(f"  {code} {label} = {value}")
print()
print("3) 编号在 report_data 与 meta 中标签不一致:")
for code in sorted(all_codes):
    if code in report_items and code in meta_labels:
        rl, rv = report_items[code]
        ml = meta_labels[code]
        if rl != ml and not (rl.startswith(ml) or ml.startswith(rl)):
            print(f"  {code}: report_data='{rl}' vs meta='{ml}'")
print()

# 4) 显示 generate.py 中每个编号引用的值
print("\n=== generate.py 中编号实际取到的值 ===")
# 先从 data_points 加载 USER_DATA
import importlib.util
spec = importlib.util.spec_from_file_location("data_points", data_points_path)
dp_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp_mod)

for code in sorted(v_calls):
    value = dp_mod.USER_DATA.get(code, "NOT FOUND")
    label = meta_labels.get(code, "???")
    r_label, r_value = report_items.get(code, ("-", "-"))
    print(f"  {code:>4} {label:<30} USER_DATA='{value}'  report_data='{r_value}'  ({r_label})")
    if value != r_value and r_value != "-":
        print(f"       ⚠️  MISMATCH!")
