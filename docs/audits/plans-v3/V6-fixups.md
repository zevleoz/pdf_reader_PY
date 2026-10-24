# V6 · Fix-ups from the end-to-end review

Single agent, run alone after V1–V5. Small, targeted fixes; don't refactor beyond them.

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
- `growth_talk/copilot.py` (item 1 only)
- `templates/first_touch/workspace.html` (items 2–6)
- `growth_talk/copilot_report.py` (item 7, the `missing_report_fields` labels only)
- `templates/student_360.html` (item 8, the First Touch section only)
- New: `test_ft_v6_fixups.py`

## Found on 2026-10-24 (live run on a DB copy, real DashScope calls)

1. **P1: transcript analysis always fails.** Uploading a meeting transcript and running the supplement job ends in error `Y4 验证最多 3 条，每条不超过 100 字，请重试生成` (reproduced twice with qwen-plus). `compute_supplement_analysis` (`growth_talk/copilot.py` ≈ line 437) runs the AI's `y4Validation` through the **strict** `validate_report_y4_validation`, which raises when the model returns more than 3 items or one over 100 characters.
   - Use `clamp_y4_validation` for AI output there.
   - Keep the strict check only where a report is confirmed.
   - Check the other AI result paths (next steps, projects, talking points, supplement `newInterests` / `scoreConflicts`) for the same raise-instead-of-clamp pattern, and clamp any you find.
   - Test: mock `call_model` returning 5 items of 150 characters → the job succeeds with 3 items of ≤ 100.
2. **Step ② doesn't focus the add box.** Entering step ② (by the stepper or by `开始会谈 →`) must focus the "输入兴趣，回车添加" input, so the advisor can type straight away. Today keystrokes go nowhere until they click it.
3. **Selecting an interest for the board is hidden.** Clicking the interest name opens rename; selecting only works by clicking blank space in the row, so "点左侧一项选中" fails for most people.
   - A **single click anywhere on the row**, including the name, selects it (visible highlight).
   - **Double-click the name** (or a small pencil icon with `aria-label="重命名"`) to rename.
   - Clicking a score button or a text input must not toggle the selection.
4. **The save indicator lies after a conflict.** After a 409 the header still says `已自动保存 HH:MM`. While the conflict banner is showing, the indicator must read `未保存 · 有冲突` (warning colour), and return to normal after `载入最新` succeeds.
5. **The floating `问 Copilot` button covers the bottom-right step buttons** (`开始会谈 →`, `结束会谈，去整理 →`), and toasts stack on top of both. Give the step footer enough right padding to clear the button (≥ 72px at all widths), and lift the toast above the button (C1 already adds `body.has-toast`; reuse it).
6. **Session loads twice.** On page load `loadSession()` fires twice (two identical `GET /api/v2/copilot/sessions/<id>`; see ≈ lines 841 and 948). Load once.
7. **Old wording in the step-③ checklist** (`missing_report_fields`). Rewrite the optional items in plain words without jargon:
   - `项目推荐：尚未选择并保存"推荐给学生"的方案…` → `项目建议：未选择（可选，报告中不显示项目）`;
   - `会议对 Y4 的验证：未填写` → `会议与 Y4 的对照：未填写（可选）`;
   - `会议文字稿：未上传（可选）` stays.
   Update any test asserting the old strings.
8. **Student 360 shows UTC times.** The First Touch report table shows the confirmation time in UTC (e.g. 14:50 for a 22:50 confirmation). Format `confirmedAt` in `Asia/Shanghai` (`YYYY-MM-DD HH:mm`). Check whether the shared `fmtDate` helper on that page has the same problem for other naive-UTC timestamps; if it does, fix it there and say which tabs are affected.

## Acceptance
- `test_ft_v6_fixups.py` covers item 1 (mocked AI) and items 6–7 (markup / label assertions).
- Manual on a DB copy: upload a short `.txt` transcript on step ③ → suggestions appear; items 2–5 behave as described at 1440×900 and 1024×768; the 360 time matches local time.
- Full suite green.

Commit message: `fix(first-touch): clamp AI transcript output, step-2 focus and selection, honest save state, 360 local times`
