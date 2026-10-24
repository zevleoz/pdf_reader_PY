# V2 · Remove Yuguo/CRM delegation and the Growth Talk 1.0 workspace

Wave 1 · Independent of V1/V3a (disjoint files).

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

## Owner decision
First Touch now starts and ends on this platform. The external system (Yuguo, plus the CRM "junction" delivery) used to assign students and authorise the process. That delegation is legacy and must be removed. None of it has reached production yet (it arrived with the unreleased `first-touch-merge` branch), so no external caller depends on it.

## Files you own
- Delete: `blueprints/integrations.py`, `growth_talk/yuguo_client.py`, `test_integrations.py`, `templates/growth_talk/workspace.html`
- `app.py`: **only** the integrations blueprint import/registration (≈ line 237–246) and the `"/api/integrations/"` CSRF-exemption entry (≈ line 206). Nothing else in `app.py`.
- `templates/students.html`: remove the "从 Yuguo 导入" button, dialog, CSS and JS.
- `blueprints/growth_talk.py`: page route and the API routes listed below
- `docs/integrations/junction-2026/` (delete), plus a short note in `docs/deployment_env.md` that `FIRST_TOUCH_DIRECTORY_TOKEN`, `CRM_INTEGRATION_TOKEN` and the `YUGUO_*` vars are no longer used. If C2's lines are there, edit only the integration lines.
- Tests that only cover removed code (list them).

**Not yours:** `templates/first_touch/home.html` (V4a rewrites it, including dropping its Yuguo button), `blueprints/copilot.py`, `growth_talk_store.py`, `student_360.html` (V5).

## Do
1. **Integrations blueprint.** Before deleting, `grep -rn "integrations\|yuguo\|Yuguo\|crm_\|junction" --include='*.py' --include='*.html' --include='*.js' .` and list every hit outside the files you're deleting.
   - Hits in files you own: remove them.
   - Hits in files you don't own: list them in your report. Expected: `home.html` (V4a), and `growth_talk_store.py` models such as `ExternalIdentity`, `CrmAppointment`, and the import `reconcile_yuguo_assignments` if any. **Keep the models and tables.** Data stays.
   - `growth_talk/prompts.py` version tags like `"yuguo-career-20260916"` are just labels: leave them.
   - Keep `docs/integrations/first-touch-activity-hub/` (the Activity Hub export still uses it).
   - If anything still imports `reconcile_yuguo_assignments` or `assignment_notices_for` (for example a before-request hook or the shell layout), remove that call site only if it's in a file you own; otherwise report it.
2. **Growth Talk 1.0 workspace.** First Touch replaces it.
   - Make `GET /students/<int:sid>/growth-talk` return a 302 to `/first-touch/students/<sid>`.
   - Delete `templates/growth_talk/workspace.html`.
   - In `blueprints/growth_talk.py`, **keep** `GET /api/growth-talk/reports/<id>/download.json` and `…/download.pdf` (used by First Touch and the 360 page).
   - Remove every other route in that file **only if** nothing outside `templates/growth_talk/` references it. Grep `templates/`, `static/`, `blueprints/`, `growth_talk/` for each path first. Expected removable: upload/chunk, sources, career-analysis, runs, jobs, preview-report, report, copilot. Keep any route that's still referenced, and say why.
   - Keep the store functions those routes used (other code may share them).
3. Leave `scripts/migrate_first_touch.py` (historical import tool) untouched.

## Acceptance
- `python -c "import app"` works. `GET /students/<id>/growth-talk` → 302 to First Touch. `/students` page has no Yuguo button. `POST /api/integrations/crm/deliveries` → 404.
- Downloads of a confirmed report (`/api/growth-talk/reports/<id>/download.pdf|json`) still work. Keep or adapt the existing tests that cover them.
- Full suite green after deleting the integration tests.

Commit message: `refactor: remove Yuguo/CRM delegation and retire the Growth Talk 1.0 workspace`
