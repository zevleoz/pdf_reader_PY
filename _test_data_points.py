"""验证新的 data_points.py 编号和标签是否正确。"""
from data_points import USER_DATA, POINT_META, v

print(f"POINT_META: {len(POINT_META)} 项")
print(f"USER_DATA: {len(USER_DATA)} 项")
print()

print("前 10 项:")
for code in list(USER_DATA.keys())[:10]:
    label = POINT_META[code]['label']
    val = USER_DATA[code]
    print(f"  {code} {label}: {val}")

print("...")
print("后 5 项:")
for code in list(USER_DATA.keys())[-5:]:
    label = POINT_META[code]['label']
    val = USER_DATA[code]
    print(f"  {code} {label}: {val}")

print()
print(f"v('001') = {v('001')}")
print(f"v('053') = {v('053')}")
print(f"v('100') = {v('100')}")
print(f"v('124') = {v('124')}")

print()
print("分组情况:")
groups = {}
for code, meta in POINT_META.items():
    g = meta['group']
    if g not in groups:
        groups[g] = []
    groups[g].append(code)
for g, codes in groups.items():
    print(f"  {g}: {len(codes)} 项 ({codes[0]}-{codes[-1]})")

print()
print("验证每个编号的 v() 取值:")
# 验证几个关键编号是否有正确的值（从 report_data.json 回填的）
key_codes = ['001', '041', '053', '068', '072', '081', '096', '104', '119']
for code in key_codes:
    label = POINT_META[code]['label']
    val = v(code)
    print(f"  v('{code}') = '{val}'  ({label})")
