# P1 — Knowledge base + Y4 evidence

Model: Sonnet · 1M context: off · Wave 1 (runs in parallel with P2)

Read first: `plans-m1/README.md` (contract §1–2), `plans-m1/framework.md` (the owner's MD of 《M1 FM会前准备框架》), and spec §8a.

## You own
- `m1/__init__.py` (empty)
- `m1/kb/r4_abilities.json`
- `m1/kb.py`
- `m1/y4_evidence.py`
- `test_m1_kb.py`
- `test_m1_y4_evidence.py`

## 1. `m1/kb/r4_abilities.json`

Transcribe it from `framework.md`. Copy the wording verbatim; do not paraphrase.

```json
{
  "version": "2026-10-28",
  "source": "M1 FM会前准备框架 + R4能力说明 2.0",
  "dims": [{"id": "R1", "en": "Recognize", "zh": "识别"}],
  "abilities": [
    {
      "code": "R1.1", "dim": "R1", "name": "情绪识别与身体觉察",
      "indicators": ["011", "013"],
      "indicator_note": "",
      "gap_note": "分析与缺口 text, verbatim",
      "ask": "会议中需确认 text, verbatim"
    }
  ],
  "fixed": {
    "structure_rows": [],
    "agenda_60": [],
    "agenda_note": "",
    "principle_callout": "",
    "quick_check": [],
    "quick_check_note": "",
    "event_path_callout": "",
    "appendix_callout": "",
    "priority_note": ""
  }
}
```

Field notes:
- `dims` has four entries, R1–R4.
- `abilities` has exactly 18 entries: R1 ×4, R2 ×5, R3 ×6, R4 ×3. Names come from 《R4能力说明 2.0》 (spec §8).
- `indicators` are schema_124 codes. Map each 「相关指标」 label to its code with the labels in `data_points.py` (read it, don't edit it).
- `indicator_note` is used when the framework says 暂无直接对应指标, e.g. R1.2.
- 职业兴趣 / 职业价值观 / 能力优势 groups expand to all of their codes. For R1.4, use only the value codes the framework names.

The `fixed` entries are only the reader-facing framework text that the prototype renders. Leave out 〔AI 填写〕 instructions, 💡 示例 boxes, and the pages 「Appendix 使用规则」 and 「Y4 标准化评价与 Signal 判读」.

## 2. `m1/kb.py`

- `load_kb() -> dict`: cached, then validated.
- `validate_kb(kb)` raises `ValueError` with a clear message when:
  - there are not exactly 18 abilities, or a code is duplicated;
  - an indicator code is not in `data_points.POINT_META`;
  - `gap_note` or `ask` is empty;
  - a `dim` is unknown.
- `ability(code) -> dict`.

## 3. `m1/y4_evidence.py`

`build_y4_evidence(student_id) -> {"report_id", "date", "items": [evidence item], "six_am": {...} | None, "complete": bool}`

- Get the report with `growth_talk.y4_snapshot.latest_complete_y4`. If there is none, return `complete: false` and no items.
- For each indicator code used by any ability, look up its band:
  1. the report's own 档位 field if it has one;
  2. otherwise `evaluation_rules.derive_evaluation(code, label, raw, norm)`. Norm codes: 060-062↔125-127, 066-068↔128-130, 069-071↔131-133, as in `evaluation_rules`.
- **M1-only rules, kept in this file** (`evaluation_rules.py` is red-line):
  - 职业价值观 095–109: ≥9 高, ≥7.5 较好, ≥6.66 不低, ≥5 偏低, <5 明显偏低.
  - Out-of-range raw values, or a missing norm where one is needed → band `无法判读`. Legal ranges come from framework p.19: e.g. trust 1–50, communication 1–45, closeness 1–30, 情绪稳定性 total 0–60, sub-items 0–15, Big Five 1–5, self-concept dims 0–10, percentiles 0–100.
  - Attachment types (020–022) keep their raw text as the band, e.g. 安全型.
- Build one evidence item per indicator, using the README §2 shape:
  - `source: "y4"`, `group: "Y4"`, `kind: "indirect"`
  - `text: "<label>：<band>"`
  - `abilities`: every ability that lists the code
  - `raw` is stored but never put into `text`
- 6AM: read the latest profile for the same report, the way `blueprints/insights.py::_six_am_pick_profile` does (import it; don't modify insights). Return a short summary dict with `group: "Y4"`, or `None`.

## Tests

- The KB loads; 18 abilities; every code is valid; `validate_kb` catches each error case above.
- Bands for a fake report:
  - matches `evaluation_rules` for ordinary codes;
  - 职业价值观 bands at the boundaries 9 / 7.5 / 6.66 / 5;
  - out of range → 无法判读;
  - missing norm → 无法判读.
- No item `text` contains a digit taken from `raw`. Build the fake report in a temp DB the same way existing `growth_talk` tests do.

## Done when

`pytest -q` is green. In your report, list any framework indicator label you could not map to a code. Do not guess those.
