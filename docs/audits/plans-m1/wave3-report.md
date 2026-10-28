# M1 wave 3 — Opus check (2026-10-28)

Scope:
- Ran the real DashScope model on 3 fictional students in throwaway DBs (no real student data was sent).
  - A: all sources
  - B: Y4 only
  - C: parent and Case Review contradict
- Tuned prompts and pipeline.
- Walked every screen as admin / two advisors / viewer.
- Rendered the print page to A4.

Result: **740 tests pass**. All findings below are fixed in the working tree on `m1-prep` (uncommitted).

## Findings and fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Blocker | Every real generation failed at the last step. The "no raw scores" check flagged any digit equal to a Y4 score (e.g. 6, 4), and those digits appear in R4, 60 分钟, dates. | `m1/validate_doc.py`: a number is a leak only right after its own indicator name or before 「分」. Leaks are removed, not fatal. 2 tests. |
| 2 | Blocker | `.gitignore` ignores `*.json`, so `m1/kb/r4_abilities.json` (and the fixture) would never be committed or deployed. | Negations added for `m1/kb/*.json` and `fixtures/m1_doc_sample.json`. |
| 3 | High | The KB was transcribed from the prototype, not the framework (`framework.md` was never added). Gap notes and questions were abridged; indicator lists were incomplete (R3.5 had 4 of 11). | All 18 rows rebuilt **verbatim** from the framework PDF Appendix; indicators mapped to schema_124 codes. |
| 4 | High | 2.1 was 「信息不足」 everywhere (potential/interference undefined in the prompt). `recommend` was used backwards: it ticked abilities with *missing* evidence and unticked ones with real events. | `m1/prompts.py` rewritten: field definitions, the framework's selection rules, length limits, no ids in text, no scores, list of sources this student actually has. |
| 5 | High | Priority was driven by how many items the model cited. Y4-only students got 5 priorities with 「证据不足」 hypotheses. | Score on the student's own behaviour (`kind = direct`) only. Y4-only abilities need a concern band and fill at most 2 slots. At most 2 per R dimension. 4 tests. |
| 6 | High | Ability tags were guessed from bare codes, and the tags decided which evidence each dimension saw (the rumination quote never reached R2). | Extraction gets ability names. Every real-situation item goes to all four dimension calls; only Y4 is filtered by the KB mapping. |
| 7 | Medium | Teacher first-hand observations in Case Review could never become a 3.2 event (my P3 brief listed only FT/parent/other). | Case Review `direct` items allowed as events; its hypotheses still never are. |
| 8 | Medium | 3.3 backup questions were the framework's third-person mentor prompts. The 2.3 "conflict" compared two Y4 scales. Some questions were leading (「……吧？」). | The plan prompt writes student-facing backup questions (fallback is labelled 「导师参考：」). Code drops a conflict that names no non-Y4 source. Leading phrasing is banned in the prompt. |
| 9 | Medium | 1.2 「会前提取信息」 showed the first lines of the raw upload. | Built from the extracted evidence texts. |
| 10 | Medium | P4: the AI / 已修改 / 导师 markers were missing on 35 of 58 blocks (the marker was appended to a throwaway wrapper). | `static/m1/m1_doc.js` `blockWrap()`. |
| 11 | Low | A final prep showed 「导师审核 —」 (the page read the draft row); 「从 18 项中添加」 stayed active when locked. | `blueprints/m1.py` `_detail` uses the final row; the picker is disabled when final. |
| 12 | Low | An advisor account with an empty advisor name matched every unassigned student. | `m1/store.py`: empty name owns nobody. 1 test. |
| 13 | Speed | Generation took ~2.5 min. | The four dimension calls now run in parallel: ~50 s (Y4 only) to ~105 s (all sources). |

## Verified

- **Access** (live server):
  - admin sees 3 preps;
  - each advisor sees only their own students and gets 403 on the other's;
  - the viewer gets 403 on every page and API, and the nav item is hidden;
  - cross-advisor edit returns 403.
- **Review flow:**
  - untick a priority → the sync prompt appears;
  - edit → autosave (PUT 200) → survives reload, marker 已修改;
  - finalize → locked;
  - reopen → new draft.
- **Phone:** at 390 px wide there is no horizontal scroll on home, review or sources.
- **Print:**
  - A4 in Chrome: the 🧭 title, 「｜」 headings, grey-header tables, 💡/🗣️/📋 callouts, the red 3.3 heading;
  - footer 「M1 FM会前准备框架 · 学生」 + page number;
  - no markers, no buttons;
  - 12 pages for student A (the verbatim Appendix is longer than the prototype sample).
- **AI content** (final run, `docs/audits/m1-screens/wave3/*_doc.json`):
  - quotes verified against the sources;
  - Case Review guesses kept as hypotheses;
  - no ids or raw scores in the text;
  - real events only, with an open-exploration theme for the Y4-only student;
  - the right 2.3 conflicts: Y4 vs parent for A, and for C, parent 「从来不发脾气」 vs the teacher's basketball observation.

## Open items (not done)

1. **Commit.** Everything above is uncommitted on `m1-prep`.
2. **DashScope key.** The runs used the fallback key in `extract.py`, which is the literal exposed on the public GitHub repo. Rotate it and set `DASHSCOPE_API_KEY` in `.env.production` before M1 goes live.
3. **Model variance.** Events and priorities differ a little between runs (expected). Mentors can edit everything.
4. **Not reproduced.** Once, the finalize click saved but the screen didn't refresh until reload (probably a race with a pending autosave). Watch for it in the first real use.
5. **Team check.** Confirm the framework Appendix is the latest Mapping (the KB is now verbatim from it). The team should review the first 3 real preps.
6. **Deploy.** Not deployed. Before production: merge to `main`, then server pull + restart; the tables auto-create at startup.
