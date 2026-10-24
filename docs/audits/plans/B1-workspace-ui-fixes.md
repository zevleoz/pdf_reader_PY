# B1 · Workspace UI correctness and polish

Wave 1 · Front-end track, step 1 of 2 (B2 edits the same template afterwards).

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
- `templates/first_touch/workspace.html`
- New: `test_audit_workspace_ui.py`

Tab numbers below are the **1-based labels** shown in the UI (1 会议准备, 2 目标说明, 3 Y4 结果解读, 4 兴趣事项, 5 总结与下一步, 6 会后补充, 7 报告确认). In code, `phase` is 0-based.

## Do
1. **Score 1 can't be entered (F1, P0).** `preferenceOptions` / `competenceOptions` (`workspace.html` ≈ line 1237) offer only `0, 2, 3`, labelled `喜欢低（0–1）/中（2）/高（3）`. Those are the 3×3 board's *band* labels, wrongly used for the 4-level *input*. An existing score of 1 renders as "待评" but stays 1 in data.
   - Offer `待评` (empty) + `0, 1, 2, 3` everywhere scores are entered (tab 4 interest cards, tab 6 candidate review ≈ line 756-770).
   - Use one shared label set for both tabs: 喜欢 `不喜欢 / 一般喜欢 / 喜欢 / 非常喜欢`, 擅长 `不擅长 / 一般擅长 / 擅长 / 非常擅长` (tab 6 already uses these; `:2042`). Define it once in the component and reuse it.
   - Keep the band labels `喜欢低（0–1）/ 喜欢中（2）/ 喜欢高（3）` **only** on the tab-5 three-level board.
2. **Navigation shouldn't save or block (F3, client side).** In `goPhase()`, when nothing is dirty, set `this.phase = target` immediately and fire a phase-only PATCH (`{phase, revision}`) in the background, without awaiting it or setting `busy`. Update `revision` from the response. (After backend task A1 lands, phase-only PATCHes return the same revision.) Keep the existing dirty-confirm and report-gate logic. Auto-run `generateNextSteps()` when entering tab 5 only if `script.nextSummary` is empty **and** it hasn't been attempted on this page load.
3. **Meeting time display (F5, client side).** In `_shanghaiParts` / `initMeetingDefaults` (≈ line 1431-1471): if the ISO string has no `Z` or offset, treat it as UTC (append `Z`) before parsing. If the parsed time isn't on a 15-minute slot, round **down** to the nearest slot and set `meetingDirty = true` so the corrected value gets saved. Today a stored `15:23` shows as `00:00`.
4. **Polish (F9).**
   - Show the save status **once**, next to the time picker. Remove the duplicate right-aligned `ft-status` (≈ line 276).
   - Replace the user-facing "修订 N" with `已保存` / `内容待保存` / `正在保存…`. Keep the revision number only in a `title` tooltip.
   - The interest card's "删除" button wraps to two lines: add `white-space: nowrap`, or make it an icon button with `aria-label="删除事项"`.
   - Rename the English label "Note" (≈ line 548) to "备注".
   - Tab 3's kicker reads `02 / Y4 REPORT` while the tab says "3 · Y4 结果解读". Make kicker numbers match the 1-based tabs on every presentation panel.
5. **Floating chat button vs toasts (F8).** Toasts (from `v2Toast` in `templates/layouts/admin_v2.html`, owned by task C1) currently cover the bottom-right chat FAB. C1 will add class `has-toast` to `<body>` while a toast is visible. In this file, add CSS so the FAB moves up (e.g. `body.has-toast .<fab class> { transform: translateY(-72px); }` with a short transition).
6. **Font floor.** Raise every `font-size: 11px / 11.5px` rule in this file to ≥ 12px for body/control text. Only small meta labels (axis ticks, counters) may stay at 11px.

## Acceptance
- `test_audit_workspace_ui.py` (render the workspace page for a session as an advisor and assert on the HTML/JS):
  - option values `0`, `1`, `2`, `3` and the label `一般喜欢` appear in the score options definition;
  - `喜欢中（2）` appears only in the three-level board code, not in the score options;
  - the literal "修订 " isn't in visible text bindings;
  - "Note" label is gone, "备注" present.
- Manual check on a DB copy (see rules) at 1440×900 and 1024×768: score an interest 1/1, save, reload → still 1/1; click through all 7 tabs without edits → no "保存" spinner and no loading block; the toast doesn't cover the chat button (once C1 has landed).
- Full suite green.

Commit message: `fix(first-touch): 0–3 score inputs, non-blocking phase navigation, meeting time parsing, workspace polish`
