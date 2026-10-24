# V4b · Rewrite the First Touch workspace as a three-step, in-meeting tool

Wave 3 · **Start after V1, V3a and V3b are committed.** This is the largest task. Build exactly what the prototype shows; when in doubt, choose fewer clicks.

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

## Files you own
- `templates/first_touch/workspace.html`: **rewrite from scratch.** The current file is ≈ 2,500 lines for 7 phases. Target well under half that. Don't keep dead code from the old version.
- `templates/first_touch/_styles.html`, if shared First Touch styles belong there
- New: `test_ft_v3_workspace.py`

## Backend contract (from V3a / V3b; read the code to confirm)
- Page ctx: `{sid, code, name, grade, school, advisorName, sessionId|null, canStart, canWrite, readOnly, role, steps}`. If `sessionId` is null and `canWrite && canStart`, POST `/api/v2/students/<sid>/copilot/sessions` on load, then continue. If it's null and the user can't write (or can't start), show an empty state.
- `GET /api/v2/copilot/sessions/<id>` → `session` (with `phase` 0–2, `revision`, `interests`, `script.talkingPoints`, `script.nextSummary`, `meeting_at`), `y4Snapshot`, `lastEditor`, `report`, `projectsCurrent`, supplement data.
- Writes (all need `revision`; each returns the new one):
  - `PATCH …/phase` `{phase, revision}` (navigation, no bump), or with `interests` / `script` / `meetingAt` (content, bumps);
  - `PATCH …/interest-draft` `{interests, revision}`;
  - `POST …/talking-points`, `POST …/next-steps`, `POST …/projects` → `{jobId}`; poll `GET /api/v2/copilot/jobs/<jobId>`;
  - `PATCH …/projects` (review edits), `POST …/sources` (transcript upload, multipart), `POST …/supplement` (analyse transcript);
  - `POST …/report-preview` (draft + `missing`), `POST …/report-confirm` `{revision}`;
  - chat: `POST /api/v2/copilot/sessions/<id>/assistant`, `GET /api/students/<sid>/copilot/chats`.
- Interest object: `{id, label, topicType: subject|interest|social, preferenceScore: 0-3|null, competenceScore: 0-3|null, specialFocus: bool, note}`. Keep whatever extra fields the API returns when you save (spread the original object).

## Screens (prototype screens ①②③)
**Shared header:** student name + code/grade/school/advisor; a three-step stepper (done steps show ✓, free navigation); an autosave indicator `已自动保存 HH:MM` / `正在保存…` / `保存失败，点此重试`; and a meeting date-time input (Shanghai time, 15-min steps, saved with the next content write). Viewer: an `只读查看` badge and every control disabled. Show `最近编辑：name · time` from `lastEditor`.

**① 会前 · Y4 速览**
- Three blocks from `y4Snapshot`:
  - 职业兴趣代码 (big letters) + six RIASEC bars, scaled to the student's own max score, top 3 highlighted;
  - 能力优势前三 + 相对较弱;
  - 职业价值观前三.
  Show the report date. Label raw scores as 得分, not 百分位.
- 会谈提示: button `AI 生成提示` → job → editable list (add / remove / edit lines, autosave into `script.talkingPoints`). Failure shows an inline error with 重试.
- Primary button `开始会谈 →` (goes to ②).

**② 会谈中 · 兴趣记录** (the core screen; optimise for speed during a live meeting)
- Left column:
  - an add box: type a name, press **Enter** to add with `preferenceScore`/`competenceScore` null. Category guessed by keyword (subject list: 数学 物理 化学 生物 语文 英语 历史 地理 政治 编程 计算机 经济; social list: 环保 气候 公益 社会 新闻 政策 心理 AI 人工智能; else interest). Focus stays in the box after adding;
  - Y4 topic chips from `y4Snapshot.topicSuggestions` (one click adds; hidden once added);
  - the interest rows. Each row has:
    - name (click to rename inline);
    - category tag (click cycles 学科 → 课外兴趣 → 社会话题);
    - ★ special focus (at most one; setting one clears the others);
    - 删除, with a 5-second "撤销" toast instead of a confirm dialog;
    - two segmented controls `– 0 1 2 3` for 喜欢 and 擅长 (`–` = 待评), with `title` tooltips 不喜欢/一般/喜欢/非常喜欢 and 不擅长/一般/擅长/非常擅长;
    - a one-line 备注 input.
- Right column: a 4×4 board (rows 擅长 3→0, columns 喜欢 0→3), coloured zones (喜欢且擅长 / 喜欢 / 擅长 / 其他), item names in cells, and the count `N 项已评分`.
  - Click a row to select it, then click a cell to set both scores at once; this clears the selection and shows a toast.
  - Unscored items stay off the board, with the hint `待评事项不进图`.
- **Autosave:** debounce 800 ms after the last change, then `PATCH …/interest-draft`. Serialise saves (never two in flight); if a change happens during a save, save again after it.
  - On **409**, show a banner `其他人刚更新了这次会谈` with `载入最新`. That button reloads the session and re-applies local unsaved edits **only** for interests the server copy doesn't have; otherwise the server copy wins, and the banner says so.
  - Add a `beforeunload` guard only while a save is pending.
- A local meeting timer (`会谈 mm:ss`), started when ② is first opened in this page load. Not saved.
- Keyboard: Enter adds; Esc clears the selection.

**③ 会后 · 整理与报告**
- **会议转写 (optional):** upload (PDF/DOCX/TXT/MD) → `POST …/sources`, then `POST …/supplement` job. Show the AI's suggestions as rows: new interest (`采纳` / `忽略`) or score conflict (`改为 X` / `保留 Y`), with the evidence quote. Decisions save immediately (through the existing interest review payload on `PATCH …/phase` with `interestReview`; read `growth_talk/copilot.py: validate_interest_review_save` for the exact shape).
- **会谈总结:** textarea (≤ 1400 chars with a counter) + `AI 起草` (next-steps job). Autosaves into `script.nextSummary`.
- **项目建议 (optional):** `生成建议` (projects job), then cards; clicking a card toggles whether it goes into the report (maps to the existing status `student_review` vs `advisor_excluded`); saves with `PATCH …/projects`. Show `已过期，需重新生成` when `projectsCurrent` is false.
- **确认报告:** a live checklist from `report-preview`'s `missing` (✓ / !). The `确认并生成报告` button is enabled only when nothing required is missing, and calls `report-confirm {revision}`.
  - After success: `已确认 · v{n}`, buttons 下载 PDF / 下载 JSON (`/api/growth-talk/reports/<id>/download.pdf|json`) and `在学生 360 查看`.
  - If the user edits after confirming, show `已确认 v{n}；有新修改，确认后生成 v{n+1}`.

**Copilot drawer:** a floating `问 Copilot` button on all three steps opens a right-side drawer: two suggested questions, a free-text box (≤ 1000 chars, Enter sends, Shift+Enter newline), answers via the assistant job, a stop button (abort polling), and the last chat's history (`GET …/chats`). Viewer: history only. Escape the answer text (no `x-html` with model output); render line breaks and simple `- ` lists only.

## Not in the new UI (delete)
The entry-choice screen, phases 1–7 and their script boxes (goal/opening/interpretation/transition/closing), the career-calibration editor, the 3×3 board, the fingerprint and double checkbox, the 4-step prepare indicator, the floating chat's separate history page, every explicit 保存 button for interests/scores/summary, and user-visible revision numbers.

## Quality bar
- Usable at 1280×800 without page scroll on step ② for up to ~12 interests (the list scrolls inside its column); stacks to one column below 960px.
- Font sizes ≥ 12px for text and ≥ 11px for axis/meta labels. Focus states are visible. Every icon-only button has an `aria-label`.
- No console errors. No request to a removed endpoint.

## Acceptance
- `test_ft_v3_workspace.py` (render + markup assertions): the page has the three step labels, the `– 0 1 2 3` score controls for both dimensions, no `entryScreen`, no "修订", and no old phase names (目标说明, Y4 结果解读, 总结与下一步).
- Manual run on a DB copy as an advisor; record what you did in your report:
  1. open a student with a Y4 → the session is created and ① shows the snapshot;
  2. go to ② and add 5 interests by keyboard, score them with buttons and via the board, star one, delete and undo one, reload → everything persisted;
  3. open the same session in two tabs, edit both → the 409 banner works;
  4. on ③, without uploading a transcript, write a summary and confirm → v1 downloads;
  5. as a viewer → read-only, and zero non-GET requests in the network panel.
- Full suite green.

Commit message: `feat(first-touch): three-step in-meeting workspace with autosave and live interest board`
