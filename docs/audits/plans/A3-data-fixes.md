# A3 · Manual add, meeting time and Activity Hub data fixes

Wave 3 · Backend track, step 3 of 3. **Start only after A2 is committed** (same file).

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
- `blueprints/copilot.py`: `api_create_student`, `api_create_session` (the default meeting time only), `_parse_meeting_at`, `_activity_hub_profile` / `api_report_activity_hub`
- `db.py`: **add** a new function only. Don't change `find_or_create_student`, which OCR and booking depend on.
- New: `scripts/normalize_meeting_at.py`, `test_audit_data_fixes.py`

## 1. Manual add merges across advisors (F4)
`api_create_student` (`blueprints/copilot.py:923-970`) calls `db.find_or_create_student`, which matches by **name only** (`db.py:447-490`). Advisor B adding "Eric" therefore attaches to advisor A's Eric, overwrites its `school`, and gets A's student profile in the response.

Do:
- Stop calling `find_or_create_student` here.
- Dedupe only against students **visible to the caller**: for an advisor, same `advisor_name`; for an admin, all students. Match on exact name, and also on school when the request gives one.
- On a hit, return `{"ok": true, "existing": true, "student": …}` and **modify nothing**.
- Otherwise create a new student via a new `db.create_student(name, grade, school, phone, advisor_name) -> int`, assigning `student_code` exactly the way existing creation does (find where `Y4-XXXX` codes are generated and reuse it).
- Keep the `requestId` idempotency cache as is.

## 2. Meeting time stored inconsistently (F5, server side)
`api_create_session` defaults to `datetime.utcnow().isoformat()` (no timezone suffix; browsers parse that as local time). `_parse_meeting_at` stores whatever string the client sent, so the DB now holds mixed formats (`2026-10-23T15:23:33` and `2026-10-24T03:00:00.000Z`).

Do:
- `_parse_meeting_at` returns a normalized UTC string `YYYY-MM-DDTHH:MM:SSZ`. Input with an offset or `Z` → convert to UTC. Naive input → treat it as **Asia/Shanghai** local time (that's what an advisor types).
- The `api_create_session` default uses the same format: current UTC time, rounded down to the nearest 15 minutes.
- `scripts/normalize_meeting_at.py --db <path> [--apply]`: rewrites `copilot_sessions.meeting_at` to that format. Existing naive values were written by `utcnow()`, so treat **stored** naive values as UTC (unlike API input). Dry run by default; idempotent. Instructions go at the top of the script (back up first). **Don't run it on `data/y4_students.db`.**
- Check the report/PDF code that formats `meetingAt` (`report_contract.build_report_preview`, `api_report_pdf`) still shows Shanghai local time correctly with the `Z` format.

## 3. Activity Hub export loses interest category (F6)
`_activity_hub_profile` hard-codes `"sourceType": "interest", "topicType": "hobby"` for every interest. Do:
- Read `docs/integrations/first-touch-activity-hub/api-profile.schema.json` and map our `topicType` values (`subject`, `interest`, `social`) to the schema's allowed `topicType` / `sourceType` values. Don't guess: if the schema has no clean match for one of ours, pick the closest allowed value and explain it in a code comment and in your report.
- Validate a generated export against the schema in a test. Use `jsonschema` if it's importable; otherwise assert the enum values by hand.

## Acceptance (`test_audit_data_fixes.py`)
- Advisor B adds a name that already exists under advisor A → a new student (201) is created; A's row is unchanged (school, advisor_name); the response never contains A's student id.
- Advisor A adds the same name again → `existing: true`, 200, nothing modified.
- `meetingAt: "2026-01-01T12:00"` (naive, Shanghai) is stored as `2026-01-01T04:00:00Z`; the report payload shows 12:00. `…T04:00:00.000Z` input is stored as `…T04:00:00Z`.
- The normalize script on a temp DB converts both legacy formats and is a no-op on a second run.
- Activity Hub export of a confirmed report with one interest of each type has three different, schema-valid topic types.
- Full suite green.

Commit message: `fix(first-touch): scoped manual add, normalized meeting time, activity hub topic mapping`
