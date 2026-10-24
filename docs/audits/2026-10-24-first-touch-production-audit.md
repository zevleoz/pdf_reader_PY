# First Touch / Copilot 2.0 — Production Audit & Agent Task Briefs

- Date: 2026-10-24 · Branch audited: `first-touch-merge` @ `62aedcf`
- Continues: `.impeccable/critique/2026-10-24T01-06-30Z__…workspace-html.md` (UI critique, 18/40) and
  `docs/superpowers/plans/2026-10-23-copilot-v2-gap-fixes.md` (gap-fix plan, implemented in `be80f2b`, `3f12c08`, `62aedcf`).
- Method: full pytest run (386 passed), live walkthrough on a sandbox copy of the DB (port 8011, throwaway
  test users), code read of `blueprints/copilot.py`, `growth_talk_store.py`, `growth_talk/jobs.py`,
  `templates/first_touch/*`, compared with the original `~/projects/first-touch`.

## 1. Where the earlier critique stands

| Critique item | Status |
|---|---|
| P0 quadrant boards never render | **Fixed** — 4×4 board renders, updates live |
| P0 unscored interests silently become 1/1 | **Fixed** — "待评" option exists, null kept |
| P1 phase 4 is a 7-column spreadsheet | **Fixed** — grouped cards + live board |
| P1 candidate review defaults / conflict UI | Mostly fixed (conflict buttons present) |
| "Browsing bumps revision" (persona red flag) | **Still broken**, see F3 |
| Font floor (11–11.5px) | Still present in `workspace.html` (≈10 rules) |

## 2. New findings (ranked)

Phase names below use the **1-based tab labels** (1 会议准备 … 4 兴趣事项, 5 总结与下一步, 6 会后补充, 7 报告确认); code uses 0-based `phase` indices.

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| F1 | P0 | **Score 1 can't be entered.** Phase 4 "喜欢/擅长" selects only offer `0,2,3` (labels `低（0–1）/中（2）/高（3）` — the 3×3 *band* labels were applied to the 4-level *input*). An existing score of 1 renders as blank/"待评" while still stored as 1. Phase 6 uses different labels (`不喜欢/一般喜欢/喜欢/非常喜欢`, 0–3). | `workspace.html:1237-1246`, compare `:756-770`; original `CopilotWorkspace.tsx:227` offers 0–3 |
| F2 | P0 | **Optimistic lock is not atomic.** Every write route checks `revision`, then commits data in separate transactions, *then* CAS-bumps the revision. A losing concurrent request still persists its data, then raises `RevisionConflict` (not caught in these routes → 500). Same in background jobs: an LLM job writes results, then fails the CAS if anything bumped the revision during the 30–90 s run. | `blueprints/copilot.py:252-353, 356-418, 422-474, 477-535`; `growth_talk/jobs.py:205-240`; `growth_talk_store.py:1359` |
| F3 | P1 | **Phase navigation bumps the revision** (observed 34→37 just clicking tabs). Combined with F2 this makes jobs fail and two-tab/two-user editing 409 constantly. Entering phase 5 ("总结与下一步") also auto-launches an LLM job every visit while `nextSummary` is empty. | `workspace.html` `goPhase()` → `savePhase(target)` always PATCHes; `api_save_phase` always bumps |
| F4 | P1 | **Manual "add student" merges across advisors.** `api_create_student` → `db.find_or_create_student` matches by **name only**: advisor B adding "Eric" gets advisor A's Eric, overwrites its `school`, and receives A's student profile in the response (then 404s when opening it). | `blueprints/copilot.py:923-970`, `db.py:447-490` |
| F5 | P1 | **Meeting time is wrong for auto/default sessions.** Server default is naive UTC (`datetime.utcnow().isoformat()`, no `Z`); the browser parses that as *local* time. Times not on a 15-min slot (e.g. `15:23`) can't be shown by the slot `<select>` and display as `00:00`. DB now holds mixed formats (`2026-10-23T15:23:33` vs `…T03:00:00.000Z`). | `blueprints/copilot.py:141-149,187`; `workspace.html:1431-1471` |
| F6 | P2 | **Activity Hub export loses interest category.** Every item is exported as `sourceType:"interest", topicType:"hobby"` regardless of `subject/interest/social`. | `blueprints/copilot.py:1150-1170` |
| F7 | P2 | Admin shell header breaks at ≤ ~930px: breadcrumb "凭远 Y4" and the "管理员" badge wrap one character per line. | `templates/layouts/admin_v2.html` (`.crumb`, role badge) — seen at 800px |
| F8 | P2 | Toasts sit on top of the floating chat button (bottom-right) on every save. | admin_v2 toast + `workspace.html` FAB |
| F9 | P2 | Workspace polish: save status rendered twice ("内容待保存" next to the time picker *and* at the right edge); "删除" button wraps to two lines in interest cards; English label "Note"; user-facing "修订 37" is jargon; phase-3 panel kicker reads "02 / Y4 REPORT" under tab "3 · Y4 结果解读". | screenshots, `workspace.html:276, 548` |
| F10 | P2 | Production config: `SECRET_KEY` silently falls back to `'dev-key-change-in-production'`; no `SESSION_COOKIE_SECURE/SAMESITE`; dead `ADMIN_PASSWORD='y4admin2026'` constant. | `app.py:36, 50-54` |
| F11 | P3 | Repo hygiene: 20 `__pycache__`/`.DS_Store` files tracked (show as modified in every diff); ~880 tracked `_debug_*.py` / `_cell_*.png` scratch files at the repo root. | `git ls-files` |

### Owner decisions (answered 2026-10-24)

1. One shared First Touch session per student → plans A2 + B2.
2. Viewer can see First Touch (read-only) → plans A2 + B2 + C1.
3. `new_iteration/report_v2.html` edits committed as `ec00dd4`.
4. Delete unused root scratch files with caution → plan D1.

**The per-agent plans in `plans/` supersede the briefs in section 3** (section 3 is kept for history).

## 3. Agent task briefs

### Global rules for every agent (paste with each brief)

- Repo: `/Users/jefflau/projects/pdf_report_converter/PDF_converter` (git, branch `first-touch-merge`). Python via `/Users/jefflau/anaconda3/bin/python`.
- **Edit only the files listed under "You own".** Other agents are editing other files at the same time.
- **Don't commit, push or run `git add`/`rm`** (except FT-07). Leave changes in the working tree and list changed files in your final message.
- Never edit red-line files (spec `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md` §2): `extract.py`, `generate.py`, `data_points.py`, `validate.py`, `new_iteration/*`, deploy files, `/api/v1/*` contracts.
- No Node/build tooling; templates are Flask + Jinja + Alpine (CDN). Keep Chinese UI copy in the existing tone.
- Never touch `data/y4_students.db` (real student data). Tests use their own fixtures.
- Done = new tests for your change pass **and** `python -m pytest -q --ignore=new_iteration` is fully green (baseline 386 passed).
- Put new tests in a new file named in your brief (avoids clashes on shared test files). Reuse fixtures from `test_copilot_routes.py` / `test_copilot_gapfixes.py` (`client`, `login_as`, `qdb`, `_inline_jobs`).

### Wave 1 — run in parallel (disjoint files)

#### FT-01 · Make revision locking atomic + stop navigation bumps (F2, F3 backend)
- **You own:** `blueprints/copilot.py` (only the session write routes: `api_save_phase`, `api_save_calibration`, `api_save_interest_draft`, `api_upload_source`, `api_y4_calibrate`, `api_save_projects`, plus helpers), `growth_talk_store.py`, `growth_talk/jobs.py`, `growth_talk/copilot.py`, new `test_audit_revisions.py`.
- **Problem:** routes validate `revision`, commit writes in separate transactions, then call `store.bump_session_revision(expected)`. A stale request still persists data; `RevisionConflict` raised at the bump is uncaught (500). Jobs do the same after a long LLM call.
- **Do:**
  1. Add a store helper (e.g. `claim_revision(session_id, expected, actor_id, action, phase=None) -> int`) that does the CAS `UPDATE … WHERE revision = expected` **before** any writes; raise `RevisionConflict` on 0 rows. In every write route, claim first, then write. Wrap route bodies so `RevisionConflict` → 409 via `_error_response`. (A single-transaction refactor is better if you can do it cleanly; claim-first is acceptable.)
  2. `api_save_phase`: when the body carries **only** `phase` (+ `revision`) and no `interests/script/meetingAt/entryMode/supplementAnalysis/interestReview`, update `phase` **without** bumping the revision and return the unchanged revision.
  3. Jobs (`jobs.py:205-240` and the writers in `growth_talk/copilot.py`: `run_supplement_analysis`, `generate_next_steps`, `generate_projects`, `apply_project_edits`): do the LLM work first, then claim the revision, then write. If the claim fails, write nothing and return a job error whose message tells the advisor the session changed and to regenerate.
- **Acceptance tests:** stale-revision PATCH to each write route returns 409 **and** leaves DB content unchanged; phase-only PATCH returns the same revision and moves `phase`; job with stale revision writes nothing.

#### FT-03 · Workspace UI correctness & polish (F1, F3 client, F5 client, F8 FAB side, F9, font floor)
- **You own:** `templates/first_touch/workspace.html`, new `test_audit_workspace_ui.py`.
- **Do:**
  1. **F1:** make `preferenceOptions` / `competenceOptions` offer all four values `0,1,2,3` + "待评", using one shared label set for phase 4 *and* phase 6 (`不喜欢/一般喜欢/喜欢/非常喜欢`, `不擅长/一般擅长/擅长/非常擅长`). Keep the 3×3 band labels `喜欢低（0–1）…` **only** on the three-level board in phase 5.
  2. **F3 client:** in `goPhase()`, when not dirty, switch `phase` locally and send a phase-only PATCH (no payload), without awaiting or blocking the UI. Only auto-run `generateNextSteps()` on entering phase index 4 if `nextSummary` is empty **and** it hasn't already been attempted this page load.
  3. **F5 client:** in `_shanghaiParts`/`initMeetingDefaults`, treat an ISO string without offset as UTC (append `Z`); if the parsed time isn't a 15-minute slot, round **down** to the nearest slot and mark `meetingDirty` so the corrected value saves.
  4. **F9:** render the save status once (keep the one beside the time picker); replace "修订 N" with plain text such as "已保存 · HH:MM" (keep the revision in a `title` tooltip for debugging); make the interest-card delete button `white-space:nowrap` (or an icon button with `aria-label="删除事项"`); rename "Note" to "备注"; fix the phase-3 kicker so the number matches the tab ("03 / Y4 结果解读").
  5. Move the floating chat button up while a toast is visible, or reserve space for it (coordinate class names with FT-05: the toast container in `admin_v2.html` will expose `body.has-toast`).
  6. Raise all `font-size: 11px/11.5px` rules in this file to ≥12px for body text and ≥11px for meta labels only.
- **Acceptance:** rendered workspace HTML contains `value="1"` in both the phase-4 and phase-6 score selects and no `中（2）` label on the phase-4 select; manual check at 1440×900 and 1024×768 in the sandbox (see §4) — save one interest scored 1/1 and confirm it reloads as 1/1.

#### FT-05 · Admin shell responsive header + toast placement (F7, F8 shell side)
- **You own:** `templates/layouts/admin_v2.html` (and any CSS file it includes, if the header/toast styles live there), new `test_audit_shell.py` (optional; markup assertions only).
- **Do:** at widths 768–1100px the top bar must not wrap characters: truncate the breadcrumb with ellipsis, give the role badge `white-space:nowrap`, collapse the search box to an icon below ~1000px. While a toast is shown, add `has-toast` to `<body>` and remove it on dismiss, and position toasts so they don't cover a bottom-right 64×64 FAB area.
- **Acceptance:** screenshots at 800, 1024, 1440 px wide show a one-line header on `/first-touch`, `/first-touch/students/<id>`, `/students`.

#### FT-06 · Production config hardening (F10)
- **You own:** `app.py` (config block only, lines ~30–60; don't touch `_run_pipeline_job`), `docs/deployment_env.md`, new `test_audit_config.py`.
- **Do:** if `Y4_ENV=production` (or `FLASK_ENV=production`) and `SECRET_KEY` is unset or equals the dev default, refuse to start with a clear message. Set `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, `SESSION_COOKIE_SECURE` from env (default True in production). Remove the unused `ADMIN_PASSWORD` constant (grep first; leave it if anything still reads it). Document the env vars.
- **Acceptance:** tests that create the app with/without production env assert the behaviour; local dev (no env) still starts.

### Wave 2 — start after FT-01 is merged (same file: `blueprints/copilot.py`)

#### FT-02 · Student creation, meeting time and Activity Hub data fixes (F4, F5 server, F6)
- **You own:** `blueprints/copilot.py` (`api_create_student`, `api_create_session`, `_parse_meeting_at`, `_activity_hub_profile`), `db.py` (add a function only; don't change `find_or_create_student`, which OCR and booking use), new `scripts/normalize_meeting_at.py`, new `test_audit_data_fixes.py`.
- **Do:**
  1. **F4:** stop using `find_or_create_student` in `api_create_student`. Dedupe only against students **visible to the caller** (same `advisor_name` for advisors; all for admin) by exact name (+ school when given). On a hit, return it with `existing: true` and **don't modify** any fields. Otherwise create a new student through a new `db.create_student(...)` helper (assign `student_code` the same way existing creation does). Never return a student the caller can't see.
  2. **F5 server:** `_parse_meeting_at` returns a normalized UTC string `YYYY-MM-DDTHH:MM:SSZ` (naive input = Asia/Shanghai local, as the UI sends). The default in `api_create_session` uses the same format. Add an idempotent script that rewrites existing `copilot_sessions.meeting_at` values to that format (naive values were written by `utcnow()`, so treat them as UTC). Don't run it against `data/y4_students.db`; document how to run it.
  3. **F6:** map `topicType` `subject|interest|social` to the Activity Hub enum in `docs/integrations/first-touch-activity-hub/api-profile.schema.json` (read the schema; don't guess), and set `sourceType` correctly. Validate one export against the schema in a test (`jsonschema` if installed; otherwise assert the enum values).
- **Acceptance:** advisor B adding an existing name owned by advisor A creates a new student and A's record is unchanged; meeting time round-trips (`2026-01-01T12:00` Shanghai → stored `…T04:00:00Z` → UI shows 12:00); exported items carry the right topic types.

### Wave 3 — run alone, last

#### FT-07 · Repo hygiene (F11, caches only)
- **You own:** `.gitignore`, git index.
- **Do:** add `__pycache__/`, `*.pyc`, `.DS_Store`, `.pytest_cache/` to `.gitignore`; `git rm --cached` those tracked files (don't delete from disk). **Don't** touch `_debug_*`/`_cell_*` files; list them in your report for the owner. Commit with message `chore: stop tracking caches`.

## 4. How to check the UI without touching real data

A sandbox copy runs on **http://localhost:8011**: config in `/Users/jefflau/projects/pdf_report_converter/.claude/launch.json`, DB copy in the orchestrator's scratchpad.
Test logins are in the scratchpad file `test_creds.txt` (admin + advisor, sandbox only). Agents that need a browser should start their own copy the same way (`sqlite3 data/y4_students.db ".backup '/tmp/…/audit.db'"`, then `DATABASE_URL=sqlite:////tmp/…/audit.db PORT=80xx python app.py`) and create users with `db.create_user` against the copy.

## 5. Verification after all waves (orchestrator)

Full pytest; sandbox walkthrough of entry screen → phases 1–7 with an interest scored 1/1; two-tab edit to confirm a 409 leaves data untouched; advisor-B manual add; Activity Hub export of a confirmed report; header at 800/1024/1440 px.
