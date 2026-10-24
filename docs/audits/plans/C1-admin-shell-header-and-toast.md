# C1 · Admin shell: responsive header, toast placement, First Touch nav for Viewers

Wave 1 · Independent.

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

## Files you own
- `templates/layouts/admin_v2.html` (and `templates/layouts/_command_palette.html` only if the search box lives there)
- Any stylesheet that only this layout includes (check first; if it's shared with student-facing pages, don't touch it, and report back)
- New (optional): `test_audit_shell.py`

## Do
1. **Header wraps character by character (F7).** At viewport widths ≈ 768–1100px, the top bar's breadcrumb "凭远 Y4 / …" (`.crumb`, ≈ line 113) and the role badge "管理员" wrap one character per line.
   - Breadcrumb: single line, `min-width: 0`, `overflow: hidden`, `text-overflow: ellipsis`, `white-space: nowrap`.
   - Role badge and user name: `white-space: nowrap`.
   - Below ≈ 1000px, collapse the search box (the "搜索或跳转… ⌘K" field) to an icon button that opens the existing command palette.
   - Page action buttons in the top bar (e.g. "从 Y4 导入", "手动添加学生" on `/first-touch`) must not overflow: let them wrap as whole buttons, or collapse into a "更多" menu below ≈ 1100px. Pick the simpler one that looks clean.
2. **Toast placement (F8).** `v2Toast` toasts appear bottom-right and cover the First Touch floating chat button.
   - While any toast is visible, add `has-toast` to `<body>`, and remove it when the last toast closes. Task B1 uses this class to lift the button.
   - Also give the toast container `bottom: 88px` on pages that have a FAB, or always. Whichever you choose, keep it consistent.
3. **Viewer nav.** The owner decided Viewers can see First Touch. Make the sidebar "First Touch" group (工作台 / 聊天中心 / 使用指南) visible for role `viewer` as well as admin/advisor. Find how the layout decides nav visibility by role; don't change any other group's rules.

## Acceptance
- On a DB copy, screenshots at 800, 1024 and 1440px wide of `/first-touch`, `/first-touch/students/<id>` and `/students` show a single-line header with no per-character wrapping and no horizontal page scroll.
- Trigger a toast (save something on the First Touch workspace): `document.body.classList.contains('has-toast')` is true while it's visible and false after it closes.
- Logged in as a viewer, the First Touch nav group is visible. Its pages return 403 until backend task A2 lands; that's expected.
- Full suite green.

Commit message: `fix(shell): responsive top bar, toast offset, first-touch nav for viewers`
