# D1 · Repo cleanup: stop tracking caches, delete unused root scratch files

Wave 4 · **Run alone, after every other task is committed.** It runs the full suite as its safety net, and other agents' in-progress edits would muddy that.

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

**Exception to the shared rules:** this task may use `git rm` on the files it's deleting, and must commit with explicit paths or `git commit` after staging only its own deletions. Save `git status --short` before you start as your baseline. Files that were already modified or untracked then (for example the owner's `docs/6AM_*` edits) are the owner's work: never stage, commit, revert or delete them. If anything is **staged** when you start, stop and report.

## Owner decision
"If deleting these does not impact the function of the web app, delete them, with caution."

## Scope
Repo root of `PDF_converter/` only (no subdirectories, except the cache directories in step 1):
- ~865 tracked files starting with `_` (`_cell_*.png`, `_label_col_*.png`, `_debug_*.py`, `_analyze_*.py`, `_img_*`, `_ranking_*`, `_vision_*`, …)
- tracked `*.bak` files: `_find_labels.py.bak`, `_ocr_labels.py.bak`, `_vision_values_bar.py.bak`, `extract.py.bak`, `extract_with_api.py.bak`, `probe.py.bak`, `run_siliconflow.py.bak`
- `default.profraw`

Out of scope (list them in your report, don't touch): everything else at the root (other `.py` scripts, `.docx`, `.xlsx`, `HANDOFF_*.md`, deploy scripts), all subdirectories, and anything red-line.

## KEEP — never delete
- `_vision_values_bar.py`: imported by `extract.py` (lines 53, 1744, 1928), a red-line file on the core OCR pipeline.
- `_convert_images.py`: imported by `vision_extract.py`.
- Any `_`-file that a kept file imports, directly or transitively (check the imports inside the two files above).
- Any `_`-file that any non-`_` file references in any way (see step 2).

## Do
1. **Caches.** Add `__pycache__/`, `*.pyc`, `.DS_Store`, `.pytest_cache/`, `*.profraw` to `.gitignore` (append; keep existing lines). Untrack with `git rm -r --cached` for `__pycache__` dirs, `*.pyc`, `.DS_Store` files (any depth), `.pytest_cache`. These stay on disk. Commit: `chore: stop tracking caches and OS files`.
2. **Build the deletion list** with a script you keep in your scratch area (not in the repo). For every candidate file in scope, search the **whole repo** (all file types, all subdirectories except `.git`, and excluding the candidate files themselves) for:
   - the module name (`_foo`) as `import _foo`, `from _foo`, `importlib`/`__import__` strings, `subprocess`/`python _foo.py` invocations;
   - the filename (`_foo.py`, `_cell_12.png`) as a string anywhere, including templates, `static/`, `.sh`, `.service`, `.conf`, `.yaml`, `.md`, `.json`;
   - glob or f-string patterns that could produce the name (e.g. `f'_cell_{i}.png'`, `"_label_col_"`): treat a file matching such a pattern as referenced **only if** the pattern sits in a non-candidate file.

   Anything referenced goes on KEEP. Write the result as two lists (DELETE, KEEP with the reason) in your report.
3. **Delete in two commits**, so either can be reverted alone:
   - Commit A, images and binaries (`*.png`, `*.jpg`, `default.profraw`, `*.bak`): `git rm` them. Message: `chore: remove unused debug images and backup files`.
   - Commit B, scratch scripts (`_*.py` on the DELETE list): `git rm` them. Message: `chore: remove unused root debug scripts`.
4. **Verify after each commit:**
   - `python -m pytest -q --ignore=new_iteration`: same pass count as before you started (record the baseline first).
   - `python -c "import app, extract, generate, vision_extract"` succeeds.
   - Start the app on a DB **copy** (see rules) and request `/login`, `/`, `/first-touch` (after logging in on the copy), and `/students`: no 500s and no `ModuleNotFoundError` in the log.
   - `python -c "import extract; print(extract.__file__)"`, then `grep -n "^from _\|^import _\|from _\| import _" extract.py generate.py app.py blueprints/*.py growth_talk/*.py`: every module named there still exists on disk.
   - If any check fails: `git revert` your last commit, move the culprit to KEEP, and redo.
5. **Don't** run `git clean`, don't delete untracked files, and don't touch `data/`, `output/`, `uploads/` or `pages/`.

## Report
Baseline vs final test counts, the three commit hashes, the KEEP list with reasons, how many files were deleted per commit, and the out-of-scope root files you noticed that might also be dead (for the owner to decide).
