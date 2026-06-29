from fake_data import build_fake_report
r = build_fake_report()
for i, sec in enumerate(r['sections']):
    print(f"sec{i}: title={sec['title']}, groups len={len(sec['groups'])}")
    for j, g in enumerate(sec['groups'][:2]):
        print(f"  group{j}: title={g.get('title','')}, items={len(g.get('items', []))}")
        for k, item in enumerate(g.get('items', [])[:1]):
            print(f"    item{k}: {item}")
    # show all group titles
    titles = [g.get('title', '') for g in sec['groups']]
    print(f"  group titles: {titles}")
    print()
