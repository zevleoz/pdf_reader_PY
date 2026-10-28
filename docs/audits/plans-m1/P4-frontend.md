# P4 — Frontend (home, sources, review, print)

Model: Sonnet · 1M context: **on** · Wave 2 (runs in parallel with P3) · Needs P2 merged

Read first:
- `plans-m1/README.md`, contract §3–5
- `docs/audits/m1-prep-prototype.html` — **the design**. Copy its markup, CSS and interactions.
- `docs/audits/m1-screens/` (screens + `m1-sample.pdf`)
- `templates/layouts/admin_v2.html`
- `templates/first_touch/workspace.html`, as the house pattern for Alpine, autosave and CSRF

## You own

- `templates/m1/home.html`
- `templates/m1/workspace.html`
- `templates/m1/print.html`
- `static/m1/m1.css`
- `static/m1/m1_home.js`, `static/m1/m1_workspace.js`, `static/m1/m1_doc.js` (the shared renderer)
- `test_m1_pages.py`
- `templates/layouts/admin_v2.html`: one nav item 「M1 会前准备」 after First Touch, hidden for Viewer. Check `app_utils.nav_for_role`; if the nav is built there, add the item there instead and say so in your report.
- `templates/student_360.html`: one 「M1 会前准备」 button linking to `/m1?student=<id>`.

## Screens (follow the prototype exactly; drop its yellow notes column and prototype bar)

1. **Home `/m1`**
   - The list of preps: student, meeting date, mentor, status, one action per row.
   - 「＋ 新建会前准备」 opens the picker from `/api/m1/students`; students that can't start are disabled and show their reason.
   - `?student=<id>` opens that student's draft, or the picker preselected on that student.
2. **Workspace `/m1/preps/<id>`**
   - Stepper ① 资料 / ② 生成 / ③ 审阅定稿, driven by prep status.
   - **① Sources**
     - The info bar.
     - Six source cards with status pills: auto cards come from `GET /api/m1/preps/<id>`; upload and paste cards use the P2 routes.
     - The confirmation sheet.
     - 「确认并生成」 calls `POST /generate`.
   - **② Generating:** poll `GET /api/m1/jobs/<id>` every 2 s and show the step list. The mentor may leave the page.
   - **③ Review**
     - The A4 document rendered by `m1_doc.js` from the doc JSON plus the KB and Y4 evidence; ask P2's GET to include both.
     - Click-to-edit blocks with the AI / 已修改 / 导师 markers.
     - Autosave 700 ms after typing stops, via `PUT /doc` with `rev`. On a 409, show a banner 「内容已在别处更新」 with 「载入最新版」, and keep the local text in a copy-able box.
     - The right panel:
       - priority toggles, with the Part 3 sync prompt exactly as in the prototype;
       - 「从 18 项中添加」;
       - 「加入我想问的问题」, which adds a backup with `origin: "mentor"`;
       - 需要留意.
     - The safety banner plus acknowledgement; 确认定稿 / 基于此版本再修改; the timestamps line (AI 初稿 / 导师最后审核).
3. **Print `/m1/preps/<id>/print`**
   - The same renderer with markers hidden.
   - Print CSS from the prototype: `@page` A4, footer 「M1 FM会前准备框架 · <student>」 + page number, `thead` repeat, no orphan headings.
   - A 「草稿」 tag on drafts.
   - The 「下载 PDF」 button calls `window.print()`, the same as E4.
   - The workspace's 「预览 / 下载 PDF」 opens this page in a new tab and calls `POST /export`.

## The PDF must match the reference

Compare your print output with `m1-screens/m1-sample.pdf` page by page:
- the 🧭 title;
- headings with 「｜」;
- grey header rows and hairline borders;
- the 💡 / 🗣️ / 📋 callouts;
- the red 3.3 heading;
- the 3.2 table with 5 columns.

Everything comes from the prototype CSS, under the `.a4` scope.

## Rules

- Render block text with `textContent`, never `innerHTML`. Read the edited text back as plain text.
- Develop against `fixtures/m1_doc_sample.json` before P3 lands.
- No CDN beyond what `admin_v2.html` already loads.
- Phone width: no horizontal page scroll. Wide tables scroll inside their own container.

## Tests

- `/m1` returns 200 for admin and advisor, and 403 for viewer.
- The nav item is hidden for viewer.
- The workspace renders the fixture doc server-side shell without errors.
- The print page contains the footer text and no marker elements.
- The 360 page has the M1 button.

## Done when

- `pytest -q` is green.
- Attach screenshots to your report: home, sources, review, the sync prompt, the safety banner, and pages 1 and 4 of the print.
- Use a DB copy in a temp dir, never the live DB.
