# B3 — Check: Y4 from three reports, old and new B3, edited data

Run after B1 and B2 are both merged. Read `README.md` in this folder first. **Tests and a short report only. Do not change product code.** If something fails, report it with the output and stop.

## Background

Commit `061f1fa` made the Y4 v2 report work with missing input PDFs: each input slot (A2/B3/B4/B6) keeps its own pages, and a missing PDF removes its pages. Slots come from `pdf_titles` in the snapshot, or are inferred from filled values for old snapshots (`new_iteration/render_v2.py`).

## File you own

`test_b3_three_reports.py` (new). No other file.

## Checks (no vision API calls; build snapshots by hand)

1. **Three reports, no B6.** Build a `report_data.json`-style snapshot with A2, B3 and B4 values filled and every B6 code blank (base it on `fake_data.py`). Render v2 the same way `test_render_v2_slots.py` does. Assert that it renders without error, that no B6 page or career section divider is present, and that the A2, B3 and B4 pages are present.
2. **Three reports, no A2** and **no B4**: same as check 1 for each case.
3. **New-format B3 values.** Same as check 1, but set 068 = `8.1`, 071 = `7.1`, 130 = `""` and 133 = `""`. Assert that the 学习动机与策略 page shows `8.1` for 自我效能感 and `7.1` for 学习自我调节, and `-` for both averages. Also record (do not assert) whether an average marker is drawn at 0 for those rows. Owner decision D2 may need a follow-up.
4. **Old B3 still on the old path.** If `~/Downloads/B3 核心学习能力_*.pdf` exist, assert `b3_gauge.is_new_b3()` is False for every one of them and that `extract._build_slot_prompt("B3")` has no `学习方法实践与提升`. If the new sample path is given in `B3_NEW_SAMPLE`, assert it is detected as new. Skip when the files are missing (they hold student data and are not committed).
5. **Edited data reaches the PDF.** With the Flask test client: create a report, `POST /api/reports/<id>/values` with `{"066": "9.9"}`, then `POST /regenerate` with `_generate_module.main` monkeypatched to render v2 HTML only. Assert that `9.9` appears on the 学习动机与策略 page.

## Done when

- `python3 -m pytest -q test_b3_three_reports.py test_b3_gauge.py test_report_value_edits.py test_render_v2_slots.py` passes. Paste the output.
- A short note to the owner: which checks passed, which were skipped and why, and the answer to the marker question in check 3. Include a screenshot of that page if a marker is drawn at 0.
