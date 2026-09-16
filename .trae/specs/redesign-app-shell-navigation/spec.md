# Unified App Shell & Navigation Redesign Spec

## Why
The web app has grown from 2-3 pages to 9 functional pages, but every page still carries its own hand-duplicated topbar with different link sets (3-8 links), different labels (预约 vs 预约测评, 报告生成 vs 生成报告, 解读会 vs 解读会纪要), and different ordering. Prompt Lab has no global navigation at all; Internal Downloads has two stacked topbars. Switching between pages feels congregated and confusing. The task is a structural UI overhaul — making navigation organized, hierarchical, and modern — with zero changes to functionality, business logic, APIs, or report/AI generation code.

## What Changes
- Add a single-source-of-truth **app shell** (`templates/app_shell.css` + `templates/app_shell.js`) that renders the global navigation on every page via one mount point.
- Navigation becomes a **grouped sidebar** (desktop) / slide-in drawer (mobile):
  - 工作台: 报告生成 (`/generate`), 学生档案 (`/students`), 数据总览 (`/dashboard`)
  - 预约中心: 预约测评 (`/booking`), 预约管理 (`/admin/bookings`)
  - 解读: 解读会纪要 (`/transcript`)
  - 内部工具: 内部下载 (`/internal`), Prompt Lab (`/prompt-lab`)
- **Cmd+K command palette** for quick page jumps (keyboard-navigable, Esc to close).
- **View Transitions API** for smooth cross-page transitions (progressive enhancement; browsers without support fall back to normal navigation).
- Sidebar footer shows admin identity badge + 登出 (calls existing `/api/admin/logout`).
- Collapsible sidebar with state persisted in `localStorage`; hamburger + drawer below 1024px.
- Remove all duplicated topbar markup from 8 templates (`index`, `students`, `dashboard`, `transcript`, `admin_bookings`, `booking`, `internal`, `prompt_lab`); each gets a 3-line shell include instead. Keep each page's own functional sub-toolbars (e.g. `lab-topbar` in `internal` / `prompt_lab`) — only the global nav is unified.
- Standardize a **page header pattern** (title + subtitle, aligned with the shell) on migrated pages without altering page logic.
- Modernize shared components in `templates/style.css` (buttons, cards, tabs, tables, focus states, spacing rhythm) while **keeping the existing brand palette** (paper `#FAF7F2`, ink `#141414`, red `#B33A3A`, Noto Serif SC headings, Inter body).
- Serve the two new shell assets through **2 new Flask routes** in `app.py` (asset serving only, mirroring the existing `/style.css` route).
- `landing.html` keeps its marketing nav but adopts the same link labels for consistency. `login.html` stays a standalone gate page. `report.html` (generated report document) is **untouched**.

## Impact
- Affected specs: none (first spec).
- Affected code:
  - New: `templates/app_shell.css`, `templates/app_shell.js`
  - Modified: `app.py` (+2 asset routes only), `templates/style.css`, `templates/index.html`, `templates/students.html`, `templates/dashboard.html`, `templates/transcript.html`, `templates/admin_bookings.html`, `templates/booking.html`, `templates/internal.html`, `templates/prompt_lab.html`, `templates/landing.html` (nav labels only), `templates/login.html` (visual polish only)
- Protected (must not change): all PDF generation / AI logic in `app.py` and `generate.py`/`extract.py`/`validate.py`/`evaluation_rules.py`, `templates/report.html`, every API endpoint, all page JS business logic (upload slots, polling, chat, E4 mapping, booking flows).

## ADDED Requirements

### Requirement: Unified global navigation shell
The system SHALL provide a shared app shell (CSS + JS) that renders identical global navigation on all internal pages, driven by a single nav definition.

#### Scenario: Same nav everywhere
- **WHEN** the user visits any of `/generate`, `/students`, `/dashboard`, `/transcript`, `/admin/bookings`, `/booking`, `/internal`, `/prompt-lab`
- **THEN** the sidebar shows the same grouped links with the same labels, and the current page is visually marked active (auto-detected from `location.pathname`)

#### Scenario: No logic regression
- **WHEN** any migrated page is loaded
- **THEN** its existing JS business logic (upload slots, polling, chat, booking calendar, E4 tools) runs unchanged; only the nav markup was replaced

### Requirement: Grouped, hierarchical navigation
The sidebar SHALL organize pages into four labeled groups (工作台 / 预约中心 / 解读 / 内部工具) with inline SVG icons (no emoji), a brand block at top, and admin identity + 登出 in the footer.

#### Scenario: Admin footer actions
- **WHEN** a logged-in admin views any internal page
- **THEN** the sidebar footer shows the admin badge and a 登出 button that calls the existing `/api/admin/logout` then redirects to `/login`

### Requirement: Collapsible sidebar and mobile drawer
The sidebar SHALL be collapsible on desktop (state persisted in `localStorage`) and become a slide-in drawer with overlay below 1024px, opened by a hamburger button. No horizontal scrolling at any breakpoint.

#### Scenario: Mobile navigation
- **WHEN** the viewport is narrower than 1024px
- **THEN** the sidebar is hidden behind a hamburger button; opening it slides a drawer over the content with an overlay tap-to-close

### Requirement: Command palette (Cmd+K)
The shell SHALL provide a command palette opened by `Cmd+K` / `Ctrl+K` (and a search affordance in the sidebar) that fuzzy-filters all pages and navigates on Enter; Esc closes it.

#### Scenario: Quick jump
- **WHEN** the user presses Cmd+K and types "学生"
- **THEN** 学生档案 is highlighted and Enter navigates to `/students`

### Requirement: Page transition polish
Cross-page navigation SHALL use the View Transitions API where supported (subtle fade/slide), with graceful fallback elsewhere. Click feedback on nav items is immediate.

### Requirement: Consistent page header
Each migrated page SHALL present a standardized page header (page title + one-line subtitle) consistent in typography and spacing across pages, using existing page content — no functional text changes.

## MODIFIED Requirements

### Requirement: Shared design system (`templates/style.css`)
The shared stylesheet SHALL remain the single design-system source, refreshed with: refined spacing scale, consistent radii/shadows, modern focus-visible states, updated `.btn`/`.card`/`.tab`/table styling. The existing palette variables (`--paper`, `--ink`, `--red`, etc.) are preserved.

#### Scenario: Visual-only refresh
- **WHEN** any page using shared classes is rendered
- **THEN** components look consistent and modern, but all class names, DOM hooks, and JS selectors used by page logic remain intact

### Requirement: Asset serving
`app.py` SHALL gain exactly two new routes: `GET /app_shell.css` and `GET /app_shell.js` serving the shell files from the templates directory, mirroring the existing `/style.css` route. No other Python changes.

#### Scenario: Shell assets load
- **WHEN** any page requests `/app_shell.css` or `/app_shell.js`
- **THEN** Flask serves the file with the correct MIME type

## REMOVED Requirements

### Requirement: Per-page duplicated topbars
**Reason**: Eight pages each hardcode their own topbar with divergent links/labels/order — the root cause of the confusing navigation.
**Migration**: Each template's `<header class="topbar">…</header>` (and the legacy `brand-stripe` where present) is replaced by a shell mount (`<div data-app-shell>` + shell CSS/JS includes). Public `landing.html` keeps its marketing nav; `login.html` keeps its minimal header; functional sub-toolbars (`lab-topbar`) are kept as-is.
