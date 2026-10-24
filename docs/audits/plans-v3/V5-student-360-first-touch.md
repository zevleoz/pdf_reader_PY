# V5 · Student 360: replace "Growth Talk" with "First Touch"

Wave 2 · **Start after V3a is committed.** Runs alongside V3b and V4a.

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
- `templates/student_360.html`: only the Growth Talk tab/section (≈ lines 536–575), its tab entry (≈ line 638, `{ key: 'growth', label: 'Growth Talk' }`), the First Touch archive link (≈ line 191), and the Alpine data it uses
- `blueprints/students.py`: only the `student_360` view's First Touch context (≈ lines 275–300)
- New: `test_ft_v3_student360.py`

## Do
1. Rename the tab to **First Touch** (key `first_touch`; if anything deep-links to `#growth`, map it to the new key). Remove every "Growth Talk" wording and the `进入 Growth Talk` button.
2. View context (`students.py`): replace `gt_reports` with `first_touch`:
   ```
   {"status": needs_y4|not_started|in_progress|completed, "step": 0-2|null,
    "canStart": bool, "sessionId": int|null,
    "interests": [top 6 scored interests by preference+competence, then specialFocus first: {label, preferenceScore, competenceScore, specialFocus}],
    "scoredCount": int, "pendingCount": int,
    "reports": [confirmed versions, newest first: {id, version, confirmedAt, confirmedBy}]}
   ```
   Reuse V3a's helpers (`latest_complete_y4`, the single-session lookup, normalised step) instead of re-implementing them. Keep `growth_talk_store.list_reports` for confirmed reports.
3. Section layout (prototype screen "学生 360 卡片"):
   - header: status pill (same wording as the First Touch list) and one action button:
     - `开始 First Touch` (canStart, no session, can_write);
     - `继续会谈` (in progress);
     - `查看 First Touch` (completed or viewer);
     - `需先完成 Y4` (disabled, with a link to report generation);
   - interest chips `★ 名称 · 喜欢/擅长` and `N 项已评分 · M 项待评`;
   - confirmed report table: 版本 · 确认时间 · 确认人 · PDF / JSON (`/api/growth-talk/reports/<id>/download.pdf|json`);
   - empty state: `还没有已确认的 First Touch 报告。在会谈第 ③ 步确认后出现在这里。`
4. The header link `First Touch 归档` stays admin-only (unchanged route).
5. Viewer: the section is visible, downloads work, and no start button is shown.

## Acceptance (`test_ft_v3_student360.py`)
- For each status the section renders the right pill and button. A student with confirmed v1 and v2 lists both, newest first.
- The page HTML contains no "Growth Talk".
- Viewer → no 开始 button, downloads present.
- Full suite green.

Commit message: `feat(student-360): First Touch section replaces Growth Talk`
