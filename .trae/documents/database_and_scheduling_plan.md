# Plan: Student Database + Self-Hosted Scheduling System

## Summary

Build a SQLite-backed student database and self-hosted calendar/scheduling system **around** the existing PDF generation pipeline. The existing upload → extract → validate → generate flow stays 100% intact; we add new layers before (booking) and after (storage, export).

***

## Phase 1: Database + Report Storage + CSV Export

### 1a. Create `db.py` — SQLite Database Layer

**New file**: `db.py`

**Schema:**

```sql
CREATE TABLE students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gender TEXT,
    birthday TEXT,
    grade TEXT,
    email TEXT,
    phone TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    report_date DATE NOT NULL,
    pdf_path TEXT NOT NULL,
    data_json TEXT NOT NULL,           -- full report_data.json content
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_name TEXT NOT NULL,
    student_email TEXT,
    student_phone TEXT,
    appointment_time TIMESTAMP NOT NULL,
    status TEXT DEFAULT 'pending',    -- pending | completed | cancelled
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, name TEXT, gender TEXT, birthday TEXT, grade TEXT, email TEXT, phone TEXT, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, student_id INTEGER, report_date DATE, pdf_path TEXT, data_json TEXT, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY, student_name TEXT, student_email TEXT, student_phone TEXT, appointment_time TIMESTAMP, status TEXT DEFAULT 'pending', notes TEXT, created_at TIMESTAMP);
```

**Key functions:**

* `init_db()` — Create tables if not exist

* `add_student(name, gender, birthday, grade, email, phone)` → student\_id

* `add_report(student_id, report_date, pdf_path, data_json)` → report\_id

* `get_students()` → list of all students

* `get_student_reports(student_id)` → list of reports for a student

* `get_all_reports()` → all reports with student info (for export)

* `get_bookings(status)` → list bookings

* `add_booking(...)` → booking\_id

* `update_booking_status(id, status)`

### 1b. Modify `app.py` — Add Post-Generation DB Write + Export

**File**: `app.py`

**Changes:**

1. Import `db` module at top
2. At startup, call `db.init_db()`
3. After PDF generation succeeds (line \~246, before `return resp`), add DB write:

   * Read student info from `report_data.json`

   * Create/find student in DB (match by name)

   * Save report record
4. **New route**: `GET /api/export` — Export all reports as CSV (uses SQLite → csv module)
5. **New route**: `GET /students` — Student list page (renders `students.html`)
6. **New route**: `GET /api/students` — JSON API for student list
7. **New route**: `GET /api/students/<id>/reports` — JSON API for student's reports
8. **New route**: `GET /reports/<id>` — View/download a specific report

**Non-breaking**: The existing `/api/generate` returns the same PDF response. The DB write is a post-step that doesn't affect the response.

### 1c. Create `templates/students.html` — Student Management Page

**New file**: `templates/students.html`

A simple page showing:

* Table of all students (name, grade, created date, number of reports)

* Click student → see their reports (date, download PDF)

* Export CSV button

* Link back to upload page

***

## Phase 2: Self-Hosted Scheduling System

### 2a. Create `templates/booking.html` — Booking Page

**New file**: `templates/booking.html`

A public page accessible via shared link (no login required):

* Name, email, phone fields

* Date picker

* Time slot picker (e.g., 9:00, 9:30, 10:00, ... 17:00)

* Submit → creates booking in `bookings` table with status 'pending'

### 2b. Modify `app.py` — Add Booking Routes

**File**: `app.py`

**New routes:**

* `GET /booking` — Show booking form

* `POST /api/booking` — Create booking entry

* `GET /admin/bookings` — Admin view of all bookings (status: pending/completed/cancelled)

* `POST /api/booking/<id>/complete` — Mark booking as completed (creates student entry)

* `POST /api/booking/<id>/cancel` — Cancel booking

**How it works:**

1. Colleague opens `/booking` link, fills student info + picks time
2. Booking entry created with status 'pending'
3. On admin page, mark as completed → creates student entry in `students` table
4. Student comes in, takes the test
5. Admin uploads 4 PDFs on the main upload page, generates report
6. Report auto-saved to DB linked to student

***

## Phase 3: Link Booking → Upload Flow

### 3a. Modify `templates/index.html` — Add Student Selection

**File**: `templates/index.html`

Add a dropdown at the top of the upload form:

* "Select existing student" dropdown (fetches from `/api/students`)

* Or "New student" option (manual entry as before)

* When a student is selected, the upload → generate → store flow links to that student

### 3b. Modify `app.py` — Accept student\_id in generate

**File**: `app.py`

* `POST /api/generate` accepts optional `student_id` form field

* If `student_id` is provided, the generated report is linked to that student

* If not, creates/finds student by name

***

## Files to Create/Modify Summary

| Action     | File                      | Description                                                        |
| ---------- | ------------------------- | ------------------------------------------------------------------ |
| **New**    | `db.py`                   | SQLite database layer (tables + CRUD)                              |
| **Modify** | `app.py`                  | Add routes: export, students, bookings, booking, post-gen DB write |
| **New**    | `templates/students.html` | Student management page                                            |
| **New**    | `templates/booking.html`  | Public booking page                                                |
| **Modify** | `templates/index.html`    | Add student selection dropdown                                     |
| **Modify** | `requirements.txt`        | Add `xlsxwriter` for Excel export (optional, CSV is built-in)      |

## Verification

1. Upload PDFs → report generated → student + report in database
2. `/students` page shows student list
3. `/api/export` downloads CSV
4. `/booking` page accepts bookings
5. Bookings can be marked completed, creating student entries
6. Upload page can link to existing students
7. Existing PDF generation flow still works identically

