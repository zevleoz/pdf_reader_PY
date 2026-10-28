# P3 — AI generation pipeline

Model: Sonnet · 1M context: **on** · Wave 2 (runs in parallel with P4) · Needs P1 and P2 merged

Read first:
- `plans-m1/README.md`, contract §2 and §4
- spec §5–6
- `framework.md`
- `growth_talk/analysis.py` (`call_model` and its DashScope config)
- `growth_talk/jobs.py` (the subprocess job pattern)

## You own

- `m1/pipeline.py`
- `m1/prompts.py`
- `m1/validate_doc.py`
- `m1/jobs.py`
- `test_m1_pipeline.py`
- `test_m1_validate.py`
- `blueprints/m1.py`: add only the two routes `POST /api/m1/preps/<id>/generate` and `GET /api/m1/jobs/<job_id>`, in a clearly marked block.

## Steps (`m1/pipeline.py`, `generate(prep_id) -> version_id`)

Step outputs are JSON. Every AI call goes through one helper, `_ask(prompt, schema_name)`. The helper calls `growth_talk.analysis.call_model`, parses the JSON, and retries once on a parse error. Tests replace the helper with a fake.

**A. Evidence**

1. Y4 items: `m1.sources.auto_sources(...)['y4']`. No AI.
2. Questionnaire items: one per dimension, grouped. No AI.
3. Each text source (parent, First Touch, Case Review, other): one AI call that returns items with a `quote`.
4. Validator: drop any item whose `quote` is not a substring of the source text after whitespace normalisation.
5. Case Review items:
   - `kind` = `hypothesis` unless the AI marked the item as an independent observation **and** the quote is a first-hand observation;
   - observations stay in the Case Review source's group.

**B. Per ability.** Four calls, one per dimension. The input is the KB ability rows plus the relevant evidence items. The output for each ability:

```
{code, potential[], interference[], known, new_clues, contradictions[], missing[],
 check_text, recommend, reason, cites[]}
```

- `cites` must name existing evidence ids; drop statements without valid cites.
- An ability counts as "supported" only when it has two different `group`s. Y4 and 6AM are one group.

**C. Priority.**
1. Code score per ability: impact, P/I present, conflict present, parent concern, Case Review hypothesis, gap importance (from B).
2. Take the top 3–5 with `recommend` true. Fewer than 3 is allowed when evidence is thin.
3. One AI call writes `hypothesis` and `why` for the chosen abilities.

**D. Meeting plan.** One AI call.
- Events: 1–2 for 60 min, 2–3 for 75/90 min. Each event must cite an evidence item whose `kind` is `direct` or `context` and whose source is FT, parent or other. With no such item, output one 开放探索主题 with no invented event.
- 2–4 open questions per event.
- Backups only for priority abilities that no event covers.
- 3.4 growth wish and next directions.
- Dimension summaries for 2.1 and 2.3.

**E. Assemble.**
1. Build the README §4 doc. Every AI text becomes a block with `origin: "ai"` and `ai_text` equal to `text`.
2. Set `flags.insufficient` from source statuses.
3. Run `validate_doc`.
4. Save an `ai_draft` version plus a fresh `edit` copy, and set the prep status to `review`.

**Safety.** Before step A runs, scan all source text:
1. A keyword list (self-harm, suicide, abuse, crisis words in Chinese; keep it in `prompts.py`).
2. If any keyword hits, one AI yes/no check on the hits.
3. A confirmed hit goes into `flags.safety` with `source_ref`.

The pipeline never writes a diagnosis.

## `m1/validate_doc.py`

- `scan_placeholders(doc)`: any 〔, 〕, `AI 填写`, `待分析`, `TODO` → error.
- `check_priority_coverage(doc)`: each `priority.code` is in some `events[].abilities` or `backups[].code`.
- `check_no_raw_numbers(doc, evidence)`: no Y4 `raw` value appears in any block text.

## Prompts (`m1/prompts.py`)

- Chinese.
- Each prompt states: use only the given items, cite ids, never invent events, Case Review interpretations of Y4 are hypotheses, Y4 bands are not R4 levels, no diagnosis, plain text only, output JSON matching the schema.
- Keep the prompts short. Opus tunes them in wave 3, so put each prompt in one named constant.

## Jobs

`m1/jobs.py` mirrors `growth_talk/jobs.py`: a subprocess, a JSON status file, and a step list for the UI with `{step, label, state, seconds}`.

The generate route:
- refuses when the prep is already `generating`;
- sets the prep status to `generating`;
- returns `{job_id}`.

On failure the job sets the prep status back to its previous value and reports a readable error.

## Tests (fake `_ask`, no network)

Run these 3 fictional students:

| Student | Sources | Expected |
|---|---|---|
| a | All sources | Full doc with no placeholders; priorities covered |
| b | Y4 only | 开放探索主题; insufficient flags; 0–3 priorities allowed |
| c | Parent and Case Review contradict each other | A conflict appears in `special.conflict` |

Also test:
- a fabricated quote is dropped;
- a Case Review statement based on Y4 becomes a hypothesis;
- 6AM never counts as a second group;
- a safety keyword hit sets the flag and blocks finalize (through P2's route);
- no raw numbers appear in the doc.

## Done when

`pytest -q` is green. Hand Opus a `scripts/m1_dry_run.py` that runs `generate` against a temp DB copy with the real model, so the wave-3 review can run it.
