from fake_data import build_fake_report
r = build_fake_report()
for i, sec in enumerate(r['sections']):
    print(f"\n=== sec{i}: {sec['title']} ({len(sec['groups'])} groups) ===")
    for j, g in enumerate(sec['groups']):
        labels = [item.get('label','') for item in g.get('items',[])]
        values = [item.get('value','') for item in g.get('items',[])]
        means = [item.get('mean','') for item in g.get('items',[])]
        maxes = [item.get('max','') for item in g.get('items',[])]
        grades = [item.get('score_grade','') for item in g.get('items',[])]
        units = [item.get('unit','') for item in g.get('items',[])]
        print(f"  group{j}: labels={labels}")
        print(f"           values={values}")
        print(f"           means ={means}")
        print(f"           maxes ={maxes}")
        print(f"           grades={grades}")
        print(f"           units={units}")
