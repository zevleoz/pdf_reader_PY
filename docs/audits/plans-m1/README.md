# M1 会前准备 — stage-1 build plans

Goal: inside the Y4 Flask app, a mentor picks a student, confirms sources, gets an AI draft of the 《M1 FM会前准备框架》, edits it in place, confirms it as final, and prints a PDF that looks like the reference.

| What | Where |
|---|---|
| Spec | `docs/audits/m1-prep-spec.md` |
| UI and PDF look | `docs/audits/m1-prep-prototype.html` — copy its markup and CSS; don't reinvent them |
| PDF reference | `docs/audits/m1-screens/m1-sample.pdf` (8 A4 pages) |

Hand one plan file to one agent.

## Waves

| Wave | Plans | Model | 1M context | Waits for |
|---|---|---|---|---|
| 0 | Branch `m1-prep` (from `main` 3aabce3) is ready as worktree `PDF_converter/.worktrees/m1-prep`. Owner: put the framework MD at `docs/audits/plans-m1/framework.md` there. Start texts: `START.md` | — | — | — |
| 1 | **P1** knowledge base + Y4 evidence ‖ **P2** data model + backend | Sonnet | off | W0 |
| 2 | **P3** AI pipeline ‖ **P4** frontend | Sonnet | **on** for both | W1 |
| 3 | **Opus check**: AI quality on 3 test students, prompt tuning, full walk, PDF vs reference | Opus | — | W2 |

The two plans in a wave own different files, so they can run at the same time. P4 builds against `fixtures/m1_doc_sample.json` (shape below), so it does not wait for P3.

## Rules for every agent

- Touch only the files your plan owns. If you need a change elsewhere, stop and report it.
- Don't commit or push; the owner commits after each wave.
- **Red-line files are read-only:**
  - `extract.py`, `generate.py`, `data_points.py`, `validate.py`, `gauge_*.py`
  - `new_iteration/render_v2.py`, `new_iteration/report_v2.html`
  - `evaluation_rules.py`
  - deploy files: `gunicorn_config.py`, `nginx_y4.conf`, `y4_report.service`, `deploy/`
  - `/api/v1/*`
- Never open the real `data/y4_students.db`. Tests use the conftest guard and temp databases.
- `pytest -q` must stay fully green. Add your own tests, named `test_m1_*.py`.
- Chinese UI copy, the same style as the prototype. No new Node build and no new pip packages.

## Shared contract

### 1. Package layout

```
m1/__init__.py
m1/kb/r4_abilities.json         P1   18 abilities + mapping + fixed text
m1/kb.py                        P1   loader + validator
m1/y4_evidence.py               P1   Y4 → evidence items (bands, no AI)
m1/store.py                     P2   tables + data access
m1/sources.py                   P2   auto sources (FT, questionnaires, 6AM) + uploads
blueprints/m1.py                P2   pages + /api/m1/*
m1/pipeline.py                  P3   generation steps A–E
m1/prompts.py                   P3
m1/validate_doc.py              P3   placeholder scan, quote check, P2→P3 coverage
m1/jobs.py                      P3   background job (same pattern as growth_talk/jobs.py)
templates/m1/*.html             P4
static/m1/m1.css, static/m1/*.js  P4
fixtures/m1_doc_sample.json     P2   writes it from §4; P4 reads it
```

Shared files, one owner each:
- `app.py`: P2 adds one blueprint import + registration.
- `templates/layouts/admin_v2.html`: P4 adds the nav item.
- The student 360 template: P4 adds the M1 button.

### 2. Evidence item (P1 and P2 produce, P3 consumes)

```json
{"id": "y4-013", "source": "y4|six_am|questionnaire|first_touch|parent|case_review|other",
 "source_ref": "report:12 | m1_source:5 | copilot_session:3 | assignment:9", "date": "2026-09-02",
 "kind": "indirect|direct|context|inference|hypothesis",
 "group": "Y4 for y4 and six_am; otherwise the source_ref",
 "text": "情绪稳定性—焦虑/安详：需关注", "quote": "",
 "abilities": ["R1.1", "R2.1"], "band": "需关注", "raw": 7}
```

`raw` exists only for Y4 items. It is stored but **never rendered** (owner decision: bands only).

### 3. Access rule (P2 implements `m1.store.can_access(user, prep_or_student)`)

| Role | Sees |
|---|---|
| Admin | Everything |
| Advisor | Students where `students.advisor_name` equals their name, plus any prep where they are `mentor_user_id` |
| Viewer | Nothing: `/m1` returns 403 and the nav item is hidden |

### 4. Document JSON (`m1_versions.doc`; P3 writes it, P4 renders and edits it)

Every editable piece is a **block**: `{"id": "...", "text": "plain text, \n allowed", "origin": "ai|mentor", "ai_text": "..."}`.
- The renderer escapes the text; there is no HTML in blocks.
- An edit sets `origin` to `mentor` and keeps `ai_text` unchanged.

```json
{
 "meta": {"student": "", "grade": "", "school": "", "meeting_date": "", "mentor": "", "duration": 60, "people": []},
 "sources": [{"key": "parent|y4|questionnaire|first_touch|case_review|other", "label": "", "extracted": BLOCK, "status_text": ""}],
 "dims": [{"dim": "R1", "potential": BLOCK, "interference": BLOCK, "gap": BLOCK}],
 "priority": [{"code": "R2.2", "evidence": ["code-built lines, bands and verbatim quotes"], "hypothesis": BLOCK, "why": BLOCK}],
 "special": {"conflict": BLOCK, "context": BLOCK, "attention": BLOCK},
 "events": [{"id": "ev1", "title": BLOCK, "clue": "text with source + date", "abilities": ["R2.2"], "gap": BLOCK, "questions": BLOCK}],
 "backups": [{"code": "R3.5|null", "missing": BLOCK, "question": BLOCK, "timing": "第 4 环节；如已回答则跳过"}],
 "growth": {"wish": BLOCK, "next": BLOCK},
 "appendix": [{"code": "R1.1", "recommend": false, "reason": BLOCK, "check": BLOCK}],
 "flags": {"safety": [{"text": "", "source_ref": ""}], "insufficient": ["其他资料：未取得"]}
}
```

- Appendix indicators, gap notes and 会议中需确认 questions are not stored in the doc. The renderer takes them from the KB plus the Y4 evidence snapshot.
- Fixed framework text comes from the KB: agenda, callouts, 3.1 questions, headings.

### 5. API (P2 owns it; P3 adds the generate/job pair)

| Method | Path | Purpose |
|---|---|---|
| GET | `/m1` | Home page |
| GET | `/m1/preps/<id>` | Workspace page (steps ①③; step ② is a state) |
| GET | `/m1/preps/<id>/print` | Print page |
| GET | `/api/m1/students` | Pickable students: Y4-complete flag + reason, accessible only |
| GET | `/api/m1/preps` | List preps |
| POST | `/api/m1/preps` | `{student_id}` → new prep with auto meta |
| GET | `/api/m1/preps/<id>` | Meta, uploaded sources, auto-source summary, current doc, `rev`, status |
| PATCH | `/api/m1/preps/<id>` | Meta: meeting_date, mentor_user_id, duration, attendees |
| POST | `/api/m1/preps/<id>/sources` | Multipart file or `{text}`, plus category |
| PATCH / DELETE | `/api/m1/sources/<sid>` | Change category/date, or remove |
| PUT | `/api/m1/preps/<id>/doc` | `{rev, doc}` autosave; returns 409 + the server doc if `rev` is stale |
| POST | `/api/m1/preps/<id>/safety-ack` | Acknowledge the safety flag |
| POST | `/api/m1/preps/<id>/finalize` | Refused while a safety flag is unacknowledged |
| POST | `/api/m1/preps/<id>/reopen` | Copies the final into a new draft |
| POST | `/api/m1/preps/<id>/export` | Logs an "export" audit row when print opens |
| POST | `/api/m1/preps/<id>/generate` | **P3**: start a job, returns the job id |
| GET | `/api/m1/jobs/<job_id>` | **P3**: job status |

Rules for these routes:
- Every write is CSRF-protected the same way existing APIs are.
- Every write adds an `audit_log` row.

## When Opus is needed

| When | Why |
|---|---|
| **Wave 3, always** | AI output quality can't be checked by tests: fabricated events, Case Review hypotheses passed off as facts, 6AM double-counted, tone of questions. Opus reads the drafts for the 3 test students, tunes `m1/prompts.py`, and compares the PDF with the reference. |
| An agent reports a contract conflict | Changing §2 or §4 affects two plans at once. |
| The framework or Mapping changes after a team meeting | Decide whether it is a KB edit only or a rule change. |
| Before the production deploy | Deploy checklist, memory check on the ECS, rollback target. |

Not needed: wave 1 and 2 reviews. The owner runs `pytest -q`, and the agents' own tests cover the contract.
