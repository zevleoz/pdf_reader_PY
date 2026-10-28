# P2 — Data model + backend (sources, preps, permissions)

Model: Sonnet · 1M context: off · Wave 1 (runs in parallel with P1)

Read first: `plans-m1/README.md` (contract §1–5) and spec §4 and §7.

## You own

- `m1/store.py`
- `m1/sources.py`
- `blueprints/m1.py`
- `fixtures/m1_doc_sample.json`
- `test_m1_store.py`, `test_m1_api.py`
- `app.py`: add the `m1` blueprint import and registration only.

Create `m1/__init__.py` only if P1 hasn't yet; keep it empty.

## 1. `m1/store.py`

SQLAlchemy models on `db.Base`, created by the existing `init_db` / `create_all` path. Check how `growth_talk_store` registers its tables and copy that.

| Table | Columns |
|---|---|
| `m1_preps` | id, student_id, meeting_date (str), mentor_user_id, duration (int, default 60), attendees (JSON text), status (`draft` / `generating` / `review` / `final`), current_version_id, rev (int), safety_ack_by, safety_ack_at, created_by, created_at, updated_at |
| `m1_sources` | id, prep_id, category (`parent` / `case_review` / `other` / `first_touch_extra`), label, filename, stored_path, text, detected_date, status (`ok` / `partial` / `unreadable`), uploaded_by, created_at |
| `m1_versions` | id, prep_id, n, kind (`ai_draft` / `edit` / `final`), y4_snapshot (JSON), kb_version, evidence (JSON), ai_output (JSON), doc (JSON), ai_generated_at, reviewed_at, created_by, created_at |

Rules for versions:
- `ai_draft` and `final` rows never change after they are written.
- Mentor edits go into one `edit` row per draft, which is overwritten while `rev` matches.
- `reopen` copies the `final` doc into a new `edit` row.

Functions:
- CRUD for the tables above.
- `can_access(user, student_or_prep)` — README §3. Reuse `app_utils._advisor_scope` for the advisor-name rule.
- `audit(user_id, student_id, action, details)` — write to the existing `audit_log` table (`growth_talk_store.AuditLog`).

## 2. `m1/sources.py`

- `auto_sources(student_id) -> dict` with:
  - `y4`: `m1.y4_evidence.build_y4_evidence`. P1 writes it; import it lazily, and in your tests mock it if P1 hasn't landed.
  - `first_touch`: the latest copilot session's records. See `growth_talk_store.CopilotSession` and the related tables. Return the date plus the text the pipeline needs.
  - `questionnaires`: one row per questionnaire in the bank, built from `questionnaire_store.list_assignments_for_student` and the published rules:
    - `已完成` — answers exist; return the answers grouped by each question's `dimension`;
    - `未取得` — the questionnaire was sent but has no answer yet;
    - `未触发` — no assignment exists.
- `add_upload(prep_id, filename, data, category, user)`:
  - extract text with `growth_talk.upload.extract_upload` and keep its error messages;
  - save the file under `data/m1_uploads/<prep_id>/` (outside `static/`);
  - set `detected_date` from the first `YYYY-MM-DD`, `YYYY年M月D日` or `M月D日` in the filename or text.
- `add_text(prep_id, text, category, user)`.

The meeting date is never auto-set. When the text mentions a meeting date, return it as a `suggested_meeting_date` hint instead.

## 3. `blueprints/m1.py`

Implement every route in README §5 **except** generate/jobs, which belong to P3.
- Page routes render `templates/m1/home.html` and `templates/m1/workspace.html`, which P4 creates. Until P4 lands, return a minimal placeholder if the template is missing.
- Use `page_login_required`.
- Reject Viewers with 403 on every `/m1` and `/api/m1` route.
- Follow the CSRF pattern of existing APIs.
- `GET /api/m1/students`: only students the user can access, each with `y4_complete` and a reason when it's false (e.g. 「Y4 尚未完成」).
- `GET /api/m1/preps/<id>` also returns `kb` (per ability: code, name, dim, gap_note, ask, indicator_note), `fixed` (the KB fixed text), and `y4_items` (text, abilities, band — **never `raw`**). P4 renders the Appendix and fixed sections from these.
- `PUT /doc`: compare `rev`. On a mismatch return 409 with `{doc, rev}`. On success, `rev + 1`.
- `finalize` refuses with 409 while `doc.flags.safety` is non-empty and not acknowledged.
- Every write adds an audit row. The 360 page link uses `/m1?student=<id>`.

## 4. `fixtures/m1_doc_sample.json`

A complete doc in the README §4 shape for the prototype's fictional student 林晓雨. Use the prototype's content (`docs/audits/m1-prep-prototype.html`: `ABIL`, `PRIORITY_DETAIL`, `EVENTS`). P4 renders this file, so fill every field.

## Tests

- Tables are created.
- `can_access`:
  - admin sees everything;
  - an advisor sees their own students and preps they mentor;
  - a different advisor gets 403;
  - a viewer gets 403.
- Upload:
  - txt, docx and pdf are each extracted;
  - an empty file gives a 400;
  - files are not reachable under `/static`.
- Questionnaire status mapping gives each of 已完成 / 未取得 / 未触发.
- `rev` conflict returns 409.
- `finalize` is blocked until the safety flag is acknowledged.
- `reopen` keeps the final unchanged.

## Done when

`pytest -q` is green and the fixture loads with `json.load`.
