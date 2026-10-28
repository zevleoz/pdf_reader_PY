# Start messages for the M1 agents

Workspace for every agent: `/Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/m1-prep`, branch `m1-prep`. That is a separate checkout, so your `six-am-v06` folder is untouched.

Model: Sonnet for all four. 1M context: off for P1/P2, **on** for P3/P4.

## Wave 1 — start P1 and P2 together

P1 needs `docs/audits/plans-m1/framework.md` in the workspace first.

### P1

```
You are implementing plan P1 of the M1 build.
Work only in /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/m1-prep (branch m1-prep). Do not cd anywhere else.
Read docs/audits/plans-m1/README.md, then docs/audits/plans-m1/P1-kb-y4.md, and follow P1 exactly.
Another agent is doing P2 in the same folder at the same time: touch only the files P1 owns.
Do not commit or push. Run tests with: python3 -m pytest -q
When done, report: files changed, test result, and any framework indicator label you could not map to a code.
```

### P2

```
You are implementing plan P2 of the M1 build.
Work only in /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/m1-prep (branch m1-prep). Do not cd anywhere else.
Read docs/audits/plans-m1/README.md, then docs/audits/plans-m1/P2-backend.md, and follow P2 exactly.
Another agent is doing P1 in the same folder at the same time: touch only the files P2 owns. If P1's m1/y4_evidence.py is not there yet, mock it in your tests.
Do not commit or push. Run tests with: python3 -m pytest -q
When done, report: files changed, test result, and anything in the contract you had to interpret.
```

**After wave 1:** run `python3 -m pytest -q` in the workspace. If it's green, commit (`feat(m1): wave 1 — KB, Y4 evidence, backend`) and start wave 2.

## Wave 2 — start P3 and P4 together

### P3

```
You are implementing plan P3 of the M1 build.
Work only in /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/m1-prep (branch m1-prep). Do not cd anywhere else.
Read docs/audits/plans-m1/README.md, then docs/audits/plans-m1/P3-pipeline.md, and follow P3 exactly. P1 and P2 are already committed; read their code before you start.
Another agent is doing P4 in the same folder at the same time: touch only the files P3 owns (plus scripts/m1_dry_run.py). In blueprints/m1.py add only the two routes P3 names.
Tests must never call the real model. Do not commit or push. Run tests with: python3 -m pytest -q
When done, report: files changed, test result, and how to run scripts/m1_dry_run.py.
```

### P4

```
You are implementing plan P4 of the M1 build.
Work only in /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/m1-prep (branch m1-prep). Do not cd anywhere else.
Read docs/audits/plans-m1/README.md, then docs/audits/plans-m1/P4-frontend.md, and follow P4 exactly. The design to copy is docs/audits/m1-prep-prototype.html; the PDF to match is docs/audits/m1-screens/m1-sample.pdf.
Another agent is doing P3 in the same folder at the same time: touch only the files P4 owns. Build against fixtures/m1_doc_sample.json; do not wait for P3.
Never open data/y4_students.db; use a temp DB copy. Do not commit or push. Run tests with: python3 -m pytest -q
When done, report: files changed, test result, and attach the screenshots P4 asks for.
```

**After wave 2:** run the tests, commit (`feat(m1): wave 2 — pipeline, frontend`), then come back to Opus for wave 3.

## Wave 3 — back to Opus

Paste this into an Opus session:

```
M1 wave 3 check. Workspace: /Users/jefflau/projects/pdf_report_converter/PDF_converter/.worktrees/m1-prep (branch m1-prep). Plans in docs/audits/plans-m1/. Review AI output on the 3 test students with scripts/m1_dry_run.py, tune m1/prompts.py, walk every screen as admin / advisor / viewer, and compare the print with docs/audits/m1-screens/m1-sample.pdf.
```
