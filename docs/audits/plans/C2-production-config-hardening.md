# C2 · Production config hardening

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
- `app.py`: **only** the config block near the top (≈ lines 30–60: constants, `app.secret_key`, `app.config[...]`). Don't touch `_run_pipeline_job` or any route (red-line).
- `docs/deployment_env.md`
- New: `test_audit_config.py`

## Problem (F10)
- `app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')`. If production ever starts without `SECRET_KEY`, sessions and CSRF tokens are signed with a public value, and nothing warns about it.
- Session cookies set no `Secure` / `SameSite` flags. (Production sits behind Cloudflare Tunnel over HTTPS, per `PRODUCT.md`.)
- `ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'y4admin2026')` (`app.py:36`) looks unused; login now uses the users table.

## Do
1. Define "production" as `Y4_ENV == "production"` (also accept `FLASK_ENV == "production"`). Check `docs/deployment_env.md`, `deploy/`, `y4_report.service` and `gunicorn_config.py` **read-only** to see what production actually sets. If neither variable is set there, document that `Y4_ENV=production` must be added to the service environment. **Don't edit the deploy files** (red-line); just say so in the doc and in your report.
2. In production, if `SECRET_KEY` is missing or equals the dev default: raise `RuntimeError` at app creation with a clear Chinese + English message. Outside production, keep the dev fallback and log a warning once.
3. Set `SESSION_COOKIE_HTTPONLY=True` and `SESSION_COOKIE_SAMESITE='Lax'`. Set `SESSION_COOKIE_SECURE` from env `Y4_COOKIE_SECURE`, defaulting to True in production and False otherwise (so local http://localhost login keeps working).
4. `grep -rn "ADMIN_PASSWORD" --include='*.py' .`: if nothing outside its own definition reads it, delete the constant. If something reads it, leave it and report where.
5. Add every variable you touched to `docs/deployment_env.md` (name, required/optional, default, effect).

## Acceptance (`test_audit_config.py`)
Use `monkeypatch` to set env vars, then import or reload `app` in a subprocess (`subprocess.run([sys.executable, "-c", "import app"])`) to avoid polluting the test session:
- production + no `SECRET_KEY` → non-zero exit containing your message;
- production + strong `SECRET_KEY` → starts, `SESSION_COOKIE_SECURE` is True;
- no production env → starts, cookie not Secure;
- `SESSION_COOKIE_SAMESITE == 'Lax'` in both cases.

Also log in locally on http://localhost to confirm dev login still works. Full suite green.

Commit message: `chore(config): fail fast without SECRET_KEY in production; harden session cookies`
