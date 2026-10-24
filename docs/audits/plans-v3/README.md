# First Touch 3.0 — agent plans

Design spec: `../first-touch-v3-prototype.html` (clickable; open it in a browser). Each plan below is self-contained with the shared rules inlined. Hand one file to one agent.

## Owner requests these implement (2026-10-24)
1. Student 360: remove "Growth Talk", show First Touch → **V5**
2. First Touch starts and ends on this platform; any student with a completed Y4 can start immediately with Y4 prefilled; Yuguo delegation removed → **V2, V3a, V4a**
3. AI features use the project's DashScope key → **V1**
4. Rework the interface and logic as a quick, in-meeting tool → **V3a, V3b, V4b** (per the prototype)

## Order

| Wave | Plans (parallel within a wave) | Wait for |
|---|---|---|
| 1 | **V1** AI provider · **V2** remove Yuguo + Growth Talk 1.0 UI · **V3a** session model + Y4 start | — |
| 2 | **V3b** wrap-up & report backend · **V4a** student list, nav, guide · **V5** student 360 | V3a (all three); V1 (for V3b) |
| 3 | **V4b** workspace rewrite | V1, V3a, V3b |
| 4 | **V6** fix-ups from the end-to-end review | everything above |

File ownership never overlaps within a wave. V3a then V3b share `blueprints/copilot.py` / `growth_talk/copilot.py`, so they run in sequence.

## What gets removed
Yuguo/CRM integration (routes, client, tests, junction schemas), manual add student, import-from-Y4 dialog, entry-choice screen, the seven-phase UI and its script fields, the AI career-calibration step, the standalone chat center pages (chat APIs stay for the in-workspace drawer), the Growth Talk 1.0 workspace page (report downloads stay). **No tables or rows are dropped.**

## Notes for the owner
- **API key — act now.** V1 reuses the DashScope key the platform already uses (`DASHSCOPE_API_KEY`, falling back to the default hard-coded in `extract.py`). That literal is in `extract.py` on GitHub, and `zevleoz/pdf_reader_PY` is a **public** repository, so the key is exposed. Rotate it in the DashScope console, put the new key in `DASHSCOPE_API_KEY` in `.env` (local) and `.env.production` (server), and decide whether to remove the literal from `extract.py` (a red-line file, so it's your call) or make the repo private. Rotating doesn't block any plan here.
- **Test data.** Your local DB has ~860 partial test "reports" for 测试学生 (Y4-0002). V3a ignores incomplete reports when deciding who can start.
- **Release.** Production still runs pre-First-Touch code. After these waves, review on a local copy again before any deploy.

## After all waves (orchestrator check)
Full pytest. Then on a DB copy:
1. Open a student with a Y4 → ① shows the snapshot.
2. Generate talking points → real DashScope call works.
3. ② keyboard capture, board scoring, reload persists.
4. Two-tab conflict banner.
5. ③ without transcript → confirm v1 → appears on 360.
6. Upload a transcript → suggestions → accept/ignore.
7. Viewer read-only.
8. No Yuguo anywhere.
9. A student without a Y4 can't start.
