# Y4-2 学习力报告 — build contract

Written 2026-11-08. The proposal is `Y4-2-proposal.html` in this folder.

Working tree: `.worktrees/b3-new-format` (branch `b3-new-format`, = origin/main 4459e28). **Do not commit**; the reviewer commits.

## Owner decisions

| # | Decision |
|---|---|
| D1 | Name: **Y4-2 学习力报告**. File `凭远Y4-2学习力报告_<学生名>.pdf` |
| D2 | Pages: P1 总览, P2 执行功能, P3 类型定位, P4 学习方法实践, P5 学习方法明细, P6 学习策略执行 (+ P6b 17 做法明细 if it doesn't fit). **P7 习惯清单 is NOT built** (archived) |
| D3 | Show dimension scores exactly as B3 prints them; never average items to get them. Tier colour and frequency word come from the score only; the arrows B3 prints are ignored. If a dimension score differs from its items' average by more than 2.0, add a warning to `checks` (shown in the dashboard, not in the PDF) |
| D5 | Use only text that B3 prints (type descriptions, each item's 具体方法与说明). No AI-written text |
| D6 | Peer-average dot on P3 only when **both** averages for that chart are non-empty in the data (128+129 for motivation, 131+132 for methods). Otherwise no dot and no legend entry for it |
| Release | Y4-2 can be downloaded for **every report that has a B3** (new or old format). Pages without data are left out (old B3: P1 without types/134/135, and P2 only) |

The sample B3 is internally inconsistent (its dimension scores don't match its item averages, and 错题分析 appears with two scores). Build against the structure; `fixtures/b3_detail_sample.json` holds the sample's values for tests. The sample has **20** method items and **17** strategy items.

## Data contract: `raw["b3_detail"]` in the report snapshot (Report.data_json)

Only for a new-format B3. Absent for an old B3 or no B3. Y4, 6AM and the evaluation rules never read it.

```json
{
  "format": "new",
  "motivation_type": "双高型",          // printed 当前类型 on the 学习动机 page; "" if not read
  "method_type": "深度理解型",           // printed 当前类型 on the 学习方法与策略 page
  "practice_dims": [{"group": "获取与理解", "name": "主动提取", "score": 8.7}, ...],   // 5, from 学习方法实践 维度结果一览
  "practice_items": [{"dim": "主动提取", "name": "主动回忆", "desc": "学完后，合上书复述或写出课堂重点。", "score": 2.0}, ...],  // all rows of the 学习方法实践 detail table
  "exec_dims": [{"stage": "目标与计划", "name": "目标设定", "score": 6.0}, ...],      // 7, from 学习策略执行 维度结果一览; score null if blank
  "exec_items": [{"stage": "目标与计划", "name": "明确目标", "desc": "...", "score": 6.0}, ...],  // all rows of the 学习策略执行 detail table
  "checks": ["主动提取 维度分 8.7 与条目平均 3.3 相差超过 2.0", ...]
}
```
Scores are numbers (float) or null. Names, groups and descriptions are read from the PDF, never hard-coded (real reports may differ from the sample).

### Tiers (B3's printed rules)
- 0–10 scores: T5 从未使用 <3 (1–2), T4 较少使用 3–4.x, T3 有时使用 5–6.x, T2 较常使用 7–8.x, T1 高频使用 ≥9. Use: `score < 3 → T5; < 5 → T4; < 7 → T3; < 9 → T2; else T1`.
- Percentiles (063–065): T1 优势表现型 ≥90, T2 良好发展型 70–89, T3 一般发展型 40–69, T4 需要支持型 20–39, T5 重点支持型 <20.
- Colours (from B3): T5 #E0403A, T4 #F07C2C, T3 #F2B630, T2 #5CA0B0, T1 #5A9E5F.

### Editing
`POST /api/reports/<id>/values` accepts extra codes:
- `b3d.motivation_type`, `b3d.method_type` (strings)
- `b3d.practice_dims.<i>`, `b3d.practice_items.<i>`, `b3d.exec_dims.<i>`, `b3d.exec_items.<i>`: the `score` of entry *i* (0-based); must be a finite number or "" (stored as null)

These use the same validation, all-or-nothing behaviour and `raw["edits"]` log as schema codes. Unknown index or missing `b3_detail` → 400.

## Agent A — reading the new B3 (backend only)

Owns: `b3_detail.py` (new), `extract.py`, `db.py` (`update_report_values` only), `test_b3_detail.py` (new). Touch nothing else.

1. `b3_detail.py`:
   - `tier_score(score)`, `tier_percentile(p)` → (code "T1".."T5", label) per the rules above.
   - `detail_pages(pdf)` → page numbers to send: the 学习动机 page and the 学习方法与策略 page (the two pages that `b3_gauge` finds gauges on), and the four pages after the 学习方法与策略 page (14–17 in the sample). Derive them from the gauge pages so a page shift still works.
   - `build_prompt()` → a prompt asking for exactly the JSON above (without `format`/`checks`), naming each field's source on the page, with "" or null when unreadable.
   - `normalise(parsed)` → coerce types, drop unknown keys, add `format: "new"`, compute `checks` per D3.
2. `extract.py`: when a new-format B3 is present (`b3_gauge.is_new_b3`), make **one** extra vision call with those pages (reuse the existing render and `_call_vision_with_retry`-style retry; it may need a variant that accepts JSON without a `"data"` key). Put the result into the snapshot written to `data/report_data.json` as `"b3_detail"`. Confirm that `_save_report_to_db` stores that key in `Report.data_json` (follow the code path; fix only inside extract.py if needed). A failure of this call must not fail the generation: log it and leave `b3_detail` out.
3. `db.update_report_values`: support the `b3d.*` codes per the contract.
4. `test_b3_detail.py`: tier boundaries; `normalise` on `fixtures/b3_detail_sample.json` (37 items, a check for 主动提取); prompt pages derived from the sample PDF when `B3_NEW_SAMPLE` is set (skip otherwise); `extract` path with the vision call mocked (detail stored; a failed call leaves it out and generation continues); `b3d.*` edits (valid, bad index, non-number, missing block, log entry).
5. Run `python3 -m pytest -q test_b3_detail.py test_b3_gauge.py test_report_value_edits.py test_b3_three_reports.py test_pipeline.py`. Report the output and a summary of changes.

## Agent B — the Y4-2 report and its buttons

Owns: `new_iteration/render_y4_2.py` (new), `new_iteration/report_y4_2.html` (new), `blueprints/reports.py` (one new route only), `blueprints/students.py` (reports list flag only), `frontend/src/pages/profile/FilesTab.tsx`, `frontend/src/pages/profile/Y4Tab.tsx`, `static/app/**` (via `npm run build` in `frontend/`), `test_y4_2_report.py` (new). Touch nothing else, and in particular not `report_v2.html` / `render_v2.py` / `generate.py`.

1. **Template** `report_y4_2.html`: A4 pages, same page shell, fonts, header (学习力 section, APP·ARK branding from `new_iteration/branding`, which is git-ignored and present locally) and 学习力 green as `report_v2.html`. Copy the needed CSS; don't import it. Pages per D2, laid out as in `Y4-2-proposal.html`:
   - P1 总览: name/grade/test date header; 3 EF percentiles with tier badges; 学习动机 type + 深层/表面 scores; 学习方法 type + scores; 134/135 with tier. Leave out any card whose data is missing (old B3: no types, no 134/135).
   - P2 执行功能: per EF, the percentile on a five-colour band with T labels and the tier name.
   - P3 类型定位 (only if a type exists): two 2×2 quadrants (axes 0–10, split at 5), the student's dot from 066/067 and 069/070, peer dot per D6, the type name. Quadrant names: motivation 内驱型 (high deep, low surface), 双高型, 外驱型 (low deep, high surface), 低动机型; methods 深度理解型, 双高整合型, 表层任务型, 低策略型. Type description text: leave a slot, filled only if the data has it (we don't read it yet). Don't invent it.
   - P4 学习方法实践 (only with b3_detail): 134 on the five-band scale; the practice dims as bars, grouped by `group`.
   - P5 学习方法明细: all practice items grouped by `dim`: name, desc, 10-cell bar coloured by tier, frequency word.
   - P6 学习策略执行: 135 on the scale; the four PDCA stages with their exec dims (null → "—"); the exec items in the same 10-cell format (spill onto P6b if needed).
   - Footer on each page: "数据来源：B3 核心学习能力报告".
2. `render_y4_2.py`: `build_context(raw)` (pure; uses schema values 063–067, 069–070, 128–132, 134, 135 and `b3_detail`) and `render_pdf(raw, out_pdf)` (Jinja → HTML → `render_v2.find_chrome()` headless print, same flags as `render_v2.main`). It must not read or write `data/report_data.json`.
3. Route `POST /api/reports/<int:report_id>/y4-2` (`@admin_required`, `@report_scoped`, like regenerate): loads the snapshot from the DB, 400 if the report has no B3 data (no `B3` in `pdf_titles` and no non-empty 063–071/134/135), renders to `OUTPUT_DIR/凭远Y4-2学习力报告_<safe name>.pdf`, and returns it as an attachment with a UTF-8 filename like regenerate does.
4. `students.py` reports list: add `has_b3` per report (same rule as the route).
5. `FilesTab.tsx`: under each report's Y4 综合报告 row, a row "Y4-2 学习力报告 · PDF" with 下载 (writers only), shown only when `has_b3`. Use the same download helper pattern as `regenerate`.
6. `Y4Tab.tsx` editor: when `/raw` returns `b3_detail`, add a second section "Y4-2 明细（B3）" below the schema rows: type strings and every dim/item score as inputs with the `b3d.*` codes; changed-highlight, save and log behave as the existing rows (same `edits` POST). Show `b3_detail.checks` above it as warnings. Also add a **保存并生成 Y4-2** button next to 保存并生成 PDF when the report has B3 data.
7. `npm ci && npm run build` in `frontend/` (typecheck must pass).
8. `test_y4_2_report.py`: `build_context` with the fixture (new B3: 6–7 pages; peer dot present when 128/129 set, absent when blank; P7 absent); old B3 (no b3_detail, no types): only P1+P2 and no type text; no B3 → route 400; route returns a PDF with Chrome mocked or real (skip when Chrome or branding is missing); `has_b3` flag.
9. Run `python3 -m pytest -q test_y4_2_report.py test_render_v2_slots.py test_report_value_edits.py`. Report the output, a summary, and screenshots of P1, P3, P5 and P6 rendered from the fixture (save the PNGs under the scratchpad given in your brief).
