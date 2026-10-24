# V3b · Wrap-up step and a simpler report confirmation (backend)

Wave 2 · Backend track, step 2 of 2. **Start after V1 and V3a are committed.**

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
- `growth_talk/copilot_report.py`, `growth_talk/report_contract.py`, `growth_talk/report_pdf.py` (only if a field change requires it)
- `blueprints/copilot.py`: only the report routes (`report-prepare`, `report-preview`, `report-confirm`, `report-pdf`) and the next-steps / projects routes
- `growth_talk/copilot.py`: only the next-steps, supplement and projects functions
- `growth_talk_store.py`: only the model-name label line (≈ 654) and session status on confirm
- New: `test_ft_v3_report.py`

## Rules from the prototype (step ③)
- A meeting transcript is **optional**. When uploaded, the existing supplement analysis proposes missed interests and score conflicts; each must be accepted or ignored.
- The summary (`script.nextSummary`) and project ideas are generated **only on request**, never automatically. Both stay editable.
- Confirmation gate (all required):
  - ≥ 3 interests with both scores set;
  - non-empty summary;
  - no unresolved transcript suggestions;
  - student grade filled.
- Projects, transcript and Y4 validation are optional.
- Confirm creates an immutable report version and sets the session `status = "COMPLETED"`. Editing afterwards is allowed: any content save on a COMPLETED session sets it back to `REVIEW`, and the next confirm creates version +1 (the existing per-student version counter).

## Do
1. **`missing_report_fields`** (`copilot_report.py:120-192`):
   - make `meeting` (会议文字稿) **not required**;
   - add `{"key": "min-interests", "label": "已评分兴趣不足 3 项", "required": True}` when fewer than 3 interests have both scores;
   - add `{"key": "summary", "label": "会谈总结未填写", "required": True}` when `nextSummary` is empty;
   - add `{"key": "pending-suggestions", "label": "还有 N 条会议转写建议未处理", "required": True}` when supplement candidates are undecided (reuse `interest_candidates` / review state);
   - keep `grade`; keep projects / y4 / y4-validation optional. Labels are short and plain. Remove references to "上一阶段" / phase numbers.
2. **Y4 section of the report without AI.** Where the draft reads career calibration texts (`careerInterests` / `abilityTendencies` / `valuePreferences`), fall back to `y4_snapshot.snapshot_summary_text(session.script.y4Snapshot)` when the calibration row is empty, which is now always the case for new sessions. The PDF must still render all three Y4 cards.
3. **Simpler confirm API.** Today the client must call prepare (job), then preview (fingerprint), then confirm with that fingerprint and two checkboxes.
   - Add `POST /api/v2/copilot/sessions/<id>/report-confirm` support for a body `{"revision": n}` with **no** fingerprint/acknowledgements. The server builds the draft, checks the gate, and confirms in one request. Return `{report: {id, version, confirmedAt, confirmedBy}, revision}` or 422 `{missing: [...]}`.
   - Keep accepting the old fingerprint body for compatibility, but the new UI won't send it.
   - Keep `report-prepare` / `report-preview` for the read-only draft preview (`GET`-style use by the UI). Make `report-preview` return `missing` alongside the draft.
4. **No auto generation.** Remove any server-side trigger that generates next steps or projects as a side effect of moving steps or preparing the report. The jobs remain callable explicitly: `POST …/next-steps`, `POST …/projects`.
5. **Model label.** Replace the hard-coded `DEEPSEEK_MODEL` labels (`copilot_report.py:358`, `growth_talk_store.py` ≈ 654) with `analysis.model_name()` from V1.
6. **Session status.** On confirm set `status="COMPLETED"`. On any content-writing route for a COMPLETED session, set `status="REVIEW"`. This lives in `blueprints/copilot.py` write routes; touch only the status line there, and coordinate by keeping the change minimal.

## Acceptance (`test_ft_v3_report.py`)
- Session with 3 scored interests + summary + grade, no transcript → one-step confirm succeeds; version 1; session COMPLETED; PDF downloads; the Y4 cards are filled from the snapshot.
- Only 2 scored interests → 422 listing `min-interests`. Missing summary → `summary`. Undecided transcript candidate → `pending-suggestions`.
- Editing interests after confirm → status REVIEW; confirming again → version 2.
- The old fingerprint confirm path still passes its existing tests.
- Full suite green.

Commit message: `feat(first-touch): optional transcript, explicit AI drafting, one-step report confirmation`
