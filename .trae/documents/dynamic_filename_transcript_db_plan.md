# Plan: Dynamic Filename + Transcript Feature + Cloud DB (v2)

## Priorities

1. **HIGH**: Dynamic PDF filename → `凭远Y4评测报告_{学生姓名}.pdf`
2. **HIGH**: Transcript upload → AI 解读会会议纪要 (structured by report, natural tone, summary)
3. **v2 NEXT**: Cloud database (Neon PostgreSQL) for student records

***

## Priority 1: Dynamic PDF Filename

### Problem

Currently output is always `report.pdf`, downloaded as `综合测评报告.pdf`.

### Solution

Extract student name from `report_data.json` after generation, then rename the output file and set the download name dynamically.

### Files to Modify

**`generate.py`** (L1408-1439) — `main()` function:

* After generating `report.pdf`, read student name from `report_data.json`

* Rename `report.pdf` → `凭远Y4评测报告_{姓名}.pdf`

* Also rename `report.html` → same basename

**`app.py`** (L236-246) — `api_generate()` route:

* After `_generate_module.main()`, find the dynamically named PDF

* Set `download_name` to `凭远Y4评测报告_{姓名}.pdf`

* Update the URL returned to frontend

### Steps

1. In `generate.py main()`: after PDF creation, read student name, rename files
2. In `app.py`: after generation, find the dynamic PDF name, use it for download

***

## Priority 2: Transcript → AI 解读会会议纪要

### What it does

Upload a text transcript (from speech-to-text of the analysis session), AI generates a structured meeting minutes document that:

* Follows the Y4 report's 4-section layout (心力/情绪 → 精力/健康 → 学习力 → 生涯力)

* Reads naturally, not formulaic/AI-ish

* References specific test data points when relevant

* Ends with an executive summary

### Files to Create/Modify

**New file:** **`prompts/transcript_summary.md`**

* AI prompt that instructs the model to:

  * Organize transcript content by Y4 report sections

  * Write in natural, conversational Chinese (like a senior consultant's notes)

  * Reference student data where relevant

  * Flag contradictions or notable patterns

  * End with a 3-paragraph executive summary

**New file:** **`templates/transcript.html`**

* UI for uploading transcript (textarea or file upload)

* Shows generated 会议纪要 after processing

* References the current student being analyzed

**Modify:** **`app.py`**

* New route: `GET /transcript` → render transcript page

* New route: `POST /api/transcript` → accept transcript text, call AI, return structured summary

  * Takes context: student name + report\_data.json (for cross-referencing)

  * Uses the same DashScope API as `/api/chat`

  * Returns structured summary with sections

**Modify:** **`templates/index.html`**

* Add a "解读会纪要" button next to the student info section

* Links to `/transcript` with the current student context

### Report Sections (for prompt reference)

Based on the 18-page report structure:

1. **心力｜情绪与动力系统** (Pages 3-8): 情绪稳定性, 自我概念, 依恋关系, 内驱力, 人格
2. **精力｜精力管理与身体健康系统** (Pages 9-10): 体质健康
3. **学习力｜学习系统** (Pages 11-15): 认知能力, 执行功能, 学习动机与策略
4. **生涯力｜专业与职业发展系统** (Pages 16-18): 职业兴趣, 能力优势, 职业价值观

***

## Priority 3 (v2): Cloud Database — Neon PostgreSQL

### Why Neon

* Free tier: 0.5GB storage, unlimited time, serverless PostgreSQL

* No credit card required for free tier

* Connection string format: `postgresql://user:pass@host/dbname`

* Python driver: `psycopg2` or `SQLAlchemy`

### Setup (User does once)

1. Go to [neon.tech](https://neon.tech) and create free project
2. Copy connection string
3. Set as environment variable: `DATABASE_URL=postgresql://...`

### Files to Create/Modify

**New file:** **`db.py`** — Database layer

* Uses `SQLAlchemy` with PostgreSQL (or SQLite as fallback)

* Tables: `students`, `reports`, `bookings`

* Full CRUD functions

**New file:** **`alembic/`** **or just init** — Schema migration

* Simple `init_db()` that creates tables on first run

**Modify:** **`requirements.txt`**

* Add `SQLAlchemy>=2.0`

* Add `psycopg2-binary>=2.9`

**Modify:** **`app.py`**

* Add DB initialization at startup

* After PDF generation succeeds, write student + report to DB

* New routes: `/api/export` (CSV), `/students` (student list), `/booking` (booking page)

### Database Schema

```sql
CREATE TABLE students (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    gender TEXT,
    birthday TEXT,
    grade TEXT,
    email TEXT,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    student_id INTEGER REFERENCES students(id),
    report_date DATE NOT NULL,
    pdf_path TEXT NOT NULL,
    data_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE bookings (
    id SERIAL PRIMARY KEY,
    student_name TEXT NOT NULL,
    student_email TEXT,
    student_phone TEXT,
    appointment_time TIMESTAMPTZ NOT NULL,
    status TEXT DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

***

## Implementation Order

1. **Phase 1**: Dynamic PDF filename (modify `generate.py` + `app.py`)
2. **Phase 2**: Transcript feature (new `prompts/transcript_summary.md` + `templates/transcript.html` + `app.py` routes)
3. **Phase 3**: Neon DB + student management (new `db.py` + modify `app.py` + new templates)

***

## Verification

1. Generate report → downloaded as `凭远Y4评测报告_张三.pdf`
2. Upload transcript → AI generates structured 会议纪要 with 4 sections + summary
3. Student data persists in Neon DB
4. `/students` page lists all students with their reports
5. `/api/export` downloads CSV of all student data
6. All existing functionality (upload, generate, chat, AI analysis) still works

