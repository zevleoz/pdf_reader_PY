# B1 — New B3: fill 068 / 071 from the new sections

Read `README.md` in this folder first. Do not touch `generate.py`, `new_iteration/`, or any template.

## Goal

For a **new-format** B3 only:

| Code | Y4 label (unchanged) | Value taken from (new B3) | Sample value |
|---|---|---|---|
| 068 | 学习动机-自我效能感 | 学习方法实践与提升 page (sample page 14), the 测评结果 card: `得分 X/10`, take X | 8.1 |
| 071 | 学习方法与策略-学习自我调节 | 学习策略执行与优化 page (sample page 16), the 测评结果 card: `得分 X/10`, take X | 7.1 |
| 130, 133 | their 常模平均数 | none → always `""` | `""` |

The old B3 must behave exactly as today (same prompt text, same results).

## Files you own

`b3_gauge.py`, `extract.py`, `test_b3_gauge.py`. Nothing else.

## Steps

1. **`b3_gauge.py`**
   - `DROPPED_CODES` becomes `("130", "133")` (068/071 are no longer dropped).
   - Add a dict `NEW_LAYOUT_PROMPT_LINES` that maps a code to the replacement schema line used for the new B3. Each line must still match `extract._SCHEMA_ITEM_LINE_RE` (`^NNN <desc> number（B3…）$`):
     ```
     068 学习方法实践与提升-得分 number（B3，"学习方法实践与提升报告"页右侧"测评结果"卡片中"得分 X/10"的 X）
     071 学习策略执行与优化-得分 number（B3，"学习策略执行与优化报告"页右侧"测评结果"卡片中"得分 X/10"的 X）
     128 学习动机-深层动机常模平均数 number（B3，新版不印此数字，一律输出 ""）
     129 … 133   (same wording, one line each, keeping each code's original label)
     ```
   - Update the module docstring: the new B3 maps 学习方法实践→068 and 学习策略执行→071 (owner decision 2026-11-07).
2. **`extract.py`**
   - `_build_slot_prompt(slot, new_b3: bool = False)`: when `slot == "B3"` and `new_b3`, replace the line of each code found in `b3_gauge.NEW_LAYOUT_PROMPT_LINES`. Keep the order and the count `n` unchanged. Default behaviour (old B3 and all other slots) must give byte-identical output to today.
   - In `extract_124_points_with_vision`, before building the B3 prompt, compute `new_b3` = any input PDF with `_pdf_slot(pdf) == "B3"` and `b3_gauge.is_new_b3(pdf)`, and pass it.
   - In `_apply_new_b3_gauges`, change the last print to say that 130/133 are blank because the new B3 has no average for these items. Remove the claim that 068/071 are blanked.
3. **`test_b3_gauge.py`**
   - Update `test_norms_taken_when_scores_agree`: 068/071 keep the vision values (`"7.7"`, `"6.6"` in the test input); 130/133 are `""`.
   - Add `test_prompt_old_b3_unchanged`: `extract._build_slot_prompt("B3")` equals `extract._build_slot_prompt("B3", new_b3=False)` and contains `068 学习动机-自我效能感`.
   - Add `test_prompt_new_b3`: with `new_b3=True` the prompt contains `学习方法实践与提升` on the 068 line and `学习策略执行与优化` on the 071 line, and still has 15 item lines.

## Done when

- `python3 -m pytest -q test_b3_gauge.py test_pipeline.py test_render.py test_render_v2_slots.py` passes.
- `B3_NEW_SAMPLE=<path to B3（新版）报告样本.pdf> python3 -m pytest -q test_b3_gauge.py` passes (ask the owner for the file; it holds student data and must not be committed).
- No change to the prompt text for the old B3.
- Report back: the diff summary and the test output. Do not run the real vision API (costs money); the owner runs it.
