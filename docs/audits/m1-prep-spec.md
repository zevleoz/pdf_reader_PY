# M1 First Meeting 会前准备 — Platform spec (draft v2)

> 2026-10-28 · Sources: team requirement 《M1 First Meeting 自动化工具开发需求》 (8 pages), 《M1 FM会前准备框架》 (20 pages), 《R4能力说明 2.0》 (pasted).
> Status: **agreed 2026-10-28** (owner decisions folded in, see §0). HTML design study: `m1-prep-prototype.html`.
> v2 changes: §5 rebuilt from the real framework; §8 inputs mostly received; new §8a check of the framework against Y4 code; §11 questions updated.

---

## 0. Decisions at a glance (my recommendations)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Where it runs | ✅ **Inside the existing Y4 Flask app on the Aliyun ECS**, as a new section `/m1`. Not a separate website, not Vercel. |
| D2 | Stage 1 scope | One student → sources → confirm → AI draft → edit in the A4 preview → confirm final → **download the 会前准备框架 PDF**. |
| D3 | AI provider | DashScope (the key First Touch 3.0 already uses). AI returns **structured JSON per section**; code places it into a fixed template. |
| D4 | Knowledge base | Versioned JSON files in the repo (same pattern as `six_am/model_v06.json`). No editing UI in stage 1. |
| D5 | Who can see M1 | ✅ Admin: all. M1 mentors get **new Y4 Advisor accounts** (none exist yet; admin creates them). An advisor sees a prep when they are its M1 Mentor or own the student. Viewer: **no access**. |
| D6 | PDF | ✅ Same as E4: 「预览 / 下载 PDF」 opens a print preview and the browser saves the PDF (`window.print()`). No server-side Chrome. |
| D7 | Scores | ✅ **No raw numbers in the report.** Y4 evidence shows the indicator name + standardized band (e.g. 焦虑/安详：需关注). Raw values stay in the backend for the AI and the audit trail. This deliberately departs from framework 2.2 「同时呈现原始数值」. |
| D8 | 补充问卷 | ✅ Read from Y4's questionnaire system (ERQ+CERQ, 社交能力, ANX, DEP, STRESS, IAD), not uploaded. |

---

## 1. Hosting: ECS vs Vercel

### Verdict: ECS, inside Y4

| Factor | ECS (inside Y4) | Vercel (like E4) |
|---|---|---|
| Where the data is | Y4 indicators, labels (`evaluation_rules.py`), 6AM profiles, First Touch records and questionnaire answers are all in the same SQLite DB. Direct reads. | Everything over `/api/v1` through the Cloudflare Tunnel. E4's handoff records ~30% transient `fetch failed` on that path. New endpoints needed for FT records, questionnaires, raw labels. |
| The requirement itself | Says 「工具暂时集成在现有 Y4 测评平台中」. | Contradicts it. |
| Accounts and permissions | Y4 roles (Admin / Advisor-owns-students / Viewer) already match §9 of the requirement. | Second account system (Supabase). Mentors would need accounts in both. |
| Privacy | Data stays on Aliyun (mainland) and DashScope (Aliyun). | Parent feedback, family relationships and emotional records of minors would live on Supabase/Vercel, likely outside the mainland. That is sensitive personal information under PIPL and raises cross-border questions. |
| Long AI jobs | Existing subprocess job runner + polling (`growth_talk/jobs.py`) already handles the tunnel's ~100 s limit. | Serverless time limits; long jobs need a queue you don't have yet. |
| PDF output | Browser print, as in E4 (D6). | Browser print. |
| Rich editor UI | Harder: Jinja + Alpine, no build chain. First Touch 3.0 proves autosave, conflict merge and block edit work in this stack. | Easier: React. |
| Cost | No new services. | Vercel + Supabase plan, second deploy pipeline. |

### What M1 adds to a 2 GiB machine

M1 adds **no resident process**. The AI runs remotely on DashScope, so a generation job is mostly waiting on the network.

| Work | Peak memory (rough) | Mitigation |
|---|---|---|
| Text extraction from PDF / DOCX / TXT (reuse `growth_talk/upload.py`) | < 50 MB per file | 10 MB per-file limit |
| Generation job (subprocess, ~6–8 DashScope calls) | ~80–120 MB | One M1 job at a time (queue) |
| PDF | 0 MB on the server | Rendered by the mentor's browser (D6), as in E4 |

**Before launch, run on the server at a busy time:**

```
free -m
ps -eo rss,comm --sort=-rss | head -15
```

Rule: if the `available` column is under ~400 MB at peak, upgrade the ECS to 4 GiB before M1 goes live. Either way, add a 2 GB swap file as a safety net.

**When Vercel would be the better choice:** if M1 mentors are E4 mentors who have no Y4 accounts and should not get one. (Open question Q2.)

---

## 2. What M1 reuses (it is mostly assembly)

| Existing piece | Used for |
|---|---|
| Y4 schema_124 data + `evaluation_rules.py` labels | The Y4 source. Read from the DB, **never re-read from PDFs by AI** (requirement §3.2). |
| 6AM profile | Shown **under** Y4 as "derived from Y4". Never a separate evidence source, never double-counted. |
| First Touch 3.0 sessions (会前 / 会谈中 / 会后) | The First Touch source, auto-filled when present. |
| Questionnaire subsystem (raw answers) | The 补充问卷 source. Y4 stores raw answers only, without scores, so scored results come from an uploaded file. |
| `growth_talk/upload.py` `extract_upload` | PDF / DOCX / TXT text extraction. |
| `growth_talk/jobs.py` | Async generation + polling. |
| E4 `PrintPreviewModal` pattern | 「预览 / 下载 PDF」 via the browser print dialog, with A4 print CSS. |
| From E4 (pattern, not code) | Freeze the Y4 snapshot when a prep is created; the document is the editor (click-to-edit A4 preview); 700 ms autosave; "mark final". |

---

## 3. Stages

| Stage | Delivers | Goal |
|---|---|---|
| **1 — this spec** | End-to-end path to a downloadable 会前准备框架 PDF | Mentors use it for a real meeting |
| 2 — editing depth | Regenerate one section without touching manual edits; Appendix ↔ Part 2 ↔ Part 3 sync prompts; version history view/restore; Word export | Fewer manual fixes |
| 3 — governance | Audit-log viewer; file retention and deletion; safety-flag handling workflow; per-student access lists; knowledge-base editor UI | Required before wide rollout |
| 4 — after the meeting | M1 meeting record (like E4's first report), feeding the Student 360 page | Closes the loop |

**Built in stage 1 even though the UI comes later:** separate storage of raw / standardized / original conclusion / AI / mentor edit; immutable versions; audit-log rows. These are cheap now and expensive to add later.

---

## 4. Stage-1 user flow

Three steps, one page each. The mentor never has to read the 18 abilities one by one.

**Entry points**
- Sidebar 「M1 会前准备」 → student list with status (未开始 / 草稿 / 已定稿) and meeting date.
- Student 360 page → 「M1 会前准备」 button.
- Only students with a complete Y4 can start one (same gate as First Touch 3.0).

**Step ① 资料 Sources**
- Top bar, prefilled and editable: 学生 / 年级 / 学校 (from the student record) · 会议日期 · M1 Mentor · 时长 (60 / 75 / 90 / custom) · 参会人员.
- Six source cards, each with a status pill: 已获取 / 部分信息 / 未提供 / 无法识别.
  - **Y4 Assessment** — auto, ✓ 已获取. Shows the assessment date; 6AM is listed inside this card.
  - **First Touch** — auto when there is a record; otherwise upload or paste.
  - **家长初始反馈** — upload or paste.
  - **补充问卷** — automatic from Y4's questionnaire system, one row per questionnaire: 已完成 (answers in) / 未触发 (trigger rules did not fire, no task) / 未取得 (task sent, no answers yet). Each question carries a `dimension`, so answers are grouped per dimension (e.g. ERQ 认知重评 / 表达抑制) for the AI. No norms, no scores in the report.
  - **Case Review** — multiple files, each with its own date.
  - **其他资料** — free type + upload or paste.
- On upload, a quick AI pass guesses category, date and a one-line summary. The mentor can correct any of them.
- The 「确认资料并生成」 button opens a confirmation sheet: file name, category, date, extracted summary. Missing sources are listed as 「未提供 → 报告中显示信息不足」. Nothing is mandatory except Y4.

**Step ② 生成 Generating**
- A progress list by section, about 1–3 minutes. The mentor can leave; the job continues and the list page shows 「生成中」.

**Step ③ 审阅 Review & download**
- Left: the A4 report, click any block to edit it. AI blocks carry a small "AI" marker that disappears once a mentor edits the block.
- Right panel:
  - **Priority abilities** (3–5 suggested): toggle on or off, each with its reason.
  - **Meeting plan**: events and questions; add own question ("Case Review 团队想问的").
  - **Warnings**: 信息不足 items, cross-part mismatch (for example "R3.5 未在 Part 3 安排核实"), safety flag.
- Buttons: 保存草稿 (autosave as well) · **确认定稿** (locks this version) · **预览 / 下载 PDF** (browser print, as in E4; a draft prints with a 「草稿」 mark).
- 「返回资料」 goes back to Step ①; regenerating keeps the old version.

---

## 5. Report structure (from 《M1 FM会前准备框架》, section by section)

Who fills each block: **Code** = fixed text or Y4 data, no AI · **AI** = structured JSON placed by code · **Mentor** = edited or added in Step ③.

| Section | Content | Filled by |
|---|---|---|
| 1.1 Meeting Overview | Basic info row; the fixed 4-stage structure (会前资料整合 → First Meeting → 家长补充 → 综合分析); the meeting agenda table (5 segments) | Code. The agenda adapts to the chosen duration: 60 min standard; 75–90 min stretches 03 Event-based to cover 2–3 events. |
| 1.2 Sources & Completeness | One row per source: what was extracted + status (完整／部分／未取得, 补充问卷 per questionnaire 已完成／未触发／未取得) + date and origin | Code from Step ①; the one-line "extracted" summary is AI (from the upload pass), editable |
| 2.1 R4 Initial Assessment | R1–R4 × Potential / Interference / Key Evidence Gap, each with R codes and sources | AI (summarised from the 18-ability review) |
| 2.2 Priority R4 Abilities | 3–5 rows (fewer allowed): ability · 原始 Evidence / VERDICT · AI 初步假设 · 为什么本次需要确认 | Evidence column: code (indicator + band, verbatim quotes; no raw numbers). Hypothesis and reason: AI. Selection: AI proposes, mentor toggles. |
| 2.3 Evidence Conflicts & Special Attention | Conflicts between two independent sources; contextual factors (family, school, peers, recent changes); special attention (stale data, key gaps, risk signals) | AI; risk signals also trigger the safety banner |
| 3.1 R4 Quick Check | Four open questions, one per R dimension, with goal | Code (fixed questions from the framework) — AI may only reword for age |
| 3.2 Event-based Exploration | 1–2 events (2–3 for 75–90 min): situation · existing clue + source · linked priority abilities · gap to verify · 2–4 follow-ups; the 5-step path box (Situation → Recognize → Regulate → Relate → Recover) | AI; the path box is fixed text. No real event → 开放探索主题. |
| 3.3 Backup Questions | Only priority abilities not covered by 3.2: ability · missing evidence · question · timing (第 4 环节 / 可延后) | AI + mentor's own questions |
| 3.4 Reflection & Growth Direction | Student growth wish prompts; possible next directions | AI (directions only; Intervention decided by Mentor later) |
| Appendix · R4 Full Evidence Review | 18 rows grouped R1–R4: related Y4 indicators (**this student's bands**, no raw numbers) with the framework's fixed analysis-and-gap note · 会议中需确认 (fixed question from framework) · 证据核验 (student-specific) · 推荐 / 暂不推荐 with reason | Indicators and question: code. 证据核验 and recommendation: AI, mentor reviews. |

**Left out of the PDF (internal only):** the 💡 example boxes, every 〔AI 填写…〕 instruction, 「Appendix 使用规则与证据解释标准」 and 「Y4 标准化评价与 Signal 判读（内部使用）」. These become backend rules and prompt text (requirement §6).

Rules for every part:
- Empty → 「信息不足」 or 「尚未取得相关资料」. Never invented content.
- Export is blocked if any 〔…〕 placeholder survives (automatic scan).
- Y4 bands are never presented as R4 ability levels. The Appendix states that 未推荐 ≠ 能力正常.
- Every Part 2.2 priority ability must have a slot in 3.2 or 3.3 (validator).

---

## 6. Analysis pipeline (backend)

**A. Evidence items.** Every source becomes a list of items, each with:
- `id`, `source`, `date`
- `kind`: direct behaviour / indirect measure / context / professional inference
- `independence_group`: everything from Y4, including 6AM, shares the group `Y4`
- `text` and a verbatim `quote`

How each source becomes items:
- *Y4:* built by **code**. For each indicator: raw score → label via `evaluation_rules` → mapped abilities and measurement meaning (trait / state / cognitive base / other) from the Mapping. No AI.
- *Uploaded text:* one AI extraction call per document. A validator checks that every `quote` exists in the source text; items that fail are dropped. This is the anti-fabrication guard.
- *Case Review:* each statement is tagged as either independent observation or interpretation of Y4. Interpretations go to 「待验证假设」, never to facts (requirement §4.2).

**B. Per-ability judgement (18 abilities, in 4 calls, one per R dimension).**
Input: the ability definition, its Layer-1 Mapping gap and the relevant evidence items.
Output JSON:
- potential, interference
- known, new clues, contradictions, missing
- `worth_verifying` {yes/no, reason}

Every statement must cite evidence ids. Two independent sources are needed to call something "supported". Items from the same `independence_group` count once.

**C. Priority.** Code scores the factors from requirement §5.1:
- impact
- Potential / Interference
- gap importance
- conflict
- family concern
- Case Review hypothesis

AI writes the reasons. The result is 3–5 abilities, or fewer if evidence is thin.

**D. Meeting plan.** Each event must cite a real evidence item; if none exists, the plan offers an 开放探索主题 instead. Each event gets 2–4 open follow-ups. Backup questions cover only gaps the events miss. A validator checks that every priority ability has a slot in Part 3.

**E. Assemble.** Code fills the template, runs the placeholder scan and stores the version.

**Safety.** A keyword + AI flag catches self-harm, abuse or crisis content and shows a red banner. The mentor must acknowledge it before 确认定稿. The tool never writes a diagnosis or a referral decision.

---

## 7. Data model (SQLite, auto-created at startup like the First Touch tables)

| Table | Holds |
|---|---|
| `m1_preps` | student_id, meeting_date, mentor_user_id, duration, attendees, status (draft / final), current_version_id, created/updated |
| `m1_sources` | prep_id, category, label, file name, stored path, extracted text, detected date, status, uploaded_by |
| `m1_versions` (immutable) | prep_id, n, kind (ai_draft / edit / final), y4_snapshot, kb_version, evidence_items, ai_output, doc (blocks with `origin` ai/mentor and `ai_original`), ai_generated_at, reviewed_at, created_by |
| `m1_audit` | user, prep_id, action (upload / generate / edit / final / export), at |

- Uploads live in `data/m1_uploads/<prep_id>/`, outside `static/`, and are served only through an auth-checked route.
- Mentor-edited blocks (`origin = mentor`) are never overwritten by a regeneration.

---

## 8. Inputs needed from the team (blockers for build)

| # | Item | Status |
|---|---|---|
| K1 | R4 ability list | ✅ 《R4能力说明 2.0》: 18 abilities (R1 ×4, R2 ×5, R3 ×6, R4 ×3) with description and development direction. 典型场景 and 导师 Toolbox exist for R1 only — not needed for stage 1. |
| K2 | Mapping and Gaps | ✅ Embedded in the framework Appendix: per ability, the related Y4 indicators, the analysis-and-gap note and the 会议中需确认 question. **Confirm this is the latest Mapping.** |
| K3 | Y4 有效评价规则 | ✅ Framework p.19. Checked against code in §8a. |
| K4 | 《M1 FM会前准备框架》 | ✅ Received (PDF; an MD version is coming, used to build the knowledge-base file exactly). |
| K5 | Past real cases | **None exist** (new service). Replaced by: 3 fictional test students (all sources / Y4 only / conflicting sources) for automated tests, and a team review of the first 3 real preps before wider use. |

The older `.trae/documents/r4-y4-judgment-logic.md` (R4 × Y4 draft) is superseded by K2 and will not be used.

### 8a. Framework checked against the Y4 code

| Check | Result |
|---|---|
| Every indicator named in the Appendix exists in schema_124 | ✅ All present, including 依恋类型 (020–022), 自我概念 (051–058), 思维模式 (059), 学习自我效能感 (068), 学习自我调节 (071), 内省能力 (085), 职业价值观 (095–109). |
| Banding rules vs `evaluation_rules.py` | ✅ Same thresholds for cognitive (≥98 / ≥95), 情绪稳定性 total and four sub-items, Big Five, attachment trust / communication / closeness, self-concept sub-items, executive function, career interest, ability strengths, and the μ ± 0.5 norm rule. |
| Gap 1: 职业价值观 score bands (≥9 高 … <5 明显偏低) | ❌ Not in code — Y4 hides these scores and keeps only the ranking. M1 needs them for R1.4. Add as an M1-side rule. |
| Gap 2: out-of-range value or missing norm → 「无法判读」 | ❌ Code bands any number (e.g. trust = 0 → 偏低). Add a range check in the M1 layer. `evaluation_rules.py` itself stays untouched, because 6AM and reports depend on it. |
| R4 VERDICT | Y4 has no R4 verdict engine. Stage 1 shows the band, and the VERDICT cell reads 「无直接对应」, as the framework allows. |
| 补充问卷 | ✅ In Y4 already (D8), with trigger rules (`_rules_v1.json`) and a `dimension` per question. Y4 stores raw answers without scoring, so M1 groups answers per dimension and shows no numbers.

---

## 9. Out of scope for stage 1

- Word export
- Regenerate one section
- Version-history UI
- Knowledge-base editor
- OCR of scanned PDFs or images (stage 1 shows 「无法识别，请粘贴文字」)
- Audio
- Parent-facing anything

---

## 10. Stage-1 acceptance

1. A student with only Y4 → full PDF. Missing parts read 「信息不足」. Zero placeholders.
2. Every event and quote in Part 3 traces to a real source excerpt (validator + the 3 fictional test students).
3. 6AM never appears as an independent source or a second vote.
4. Every Part 2 priority ability has a Part 3 slot.
5. Mentor edits survive reload and autosave conflicts.
6. An advisor opening another advisor's prep gets 403; a viewer cannot open `/m1`.
7. Uploaded files are not reachable by a direct URL without login.
8. 预览 / 下载 PDF prints a clean A4 document in Chrome and Edge: no buttons, no AI markers, no raw scores.
9. The existing test suite stays green, and the red-line report files are untouched.

---

## 11. Owner decisions (2026-10-28)

- Q1 Hosting → ECS inside Y4.
- Q2 Accounts → M1 mentors get Y4 Advisor accounts (none yet).
- Q3 Viewer → no access.
- Q4 PDF → like E4: browser print, downloadable.
- Q5 Past cases → none; fictional test students + review of the first real preps.
- Q6 Scores → no raw numbers; bands only.
- Still to confirm with the team: the framework Appendix is the latest Mapping.
