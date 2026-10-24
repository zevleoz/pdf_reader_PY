# V3a · Three-step session model, start from Y4, Y4 snapshot

Wave 1 · Backend track, step 1 of 2 (V3b follows; V4a, V4b and V5 build on this contract).

## Rules for this task (read first)

- Repo: `/Users/jefflau/projects/pdf_report_converter/PDF_converter` (git, branch `first-touch-merge`). Python: `/Users/jefflau/anaconda3/bin/python`.
- **Design spec:** `docs/audits/first-touch-v3-prototype.html`. Open it in a browser; it's a clickable prototype of the new flow, and its right-hand "logic notes" column states the rules each screen must follow. Where this plan and the prototype disagree, this plan wins.
- Background: `PRODUCT.md` (one level up) and `docs/audits/plans-v3/README.md`.
- **Edit only the files listed under "Files you own".** Other agents work in this same checkout at the same time.
- Commit only your own files, by explicit path: `git add <your files> && git commit -m "<message>"`. Never `git add -A`, `git add .`, `git stash`, `git reset`, `git checkout -- .`, or anything that touches other people's changes. Don't push.
- Never edit red-line files (spec `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md` §2): `extract.py`, `generate.py`, `data_points.py`, `validate.py`, `gauge_reader.py`, `gauge_processor.py`, anything in `new_iteration/`, deploy files, `/api/v1/*` contracts. Importing from them is fine.
- Flask + Jinja + Alpine.js (CDN). No Node, npm or build step. UI copy is Chinese, in the existing tone.
- **Never read from or write to `data/y4_students.db`** (real student data). Tests use their own fixtures. For manual browser checks, use a copy: `sqlite3 data/y4_students.db ".backup '/tmp/<you>/ft.db'"`, then `DATABASE_URL=sqlite:////tmp/<you>/ft.db SECRET_KEY=dev PORT=<free port> python app.py`. The copy already contains admin, advisor and viewer accounts; ask the owner for logins, or create throwaway ones on the copy with `db.create_user(...)`.
- **Never print, log, commit or copy an API key value.** Refer to keys only by their environment-variable name.
- Don't drop database tables or delete rows. Removing a feature means removing its routes, UI and code, not its stored data.
- Reuse fixtures from `test_copilot_routes.py` / `test_copilot_gapfixes.py` (`client`, `login_as`, `qdb`, `_inline_jobs`). Put new tests in the new test file named below. When you remove a feature, delete or update the tests that only covered it, and list them in your report.
- Done = your new tests pass, `python -m pytest -q --ignore=new_iteration` is fully green, and you committed. If another agent's in-progress edit breaks an unrelated test, say so in your report instead of "fixing" their file.
- Final report: files changed, commit hash, test counts, removed tests, and anything you couldn't do.

## Owner decisions
- First Touch starts and ends on this platform: **any student with a completed Y4 assessment can start a session right away, with the Y4 data already filled in.** No external approval, no manual student creation inside First Touch.
- One session per student (already implemented), Viewer read-only (already implemented). Keep both.
- The flow shrinks from 7 phases to **3 steps**: ① 会前准备, ② 会谈记录, ③ 会后整理 (see the prototype).

## Files you own
- `blueprints/copilot.py`, `growth_talk/copilot.py`, `growth_talk_store.py`, `growth_talk/jobs.py`
- New: `growth_talk/y4_snapshot.py`, `test_ft_v3_session.py`
- Existing First Touch tests that assert removed behaviour (update or delete, and list them)

**Not yours:** templates (V4a/V4b), `growth_talk/copilot_report.py` / `report_contract.py` (V3b), `growth_talk/analysis.py` (V1).

## 1. "Completed Y4" and the snapshot (`growth_talk/y4_snapshot.py`)
Y4 reports live in `reports` (`db.Report`). `data_json` is `{"student": …, "schema_124": [ {code, label, value, type, …}, … ]}` with **string values**. Some rows are partial test data with only three points, so presence of a row isn't enough.
- `latest_complete_y4(student_id) -> Report | None`: newest report (by `report_date`, then `id`) whose `schema_124` contains code `072` with a non-empty value **and** at least 4 of codes `073–078` numeric.
- `build_snapshot(report) -> dict`, pure and deterministic, **no AI**:
  ```
  {"reportId", "reportDate",
   "hollandCode": "SAE",                       # 072, letters only
   "riasec": [{"key":"R","label":"现实型","score":2.0}, … 6 items, order R I A S E C],  # 073–078
   "topAbilities": [{"label":"语言能力","score":6.0}, … top 3],      # 079–094, label = text after "能力优势-"
   "weakestAbility": {"label", "score"},
   "topValues": [{"label":"创造发明","score":5.0}, … top 3],          # 095–124, label after "职业价值观-"
   "topicSuggestions": ["科学实验", …]}                                 # see below
  ```
  Parse numbers with `float()`, skipping blanks and non-numbers. Ties: keep schema order. Check codes and labels against `data_points.POINT_META` rather than trusting this list.
- `topicSuggestions`: a static map from the first two letters of `hollandCode` to 3 topics each, deduplicated, max 6. R: 机械/动手制作/户外运动; I: 科学实验/编程/数学探究; A: 绘画/音乐/写作; S: 志愿服务/辩论/心理话题; E: 社团组织/商业挑战/演讲; C: 数据整理/财务规划/规划类比赛.
- Also `snapshot_summary_text(snapshot) -> dict` with three one-line Chinese sentences (`careerInterests`, `abilityTendencies`, `valuePreferences`), e.g. `职业兴趣代码 SAE：社会型、艺术型、事业型较突出。`. V3b uses these to fill the report's Y4 section without AI.

## 2. Three steps
- `growth_talk/copilot.py`: `PHASES = ["会前准备", "会谈记录", "会后整理"]`.
- Legacy rows hold 0–6. Add `normalize_phase(value)`: 0–2 → 0, 3–4 → 1, 5–6 → 2, and anything else clamps into 0..2. Apply it wherever a session is read (`_copilot_session_dict` / `_session_full`), so old sessions open on the right step without a data migration. Writes only accept 0–2.
- Remove the `entryMode` / guided-vs-direct concept: drop it from `create_session`, the phase PATCH (`_PHASE_CONTENT_KEYS`) and `_entry_mode`. Ignore an `entryMode` key if a client still sends one.
- The step PATCH stays non-bumping for navigation (from A1). Keep that behaviour and its tests.

## 3. Starting a session
- `POST /api/v2/students/<sid>/copilot/sessions`:
  - if `latest_complete_y4` is None → **409** `{"error": "该学生还没有完整的 Y4 报告，请先生成 Y4 报告", "code": "needs_y4"}`;
  - otherwise create (or return the existing) session with `y4_report_id` = that report, `meeting_at` = now (existing normalised format), and `script["y4Snapshot"] = build_snapshot(report)`.
- `GET /api/v2/copilot/sessions/<id>`: include `y4Snapshot`. If the stored one is missing, or a newer complete Y4 report exists, rebuild it, then store it with a plain field update (no revision bump: it's derived data).
- **Remove** `POST /api/first-touch/students` (manual add) and `POST /api/first-touch/import-y4`, with their idempotency cache and tests. Students come from the platform.
- **Remove** the career-calibration AI step: route `POST …/y4-calibrate` and `PATCH …/career-calibration`, plus `generate_career_calibration`. The snapshot replaces them. Keep the `copilot_career_calibration` table and data.

## 4. Talking points (optional AI, step ①)
- New job kind `talking_points` via `_dispatch`. Prompt input: the snapshot plus the student's name and grade. Output: JSON `{"points": ["…", "…", "…"]}`, 3–5 items, each ≤ 80 characters, phrased as open questions a counsellor can ask. Validate and clamp.
- Persist to `script["talkingPoints"]` (list) using the A1 pattern: compute → claim revision → write.
- Route: `POST /api/v2/copilot/sessions/<id>/talking-points` → `{jobId}`. Editable later through the existing script PATCH (allow the `talkingPoints` key in `validate_script_fields`: list of ≤ 5 strings ≤ 120 characters).
- Drop the old script text fields (`goal`, `opening`, `interpretation`, `transition`, `closing`) from validation and defaults; ignore them if present. **Keep `nextSummary`** (V3b uses it).

## 5. Home list data
Rewrite `_first_touch_students()` (it feeds `/first-touch`, built by V4a) to return, per visible student:
`{id, code, name, grade, school, advisorName, y4Date, canStart, status, step, reportVersion}`
- `canStart` = has a complete Y4.
- `status` ∈ `needs_y4 | not_started | in_progress | completed`. `completed` = the session has a CONFIRMED report for its latest run (V3b sets the session `status = "COMPLETED"` on confirm; accept either signal).
- `step` = normalised phase or null. `reportVersion` = latest confirmed version or null.
- Keep it to a constant number of queries for any number of students (no per-student query loop).

## 6. Chat pages
- `/first-touch/copilot` and `/first-touch/copilot/<sid>` → 302 to `/first-touch` and `/first-touch/students/<sid>`.
- Keep every chat **API** route (`…/assistant`, chats list/get/delete). The workspace's Copilot drawer uses them.

## Contract for V4a / V4b / V5
- Workspace page ctx: `{sid, code, name, grade, school, advisorName, sessionId|null, canStart, canWrite, readOnly, role, steps: PHASES}`. No `entryScreen`.
- Session GET adds `y4Snapshot` and keeps `lastEditor`. `script.talkingPoints` is a list.
- A student without a session but with `canStart` → the UI calls the POST to create one. A viewer never creates one.

## Acceptance (`test_ft_v3_session.py`)
- The snapshot builder on a fixture `schema_124` (write one with real codes 072–124 and string values) returns the right code, order, top-3 lists and suggestions. A 3-point partial report → `latest_complete_y4` skips it.
- POST session for a student without a complete Y4 → 409 `needs_y4`. With one → 201, and the snapshot is present on GET.
- A legacy session at phase 5 reads back as step 2.
- Manual-add, import-y4, y4-calibrate and career-calibration routes → 404 or 405. The chat pages → 302.
- Talking-points job with a mocked `call_model` stores 3–5 points and bumps the revision once. A stale revision writes nothing.
- The home data function issues a bounded number of queries (assert with a SQLAlchemy event counter for 1 vs 10 students).
- Full suite green.

Commit message: `feat(first-touch): three-step sessions that start from a completed Y4 with a prefilled snapshot`
