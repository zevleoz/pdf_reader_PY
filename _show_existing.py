import json
from pathlib import Path

d = json.loads(Path("data/report_data.json").read_text(encoding="utf-8"))

print("=== Student ===")
for k, v in d["student"].items():
    print("  {:<15s} {}".format(k, v))

print("\n=== PDF Titles ===")
for t in d["pdf_titles"]:
    print("  - " + t)

total = 0
print("\n=== Sections & Groups ===")
for sec in d["sections"]:
    print("\n[{} / {}]".format(sec["title"], sec.get("subtitle", "")))
    for g in sec["groups"]:
        items = g.get("items", [])
        total += len(items)
        print("  - {} ({} items)".format(g["name"], len(items)))
        for it in items:
            val = it.get("value")
            mean = it.get("mean")
            unit = it.get("unit", "")
            grade = it.get("grade", "")
            print("      {:<28s} {:>8s} {:<4s} (avg: {:>8s} grade: {:s})".format(
                str(it.get("label", "?"))[:26],
                str(val) if val is not None else "-",
                str(unit),
                str(mean) if mean is not None else "-",
                str(grade),
            ))

print("\nTotal metrics extracted: {}".format(total))
