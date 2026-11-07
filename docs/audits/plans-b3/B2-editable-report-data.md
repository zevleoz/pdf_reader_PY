# B2 — Editable report data on the student dashboard

Read `README.md` in this folder first. Do not touch `generate.py`, `new_iteration/`, `extract.py` or `b3_gauge.py`.

## Goal

On the student page, the **原始数据** view of a report (`templates/students.html`, `showRawData(reportId)`) lists every data point (编号 / 指标 / 数值 / 来源). Make the 数值 column editable. Saving writes the values into the report's stored snapshot (`Report.data_json` → `schema_124[].value`). The existing **生成 PDF** button calls `POST /api/reports/<id>/regenerate`, which already rebuilds the PDF from that snapshot. After a save, it therefore prints the edited values with no change to the PDF code.

## Files you own

`db.py`, `blueprints/reports.py`, `templates/students.html`, `test_report_value_edits.py` (new).

## Steps

1. **`db.py`**: add `update_report_values(report_id: int, edits: Dict[str, str], editor: str) -> Dict[str, Any]`.
   - Load `Report.data_json`. For each `code → value` in `edits`, find the `schema_124` item with that `code`. Unknown codes are an error; reject the whole call and change nothing.
   - Value rules: strip whitespace. `""` is allowed (it clears the value). For items whose type is `number` in `data_points.py`, the value must parse as a float; otherwise reject the whole call with the code in the message.
   - Write the new value. Append one entry per changed code to `raw["edits"]` (create the list if missing): `{"code", "old", "new", "by": editor, "at": ISO time}`. Skip codes whose value is unchanged.
   - Save in one transaction. Return `{"changed": [codes]}`.
2. **`blueprints/reports.py`**: add `POST /api/reports/<int:report_id>/values` with the same decorators as `regenerate` (`@admin_required`, `@report_scoped`).
   - Body: `{"edits": {"068": "8.1", ...}}`. Return 400 with the error message on bad input, 404 if the report is missing, and `{"ok": true, "changed": [...]}` on success.
   - Editor name: use the logged-in user, the same way other routes in this file read it. If there is none, use `"admin"`.
   - Hidden raw items (`_eval_rules.is_hidden_raw`, codes 095–109) are not shown by `/raw`. Reject edits to them (400).
3. **`templates/students.html`**, inside `showRawData`:
   - Render each 数值 cell as `<input>` (keep the current look: bold, compact, right width). Escape values when building the HTML.
   - Highlight a changed cell (for example a light yellow background) and show a count: `已修改 N 项`.
   - Add the buttons **保存修改** and **保存并生成 PDF** next to `← 返回报告列表`. 保存修改 calls the new route. 保存并生成 PDF saves and, on success, calls the existing `regeneratePdf(reportId, btn)`. Both are disabled while nothing has changed.
   - After a successful save, reload the table from `/raw` so it shows the stored values, and show `已保存`. On error, `alert` the server message and keep the user's input.
   - If the user clicks 返回报告列表 with unsaved changes, `confirm('有未保存的修改，确定离开？')`.
   - Below the table, if `data.raw.edits` is not empty, show a small list: `编号 指标：旧值 → 新值（by, time）`, newest first, at most 20 entries.
   - Show the inputs and buttons only to users who may click 生成 PDF today; others see the read-only table as now.
4. **`test_report_value_edits.py`** (Flask test client + a temporary DB, following the style of existing tests such as `test_audit_data_fixes.py`):
   - Saving `{"068": "8.1"}` changes only that item and adds one `edits` entry.
   - Unknown code → 400, nothing changed. A non-number for a number item → 400, nothing changed. Hidden code 100 → 400.
   - Saving the same value twice adds no second `edits` entry.
   - After an edit, `regenerate` writes `data/report_data.json` with the new value. Monkeypatch `_generate_module.main` so no PDF is built, and read the JSON that the route wrote.

## Done when

- `python3 -m pytest -q test_report_value_edits.py test_audit_data_fixes.py test_render.py` passes.
- In the browser preview: open a student → report → 原始数据, change one value, click 保存并生成 PDF, and the downloaded PDF shows the new value. Report back with a screenshot of the edited table and the page of the PDF showing the value.
- No change to the PDF code.
