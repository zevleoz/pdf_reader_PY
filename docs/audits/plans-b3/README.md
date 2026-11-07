# B3 new format + editable report data

Written 2026-11-07. Owner's asks:

1. B3 input files now come in two versions (old and 2026-11 新版). The system must tell which one it is reading and still fill the same Y4 data points.
2. After a report is read, its scores show on the student dashboard. Make them **editable**, so a wrong value can be fixed by hand. **生成 PDF** must then use the edited values.
3. 自我效能感 and 学习自我调节 are legacy items from the old B3. For the new B3, fill them from the new sections (mapping below). More changes will follow later.
4. Make sure the Y4 report can still be generated from three input reports.

**Hard rule (owner):** do not change Y4 PDF generation (`generate.py`, `new_iteration/render_v2.py`, `new_iteration/report_v2.html`). All work is in reading the inputs, storing the data and the dashboard.

## What is already done (uncommitted in the working tree)

| Item | Where | State |
|---|---|---|
| Old vs new B3 detection | `b3_gauge.is_new_b3()`: the new B3 has two half-ring charts of a fixed size | Checked: the new sample → new; all 63 old B3 PDFs in `~/Downloads` → old |
| Page choice for the new B3 | `extract._render_pages_for_vision`: new B3 → pages 3, 4, 6, 8, 10, 12, 14, 16 | The new B3 text layer is scrambled, so keyword page picking found nothing |
| Peer averages 128/129/131/132 | `b3_gauge.read_gauges()` measures the dashed 同龄群体均值 line from the chart pixels. It is used only if the measured scores match the printed scores within 0.2 | Sample: 6.4 / 5.8 / 6.1 / 5.2. Scores reproduce the printed values within 0.1 |
| 068/071/130/133 | Currently set to blank for the new B3 | **B1 changes this** |
| Tests | `test_b3_gauge.py` (set `B3_NEW_SAMPLE=<pdf>` to run the real-PDF test) | Passing |

`extract.py` also carries the owner's earlier, uncommitted change that removes the hard-coded DashScope key. **Owner to confirm** it is committed together with B1.

## Decisions (owner, 2026-11-07)

| # | Topic | Decision |
|---|---|---|
| D1 | New B3 → legacy items | **学习策略执行与优化 score → 071 学习自我调节. 学习方法实践与提升 score → 068 自我效能感.** Applies to the new B3 only; the old B3 is read as before |
| D2 | Peer averages for those two (130, 133) | **Leave blank.** The new pages have no average. Nothing is invented; a value can be typed in through the editable dashboard |
| D3 | Version detection | Automatic, per file, from the PDF itself (no user choice) |
| D4 | Where editing lives | The 原始数据 table on the student page (`templates/students.html`, `showRawData`), which already lists every data point of a report. 生成 PDF already rebuilds from the stored snapshot (`/api/reports/<id>/regenerate`), so saving edits into that snapshot is all it needs |

## Plans

| Plan | What | Files it owns | Depends on |
|---|---|---|---|
| [B1](B1-new-b3-mapping.md) | Read 学习策略执行 / 学习方法实践 into 071 / 068 for the new B3 | `b3_gauge.py`, `extract.py`, `test_b3_gauge.py` | — |
| [B2](B2-editable-report-data.md) | Editable 原始数据 table + save + 生成 PDF from the edited data | `db.py`, `blueprints/reports.py`, `templates/students.html`, `test_report_value_edits.py` (new) | — |
| [B3](B3-verify-three-reports.md) | Check: Y4 from three inputs, old B3, new B3, edited data | Tests only (`test_b3_three_reports.py`, new) | B1 and B2 merged |

B1 and B2 touch different files and can run at the same time. B3 runs last.

## Known limits (tell the owner, do not fix here)

- With 130/133 blank, `render_v2` prints the average as `-`, but `avg_pct` falls back to 0. If the template draws an average marker at 0, it will show at the left edge. Hiding it is a renderer change, so it is **not** in these plans. B3 reports whether it happens.
- AI outputs already made from a report (AI 解读, 6AM, Y4 signals) are not redone after an edit. B2 only makes the PDF use the edited values.
