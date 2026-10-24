# A1 · Atomic revision locking + navigation without revision bumps

Wave 1 · Backend track, step 1 of 3 (A2 and A3 start after this is committed).

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
- `blueprints/copilot.py`: only the session write routes (`api_save_phase`, `api_save_calibration`, `api_save_interest_draft`, `api_upload_source`, `api_y4_calibrate`, the projects PATCH/POST routes, `report-prepare`/`report-confirm` if they bump revisions) and private helpers they use
- `growth_talk_store.py`
- `growth_talk/jobs.py`
- `growth_talk/copilot.py`, `growth_talk/copilot_report.py`
- New: `test_audit_revisions.py`

## Problem (F2, F3)
Copilot sessions use optimistic locking through `copilot_sessions.revision`. Today every write route:
1. checks `body.revision == row.revision` (`_revision_error`),
2. commits data in **separate** transactions (`store.replace_session_interests`, `store.save_supplement_analysis`, `store.update_session_fields`, `store.upsert_calibration`, …),
3. **then** calls `store.bump_session_revision(session_id, expected)`, a compare-and-swap (`growth_talk_store.py:1359`).

If two requests race, the loser has already written its data before the swap fails, and the `RevisionConflict` raised in step 3 isn't caught, so the response is a 500. Background jobs (`growth_talk/jobs.py:205-240`) do the same after a 30–90 s LLM call: they write results, then fail if anything changed the revision meanwhile.

Separately, `api_save_phase` bumps the revision on every call, and the front end calls it on every phase-tab click. Browsing alone moved the revision 34→37 in testing, which makes jobs and multi-tab editing fail constantly.

## Do
1. **Claim before you write.** Add a store helper, e.g. `claim_revision(session_id, expected_revision, actor_id, action, phase=None) -> int`. It runs the CAS `UPDATE … SET revision = revision + 1 WHERE id = ? AND revision = ?`, records the `CopilotPhaseEvent`, commits, returns the new revision, and raises `RevisionConflict` on 0 rows. In every write route, call it **before** any data write and return the new revision. If you can cleanly put the claim and the writes in one SQLAlchemy transaction instead, do that; claim-first is the acceptable minimum.
2. **Map conflicts to 409.** Catch `store.RevisionConflict` in every write route (or with one small decorator) and return `_error_response(exc)`, which already maps it to 409 with the existing Chinese message.
3. **Phase-only saves don't bump.** In `api_save_phase`, when the body has `phase` + `revision` and none of `interests`, `script`, `meetingAt`, `entryMode`, `supplementAnalysis`, `interestReview`: still validate the revision, update `phase` (and `status` = `REVIEW` for the last phase, as now), **don't** bump, and return the unchanged revision in the same response shape.
4. **Jobs: compute, then claim, then write.** For `supplement`, `next_steps`, `projects_generate`, `projects_review` (and `report_prepare` if it writes), restructure so the LLM work returns its result without writing (split functions in `growth_talk/copilot.py` such as `run_supplement_analysis` → compute + persist, `generate_next_steps` currently writes at `:503`, `generate_projects` at `:824`, supplement at `:444`, `:726`). Then claim the revision, then persist. If the claim fails, persist nothing and fail the job with the message `会谈在生成期间已被修改，请刷新后重新生成。`
5. Keep every existing response shape (`{"revision": …, "result": …}`) so the templates keep working.

## Acceptance (write these in `test_audit_revisions.py`)
- For each write route: a stale `revision` returns **409**, and the DB content (interests, script, calibration, supplement analysis, sources) is byte-for-byte unchanged.
- Phase-only PATCH: 200, same revision returned, `phase` updated.
- PATCH with content: revision +1.
- A job dispatched at revision N, where the session is bumped to N+1 before the job finishes (use `_inline_jobs` and bump in between), ends in error and writes nothing.
- Full suite green; update existing tests only where they asserted the old "phase-only bumps the revision" behaviour, and say which ones in your report.

Commit message: `fix(copilot): claim revision before writes; phase navigation no longer bumps revision`
