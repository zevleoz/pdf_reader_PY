# M1 production readiness implementation plan

**Start with P0.** A delayed report edit was omitted from a draft export and, in a separate run, from a report that published successfully. Fix this before any rollout. Run Flash A alongside P0. Start Flash B after P0 merges because both touch the report workspace.

Use the audited release baseline `b333a3a` on `origin/main`. Read the relevant section and named files for each assignment. Leave 1M context off. If the starting revision changes, repeat that assignment’s reproduction on the new revision. [Audit and screenshots](../2026-11-22-m1-production-readiness.html)

| Order | Assignment | Owner | Audit findings |
| --- | --- | --- | --- |
| 1 | Save, publish and export the reviewed revision | Lead engineer | M1-01 |
| Parallel with 1 | Flash A · Roster error recovery and keyboard interaction | Flash | M1-04 roster, M1-05 roster |
| After 1 | Flash B · Keyboard-accessible report uploads | Flash | M1-05 report |
| After Flash A | Student task status, First Meeting and delivery labels | Lead engineer + product | M1-02, M1-03, M1-07 |
| After 1 | Durable generation recovery, starting with preparation | Lead engineer | M1-04 generation |
| After 1 and Flash B | Responsive report review | Design + report engineering | M1-06 |
| After the above | Staging and staff pilot | QA + operations | Release gates |

Use separate branches or worktrees for independent assignments. Use synthetic records, a temporary SQLite database, and local browser tests. Each assignment hands back changed files, the test command and result, and any remaining decision or failed check.

## 1. Save, publish and export the reviewed revision

**Primary files** `static/m1/report_edit.js`, `static/m1/report_workspace.js`, `templates/m1/report_workspace.html`, `blueprints/m1_report.py`, `m1/report_store.py`. Read `static/m1/plan.js` (`runSessionExport`), `blueprints/m1_plan.py` (session print), and `test_dp16c_regressions.py` for the existing pattern. Search both JS editors and all report print and publish callers before changing the contract.

1. **Capture the regression.** Edit a field in the report iframe, trigger its save, hold the write server-side and click `导出 PDF`. Repeat on a fresh draft with `正式发布`. Coordinate request order with an explicit test barrier so the test remains deterministic. The baseline exports the old value, and the independent publish run returns 200 followed by 409 on the delayed write.
2. **Use one save barrier.** The report workspace must know when either editor is dirty, saving, failed or conflicted. Flush the focused iframe field, debounced fields and queued writes through one sequencing contract before export, publish or reopen. If using a message bridge, verify the expected origin and frame, and correlate request and acknowledgement. Wait for server-acknowledged revisions. Keep failed text visible with a retry. Treat a lost write response as an uncertain result and reconcile before retrying. A stopped action preserves the editor and its pending text.
3. **Bind the review to a revision.** The publish request carries `expected_rev` and `version_id`. Read a coherent report and version, run the existing mandatory checks for that candidate, then commit with an atomic compare-and-swap on revision, version and eligible status. A competing document edit and publish must have a single winner. Cover the write paths that affect publication, including changes used by its checks. Return a conflict with a clear route back to review when the candidate changed. Keep the existing distinction between required checks and advisory findings.
4. **Bind print to saved content.** Open the print tab during the click, indicate it is preparing, and navigate after saves succeed. Require both revision parameters when supplied and validate them in the same read transaction as the print payload. On mismatch, show a recovery message instead of starting the print dialog. Keep authorized read-only links able to open the saved copy. Make publication read-only in the iframe immediately and refresh it from the committed state.
5. **Preserve the published artifact.** Store the exact published content, actor and timestamp before reopening can change it. Reopen against a separate editable revision. Verify existing report-based plans, including their source fingerprints and stale-data cues, when deciding how to copy versions. Keep existing print links and draft watermark behavior. The authoritative artifact is the approved or published snapshot defined by current policy.

**Acceptance.** Test export and publish separately with a pending write, failed save, a second tab updating the report, and a double-click. Assert both the persisted revision and the text returned by the print route. Confirm that a reopened draft cannot rewrite the saved official artifact. Verify read-only co-mentor export and denial after permission revocation. Use `test_m1_report_flow.py`, `test_m1_report_nonblocking.py`, `test_m1_report_print.py`, `test_m1_report_preview.py`, `test_dp15_student_access.py`, and one browser regression covering both actions. Existing markup assertions can change where the new interaction replaces their contract.

## Flash A · Roster recovery and keyboard interaction

> Work on `/m1`. Scope is `templates/m1/home.html`, `static/m1/m1_home.js`, and focused roster tests. `test_m1_roster.py` and `test_m1_roster_home.cjs` are the starting points. Use the existing shell and Chinese terminology.
>
> Replace the apparent zero on first load with a loading state. Render a roster request failure with a persistent `重试` button. Show a successful empty result only after a successful response. Handle candidate-picker failures in the open dialog separately so the roster remains usable. Keep search and filters when retrying and prevent a late response from replacing a newer one.
>
> Make the Add Student dialog keyboard-modal. Initial focus goes inside, Tab and Shift+Tab stay inside, and Escape and Cancel restore the trigger. If a direct link opened the dialog, return focus to a meaningful visible control. Give the roster’s status filter buttons a labeled group and an updated pressed state.
>
> Verify `503 → retry → rows`, a real empty roster, and `picker 503 → retry → candidates` in Chrome. Open the dialog by keyboard, cycle focus in both directions, then verify Escape and focus restoration. Check the active filter after keyboard selection at desktop and 375 px. The First Meeting routing and eligibility rules belong to the lead assignment below.

## Flash B · Keyboard-accessible report uploads

> Start from the branch that includes the P0 change. Scope is the source section of `templates/m1/report_workspace.html`, the upload bindings in `static/m1/report_workspace.js`, and focused report tests. Keep accepted file types, validation, transcript replacement confirmation and current upload endpoints.
>
> Make `选择文件` and `上传文件` actual keyboard-operable controls with accessible names. Keep drag and drop as an additional gesture. Place accepted formats and upload errors by the corresponding control. Return focus after an error or cancellation and preserve successful upload announcements.
>
> With keyboard only, pick a transcript and a supplementary file. Verify cancel, retry after a failed upload, and replace an existing transcript. Check pointer upload and drag and drop once. Run the report flow tests and record the browser result.

## Student task status, First Meeting and delivery labels

**Primary files** `blueprints/m1.py`, `m1/roster.py`, `m1/store.py`, `m1/plan_store.py`, `static/m1/m1_home.js`, `static/m1/m1_student_hub.js`, `static/m1/m1_student.js`, `static/m1/m1_lists.js`, and the corresponding M1 templates. Integrate profiling through `frontend/src/pages/StudentProfile.tsx` and the existing profile API. Coordinate any report template wording after Flash B.

1. Build one permission-aware projection of student tasks from the existing store records. Each task exposes the document, current stage, available action or blocking reason, responsible role, and resume link. Derive roster `有待办` from actionable tasks. Use the same report and plan state for the roster, hub, meeting and profiling views. Keep First Touch and M1 as separate workflows. Keep the profiling completion rules while surfacing open M1 work as an optional workbench item after the same-student handoff works.
2. Give `查看学生` and `新建首次会议` separate intents. Existing navigation links still resolve. A student-scoped create link opens a preselected form, resumes an open prep, or gives the unmet requirement and a link to Y4. Product must confirm whether a finalized First Meeting permits another. Until that decision, keep the existing picker restriction and show the existing meeting in the hub. Align eligibility and enforcement once the decision is made.
3. Keep open report work visible when a plan exists or finishes. Offer report-based plan creation once the report draft is eligible, and standalone plan creation where the user has access. Use distinct progress states for a scheduled date and a held meeting. Until Product assigns ownership of meeting confirmation, show the scheduled date and use a neutral state for elapsed dates.
4. Explain the family handoff beside the action. Identify draft report, official family report, internal session and parent development plan. Show whether the artifact is ready or exported, and explain where staff share it. Treat recording a family share as a separate product decision.

**Acceptance.** Test no meeting, open prep, final prep, incomplete Y4, report ready with no plan, report open with exported plan, read-only co-mentor and denied viewer. Verify direct and report-based creation, an exact resume link, return to the same profiling student, and no new meeting loop. Run roster, M1 platform and profiling profile tests. If adding the workbench item, run `test_profiling_workbench_api.py` and verify completion counters on an unaffected student.

## Durable generation recovery

**Primary files** `m1/jobs.py`, `m1/report_jobs.py`, `m1/plan_jobs.py`, the M1 generation routes, and their polling clients. Start with preparation, where a fresh session with an existing draft never polled in the audit.

Persist the active attempt and previous draft reference server-side. Return authorized job status from document detail so a new browser can resume. Reuse existing workers. Retry transient status errors with a bounded interval and visible recovery. Reconcile dead or stale workers, keep the saved draft available, and use an atomic attempt identity so two starts or a late worker cannot overwrite a newer result. Extend the same status contract to report and development plan after preparation is verified. Merge the report polling change after Flash B and before the responsive review implementation because they share the report controller.

**Acceptance.** With a fake worker, test new tab, fresh session, existing draft, a transient status 503, worker termination and retry, simultaneous start, and completion from an obsolete attempt. Confirm that progress follows existing document permissions and that job logs omit source text.

## Responsive report review

**Primary files** `templates/m1/report_workspace.html`, `static/m1/report_workspace.js`, `static/m1/report_workspace.css`, and the report editor and print templates. Start after the P0 save barrier and Flash B. Design reviews the section editor with a mentor before engineering changes the authoring flow.

Move task editing and issue navigation to a responsive section view. List required checks where staff start review. Each item focuses its field and exposes the relevant evidence and speaker context. Keep a distinct printable preview served by the existing A4 renderer. Use the P0 save and revision contract during the transition. Product confirms phone authoring scope. The phone workflow must at least support triage, reading, reaching the next task, and seeing save and publication state.

**Acceptance.** Walk one required check from issue to evidence to corrected field. Verify keyboard order, focus, save status and reflow at 320 and 375 CSS px plus 200% zoom. Check desktop and mobile views, then validate the printed report and draft watermark against the existing print fixtures.

## Staging and rollout gates

1. **Before pilot.** Deploy the candidate revision to staging. Repeat the delayed-save walkthrough, verify report publication and each PDF audience, and run the targeted suites plus the normal repository suite. Confirm that browser tests ran on a runner with Chrome and localhost binding.
2. **Pilot.** Have one admin, one primary mentor and one co-mentor each complete their relevant scenario on staging. Include an interrupted generation, a permission change, keyboard operation, and the agreed mobile workflow. Record dead ends, stale exports, lost edits, and time to reach the intended task. Require zero stale exports, lost edits or dead-end primary actions.
3. **Before wider rollout.** Record the deployed revision, verify the profiling and questionnaire paths, rehearse backup and restore of the database and document files, and confirm rollback and job monitoring. Release only when the pilot gates are met.
