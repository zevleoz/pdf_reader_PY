# Tasks

- [x] Task 1: Build the app shell foundation (new files, no page changes yet)
  - [x] 1.1 Create `templates/app_shell.css`: sidebar layout variables, grouped nav styles, active indicator, collapsed state, mobile drawer + overlay, command palette styles, view-transition rules, all using existing palette (`--paper/--ink/--red` from `style.css`)
  - [x] 1.2 Create `templates/app_shell.js`: single NAV definition (4 groups, 8 links, Chinese labels, inline SVG icons), auto active-state by `pathname`, renders into `[data-app-shell]` mount, collapse toggle with `localStorage`, mobile drawer + overlay + Esc, Cmd+K palette with fuzzy filter and keyboard navigation, sidebar footer (admin badge via `/api/admin/check`, 登出 via `/api/admin/logout` → `/login`), `@view-transition` friendly
  - [x] 1.3 Add two routes in `app.py`: `GET /app_shell.css` and `GET /app_shell.js` (serve from `TEMPLATE_DIR`, mirroring the `/style.css` route; no other Python changes)

- [x] Task 2: Migrate all internal pages to the shell
  - [x] 2.1 `index.html` (报告生成): remove topbar/brand-stripe, add shell include, keep all upload/logic markup and JS untouched
  - [x] 2.2 `students.html` (学生档案): same migration
  - [x] 2.3 `dashboard.html` (数据总览): same migration
  - [x] 2.4 `transcript.html` (解读会纪要): same migration
  - [x] 2.5 `admin_bookings.html` (预约管理): same migration; keep its `.tabs` booking/status switching logic
  - [x] 2.6 `booking.html` (预约测评): same migration (public page; nav links intact, auth-guarded pages just redirect)
  - [x] 2.7 `internal.html` (内部下载): remove only the global topbar; keep the functional `lab-topbar` and its tool logic
  - [x] 2.8 `prompt_lab.html` (Prompt Lab): add shell include (it has no global nav today); keep `lab-topbar` and 3-column tool layout intact
  - [x] 2.9 Standardize page headers on migrated pages (title + subtitle aligned to shell spacing); no functional text changes

- [x] Task 3: Consistency polish of shared surfaces
  - [x] 3.1 `landing.html`: update marketing nav labels to match shell naming (生成报告 → shell labels; keep landing layout/animations)
  - [x] 3.2 `login.html`: light visual polish only (align palette/focus states); keep standalone gate structure
  - [x] 3.3 `templates/style.css`: refresh shared components (buttons, cards, tabs, tables, focus-visible, spacing rhythm) preserving palette and class names/selectors used by page JS

- [x] Task 4: End-to-end verification
  - [x] 4.1 Start the Flask server locally; visit all 8 migrated routes + landing + login; confirm shell renders, active state correct, no console errors
  - [x] 4.2 Regression check: on `/generate` the upload slots + progress polling work; on `/booking` the calendar works; on `/admin/bookings` tabs work; on `/prompt-lab` the 3-column tool works (JS unaffected)
  - [x] 4.3 Responsive check at 1440px / 1024px / 768px / 390px: no horizontal scroll, drawer works, palette works
  - [x] 4.4 Confirm protected routes still redirect to `/login` when unauthenticated

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 can run in parallel with Task 2 (different files, except style.css used by all — merge after Task 2 edits to avoid conflicts)
- Task 4 depends on Tasks 1-3
