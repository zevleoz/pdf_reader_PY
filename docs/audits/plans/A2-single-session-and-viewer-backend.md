# A2 · One First Touch session per student + Viewer read access (backend)

Wave 2 · Backend track, step 2 of 3. **Start only after A1 is committed** (same files). B2 builds the matching UI in parallel against the contract in the "Contract for B2" section below.

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
1. **Each student has exactly one First Touch session**, shared by whoever works on the student (admin or the student's advisor).
2. **The Viewer role can see First Touch** (read-only: no writes, no LLM calls).

## Files you own
- `blueprints/copilot.py` (decorators, `_student_or_404`, `_session_or_404`, `_visible_students`, `_first_touch_students`, `api_list_sessions`, `api_create_session`, `page_*` routes, chat routes' role decorators)
- `growth_talk_store.py` (`create_session`, `list_sessions`, related helpers)
- `blueprints/growth_talk.py`: role decorators on GET download routes only
- New: `scripts/merge_duplicate_copilot_sessions.py`, `test_audit_single_session.py`, `test_audit_viewer_access.py`
- Existing tests that assert the *old* per-advisor session isolation (update them to the new rule, and list them in your report)

## Current behaviour
- `store.create_session(student_id, advisor_id, …)` is idempotent per `(student_id, advisor_id)`, so an admin and an advisor each get their own session for the same student.
- `store.list_sessions(sid, advisor_id)` filters by advisor for advisors; `_session_or_404` rejects advisors whose `advisor_id` differs from the row's.
- Every First Touch route is `@role_required("admin", "advisor")`. `VALID_ROLES = ("admin", "advisor", "viewer")` (`db.py:2280`). `_student_or_404` / `_visible_students` only restrict advisors (by `students.advisor_name`), so admins and viewers already see every student.

## Do
### Single session
1. `create_session`: idempotent per **student** only, ignoring `ARCHIVED` rows. Keep writing `advisor_id` as "created by". Do the check-and-insert in one transaction; if you add the unique index below, catch `IntegrityError` and return the existing row.
2. `list_sessions(student_id)`: drop the advisor filter (keep the parameter optional for compatibility, but no caller should pass it) and exclude `status = 'ARCHIVED'`. Update all callers in `blueprints/copilot.py` (`api_list_sessions`, `page_workspace`, `page_chat`, `_first_touch_students` counts, the chat picker).
3. `_session_or_404`: authorisation = the caller can see the student (`_student_or_404`). Remove the `advisor_id == actor` check. Return 404 for `ARCHIVED` sessions.
4. Migration `scripts/merge_duplicate_copilot_sessions.py`:
   - default **dry run**: print, per student with more than one non-archived session, which one is kept and which are archived;
   - `--apply`: keep the session that (a) has a confirmed report via its `run_id`, else (b) has the highest `phase`, else (c) has the latest `updated_at`. Set the others to `status='ARCHIVED'` (never delete), and write an audit row via `store.write_audit` (action `copilot_session_archived_duplicate`);
   - then create `CREATE UNIQUE INDEX IF NOT EXISTS uq_copilot_session_student_active ON copilot_sessions(student_id) WHERE status != 'ARCHIVED'` (SQLite partial index). Also add it to the model's `__table_args__` / table creation path so new databases get it;
   - takes `--db <path>`. **Don't run it on `data/y4_students.db`.** Put the run instructions at the top of the script (back up first).
   - Before relying on `status`, check how `ARCHIVED` interacts with existing values (`REVIEW`, …) and any `status` checks in the code.
5. Chats stay keyed by student (no change), but make sure `page_chat` passes the single active session id.

### Viewer read access
6. Add `"viewer"` to `@role_required` on **read-only** routes only:
   - pages: `/first-touch`, `/first-touch/students/<sid>`, `/first-touch/copilot`, `/first-touch/copilot/<sid>`, `/first-touch/guide`
   - GET APIs: `GET /api/v2/students/<sid>/copilot/sessions`, `GET /api/v2/copilot/sessions/<id>`, `GET /api/v2/copilot/jobs/<job_id>`, `GET …/report-pdf`, `GET /api/students/<sid>/copilot/chats`, `GET /api/copilot/chats/<chat_id>`, `GET /api/first-touch/reports/<id>/activity-hub.json`, and the growth-talk report downloads `GET /api/growth-talk/reports/<id>/download.json|pdf`.
   - **Everything that writes or calls an LLM stays admin/advisor**: all POST/PATCH/DELETE routes (including `POST …/report-preview`; viewers see confirmed reports through the download routes, not drafts), the assistant/chat-ask routes, report-prepare, report-confirm, imports, manual add.
   - `/first-touch/archive/<sid>` stays **admin-only** (it shows raw transcripts and is audit-logged).
7. `page_workspace` when no session exists and the caller is a viewer: render with `entryScreen: false`, `sessionId: null` and a new `ctx.readOnly: true` (see contract). Never create anything on GET.
8. Add `ctx.readOnly` (True for viewer) and keep `ctx.canWrite` (False for viewer) on every First Touch page; add `ctx.role`.

## Contract for B2 (front end)
- Every First Touch page ctx has `canWrite: bool`, `readOnly: bool`, `role: "admin"|"advisor"|"viewer"`.
- Workspace ctx: `sessionId` is the single active session or `null`; `entryScreen` is true only when `sessionId` is null **and** `canWrite`.
- Session GET payload: unchanged, plus `session.advisor_id` (creator) and a new top-level `lastEditor: {name, at}` from the latest `CopilotPhaseEvent` (actor display name + timestamp).

## Acceptance
- `test_audit_single_session.py`: admin creates a session for an advisor's student → the advisor's `GET …/sessions` returns that same session; the advisor's `POST …/sessions` returns it with `existing: true` (no second row); an advisor can PATCH the admin-created session; an advisor of a different student gets 404; the migration (run against a temp DB with 3 sessions for one student) archives 2, keeps the right one, and the unique index then blocks a second active session.
- `test_audit_viewer_access.py`: viewer gets 200 on every route in step 6, 403 on every write/LLM route (loop over the blueprint's url_map: any non-GET route must reject viewer), and 403 on the archive page.
- Full suite green.

Commit message: `feat(copilot): one shared session per student; read-only viewer access to First Touch`
