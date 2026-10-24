# B2 · Read-only Viewer UI + shared-session UI

Wave 2 · Front-end track, step 2 of 2. **Start after B1 is committed** (same template). This can run alongside backend task A2. Build against the contract below; the end-to-end checks need A2 to be committed too.

## Rules for this task (read first)

- Repo: `/Users/jefflau/projects/pdf_report_converter/PDF_converter` (git, branch `first-touch-merge`). Python: `/Users/jefflau/anaconda3/bin/python`.
- Background: `docs/audits/2026-10-24-first-touch-production-audit.md` (finding IDs F1–F11) and `PRODUCT.md` one level up.
- **Edit only the files listed under "Files you own".** Other agents are working in this same checkout at the same time.
- Commit only your own files, by explicit path: `git add <your files> && git commit -m "<message>"`. Never `git add -A`, `git add .`, `git stash`, `git reset`, `git checkout -- .`, or anything that touches other people's changes. Don't push.
- Never edit red-line files (spec `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md` §2): `extract.py`, `generate.py`, `data_points.py`, `validate.py`, `gauge_reader.py`, `gauge_processor.py`, anything in `new_iteration/`, deploy files, `/api/v1/*` contracts.
- Flask + Jinja + Alpine.js (CDN). No Node, npm or build step. Keep Chinese UI copy in the existing tone.
- **Never read from or write to `data/y4_students.db`** (real student data). Tests use their own fixtures. For manual browser checks, use a copy: `sqlite3 data/y4_students.db ".backup '/tmp/<you>/audit.db'"`, then `DATABASE_URL=sqlite:////tmp/<you>/audit.db SECRET_KEY=dev PORT=<free port> python app.py`, and create users against the copy with `db.create_user(...)`.
- Reuse fixtures from `test_copilot_routes.py` / `test_copilot_gapfixes.py` (`client`, `login_as`, `qdb`, `_inline_jobs`). Put new tests in the new test file named below.
- Done = your new tests pass, `python -m pytest -q --ignore=new_iteration` is fully green, and you committed. If another agent's in-progress edit breaks an unrelated test, say so in your report instead of "fixing" their file.
- Final report: list the files you changed, the commit hash, test counts, and anything you couldn't do.

## Owner decisions this implements
1. Each student has **one** First Touch session shared by admin and the student's advisor.
2. The **Viewer** role can see First Touch, read-only: no writes, no AI generation, no chat questions.

## Files you own
- `templates/first_touch/workspace.html`, `home.html`, `chat.html`, `chat_picker.html`, `guide.html`
- `templates/student_360.html`: only the First Touch section/links
- New: `test_audit_viewer_ui.py`

## Contract from backend task A2
- Every First Touch page ctx has `canWrite: bool`, `readOnly: bool`, `role: "admin"|"advisor"|"viewer"`. Viewer → `canWrite=false, readOnly=true`.
- Workspace ctx: `sessionId` is the student's single active session or `null`; `entryScreen` is true only when `sessionId` is null **and** `canWrite`.
- `GET /api/v2/copilot/sessions/<id>` adds `lastEditor: {name, at}` (may be missing until A2 lands; render nothing if absent).
- Viewers get 403 on every POST/PATCH/DELETE, so the UI must **never send one** in read-only mode.

## Do
### Workspace (`workspace.html`)
1. When `readOnly`:
   - Wrap editable areas in `<fieldset :disabled="readOnly">` (or bind `:disabled`) and hide every save, generate, regenerate, upload, add, delete, confirm and "重新准备报告" control.
   - `goPhase()` only switches `phase` locally (no PATCH).
   - Don't auto-run `generateNextSteps()` (tab 5) or `prepareReport()` (tab 7).
   - Tab 7: if the session has a confirmed report (`report` in the session payload), show the confirmed-report view with PDF/JSON download links; otherwise show `报告尚未确认`.
   - Hide the floating chat composer (history may still be shown).
   - Show a small badge in the header: `只读查看`.
2. When `sessionId` is null and `readOnly`: show an empty state `该学生尚未开始 First Touch 会谈。` instead of the entry-choice cards.
3. Shared session: in the header, under the student name, show `最近编辑：{name} · {Shanghai time}` from `lastEditor` when present.

### Home (`home.html`)
4. When `readOnly`: hide `从 Y4 导入`, `从 Yuguo 导入`, `手动添加学生` and per-card `直接上传会后资料`; rename `进入工作台` to `查看`.
5. For everyone: show `直接上传会后资料` only on cards whose student has **no** session yet (with a single shared session it only makes sense before one exists). If the card data doesn't expose this, use `sessionCount == 0`.

### Chat (`chat.html`, `chat_picker.html`)
6. When `readOnly`: show the chat list and history, but hide the composer, `开始聊天`, stop and delete. Show the hint `只读账号可查看历史对话，不能发起提问。`

### Student 360 (`student_360.html`, First Touch section only)
7. Make sure the First Touch links render for viewers and point to `/first-touch/students/<id>` (read-only view). Keep the archive link admin-only.

## Acceptance (`test_audit_viewer_ui.py`)
Render each page with a ctx that sets `readOnly=True, canWrite=False` (log in as a viewer via `login_as`; if A2 isn't committed yet, render the templates directly with `app.test_request_context()` + `render_template`):
- Workspace HTML contains `只读查看` and no visible save/generate buttons for viewers.
- Home has no `手动添加学生` for viewers.
- Chat has no composer textarea for viewers.

Then, once A2 is committed, a manual check on a DB copy logged in as a viewer: open home → a student → all 7 tabs, chat, and 360. The browser network tab shows **zero** non-GET requests and no 403s.

Full suite green.

Commit message: `feat(first-touch): read-only viewer mode and shared-session UI`
