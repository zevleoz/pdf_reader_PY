# V4a · First Touch student list, navigation and guide

Wave 2 · **Start after V3a is committed** (uses its home-list contract). Runs alongside V3b and V5.

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
- `templates/first_touch/home.html` (rewrite)
- `templates/first_touch/guide.html`
- Delete: `templates/first_touch/chat.html`, `templates/first_touch/chat_picker.html` (V3a turned their routes into redirects; grep first that nothing renders them)
- `app_utils.py`: only the First Touch nav entries (≈ line 335–345)
- New: `test_ft_v3_home.py`

## Do
1. **Student list** (prototype screen "学生列表"). `ctx.students` items come from V3a: `{id, code, name, grade, school, advisorName, y4Date, canStart, status, step, reportVersion}`.
   - A plain table, not cards: 学生 · 编号 · 年级 · 顾问 · 最新 Y4 · First Touch status · action. It must stay readable with 200+ rows: sticky header, no per-row buttons beyond one.
   - Search box (name / code / school, client-side, instant) and filter chips with counts: 全部 / 可开始 / 进行中 / 已完成 / 缺少 Y4.
   - Status pill: `not_started` → 未开始; `in_progress` → `进行中 · ①/②/③` by step; `completed` → `已完成 · v{reportVersion}`; `needs_y4` → 需先完成 Y4 (row dimmed).
   - Action (one per row):
     - `not_started` + canWrite → **开始**: POST create session, then go to the workspace. On 409 `needs_y4`, show the message inline.
     - `in_progress` → **继续**.
     - `completed` → **查看**.
     - `needs_y4` → **去生成 Y4**, linking to the report-generation page for that student (find the existing route; if there isn't a per-student one, link to `/`).
     - Viewer: always **查看**, and only when a session exists.
   - Remove: 从 Y4 导入, 从 Yuguo 导入, 手动添加学生 and their dialogs and JS, the per-card 直接上传会后资料 button, and the 聊天中心 link.
   - Header: title "First Touch", subtitle "已完成 Y4 的学生可以直接开始会谈", link to 使用指南.
2. **Navigation** (`app_utils.py`): the First Touch group keeps 学生列表 (`/first-touch`) and 使用指南, and drops 聊天中心. Keep the existing role visibility (admin, advisor, viewer).
3. **Guide** (`guide.html`): rewrite it for the three-step flow. Keep it short, one section per step, matching the prototype notes in plain advisor-facing Chinese:
   - ① 会前: 看 Y4 速览，可选生成会谈提示;
   - ② 会谈中: 回车添加兴趣，点 0–3 打分或点象限格，★ 特别关注，自动保存;
   - ③ 会后: 可选上传转写处理建议，起草总结，选项目，确认生成报告.
   - Remove references to seven phases, Yuguo, manual add and the chat center.

## Acceptance (`test_ft_v3_home.py`)
- As an advisor: rows render with the right pill and action for each of the four statuses (build fixtures through the store / V3a functions).
- No "Yuguo", "手动添加学生", "从 Y4 导入" or "聊天中心" text on the page or in the nav.
- As a viewer: no 开始 buttons.
- Manual check on a DB copy at 1440px and 800px: search and filters work, and 开始 creates a session and opens the workspace.
- Full suite green.

Commit message: `feat(first-touch): Y4-driven student list, trimmed navigation, three-step guide`
