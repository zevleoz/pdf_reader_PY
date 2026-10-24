# First Touch production fixes — agent plans

Source audit: `../2026-10-24-first-touch-production-audit.md`. Each plan file below is self-contained (the shared rules are already inlined). Hand one file to one agent.

## Order

| Wave | Plans (run in parallel within a wave) | Wait for |
|---|---|---|
| 1 | **A1** revision locking · **B1** workspace UI · **C1** shell header/toast/nav · **C2** config hardening | — |
| 2 | **A2** single session + viewer backend · **B2** viewer/shared-session UI | A1 committed (for A2); B1 committed (for B2) |
| 3 | **A3** manual add / meeting time / Activity Hub | A2 committed |
| 4 | **D1** repo cleanup (alone) | everything else committed |

Why this order: A1, A2 and A3 all edit `blueprints/copilot.py` and `growth_talk_store.py`; B1 and B2 both edit `workspace.html`. Agents in the same wave never share a file.

## Owner decisions (2026-10-24)
1. One First Touch session per student, shared by admin and advisor → A2 + B2.
2. Viewer can see First Touch, read-only (no writes, no AI calls). The archive page stays admin-only → A2 + B2 + C1 (nav).
3. `new_iteration/report_v2.html` edits committed (`ec00dd4`).
4. Delete unused root scratch files with caution → D1.

## Data migrations the owner runs manually (after back-up)
- A2: `scripts/merge_duplicate_copilot_sessions.py --db data/y4_students.db` (dry run), then `--apply`.
- A3: `scripts/normalize_meeting_at.py --db data/y4_students.db` (dry run), then `--apply`.

Back up first: `sqlite3 data/y4_students.db ".backup 'data/backup_$(date +%Y%m%d_%H%M).db'"`.

## After all waves (orchestrator check)
Full pytest. On a DB copy: entry screen → tabs 1–7 with an interest scored 1/1; two tabs editing the same session (the stale one gets a 409, data untouched); admin then advisor opening the same student see the same session; a viewer clicking through everything sends zero non-GET requests; advisor B manually adding a name owned by advisor A gets a new student; Activity Hub export; header at 800/1024/1440px.
