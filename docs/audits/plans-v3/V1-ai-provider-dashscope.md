# V1 · Switch First Touch AI to the project's DashScope key

Wave 1 · Independent. Small.

## Rules for this task (read first)

- Repo: `/Users/jefflau/projects/pdf_report_converter/PDF_converter` (git, branch `first-touch-merge`). Python: `/Users/jefflau/anaconda3/bin/python`.
- **Design spec:** `docs/audits/first-touch-v3-prototype.html`. Open it in a browser; it's a clickable prototype of the new flow, and its right-hand "logic notes" column states the rules each screen must follow. Where this plan and the prototype disagree, this plan wins.
- Background: `PRODUCT.md` (one level up) and `docs/audits/plans-v3/README.md`.
- **Edit only the files listed under "Files you own".** Other agents work in this same checkout at the same time.
- Commit only your own files, by explicit path: `git add <your files> && git commit -m "<message>"`. Never `git add -A`, `git add .`, `git stash`, `git reset`, `git checkout -- .`, or anything that touches other people's changes. Don't push.
- Never edit red-line files (spec `docs/superpowers/specs/2026-10-14-y4-platform-2.0-design.md` §2): `extract.py`, `generate.py`, `data_points.py`, `validate.py`, `gauge_reader.py`, `gauge_processor.py`, anything in `new_iteration/`, deploy files, `/api/v1/*` contracts. Importing from them is fine.
- Flask + Jinja + Alpine.js (CDN). No Node, npm or build step. UI copy is Chinese, in the existing tone.
- **Never read from or write to `data/y4_students.db`** (real student data). Tests use their own fixtures. For manual browser checks, use a copy: `sqlite3 data/y4_students.db ".backup '/tmp/<you>/ft.db'"`, then `DATABASE_URL=sqlite:////tmp/<you>/ft.db SECRET_KEY=dev PORT=<free port> python app.py`. The copy already contains admin, advisor and viewer accounts; ask the owner for logins, or create throwaway ones on the copy with `db.create_user(...)`.
- **Never print, log, commit or copy an API key value.** Refer to keys only by their environment-variable name.
- Don't drop database tables or delete rows. Removing a feature means removing its routes, UI and code, not its stored data.
- Reuse fixtures from `test_copilot_routes.py` / `test_copilot_gapfixes.py` (`client`, `login_as`, `qdb`, `_inline_jobs`). Put new tests in the new test file named below. When you remove a feature, delete or update the tests that only covered it, and list them in your report.
- Done = your new tests pass, `python -m pytest -q --ignore=new_iteration` is fully green, and you committed. If another agent's in-progress edit breaks an unrelated test, say so in your report instead of "fixing" their file.
- Final report: files changed, commit hash, test counts, removed tests, and anything you couldn't do.

## Files you own
- `growth_talk/analysis.py` (the `call_model` function and its config constants only)
- `.env.example`, `docs/deployment_env.md`
- New: `test_ft_ai_provider.py`

## Problem
Every First Touch AI feature calls `growth_talk/analysis.py: call_model()`: talking points, transcript analysis, summary, project ideas, Copilot chat and career calibration (call sites in `growth_talk/copilot.py` and `growth_talk/analysis.py`). It only reads `DEEPSEEK_API_KEY`, a colleague's key that isn't configured here, so every AI button fails with "未配置画像分析服务".

The rest of the platform uses Alibaba DashScope. `ai_client.py:216` reads `os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY)`, and the base URL `https://dashscope.aliyuncs.com/compatible-mode/v1` is OpenAI-compatible: same `/chat/completions` shape that `call_model` already builds.

## Do
1. Make `call_model` use DashScope's OpenAI-compatible endpoint:
   - **Key:** `FT_LLM_API_KEY` if set, else `DASHSCOPE_API_KEY`, else `extract.DEFAULT_DASHSCOPE_KEY`. That's the same fallback `ai_client.py` uses, so the owner's existing key is reused. Import `extract` lazily inside a small `_api_key()` helper (it's a heavy module). **Don't copy the key literal anywhere.**
   - **Base URL:** `FT_LLM_BASE_URL`, default `https://dashscope.aliyuncs.com/compatible-mode/v1`.
   - **Model:** `FT_LLM_MODEL`, default `qwen-plus`.
   - Keep `temperature`, `response_format: {"type": "json_object"}` (qwen-plus supports JSON mode; every prompt already says "JSON"), the system prompt and response parsing unchanged. Raise the timeout from 60 to 90 seconds.
   - Remove the `DEEPSEEK_*` constants and env reads.
2. Add `model_name() -> str` returning the configured model. Other modules currently hard-code `os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")` as a label (`growth_talk/copilot_report.py:358`, `growth_talk_store.py` ≈ line 654). Don't edit those files (other agents own them); list both lines in your report so V3b can switch them to `analysis.model_name()`.
3. Error messages: a missing key → `AI 服务未配置（DASHSCOPE_API_KEY），请联系管理员`. HTTP 401/403 → `AI 服务密钥无效或无权限（{code}）`. 429 → `AI 服务繁忙，请稍后重试`. Other codes keep the existing message.
4. `.env.example` and `docs/deployment_env.md`: document `FT_LLM_API_KEY`, `FT_LLM_BASE_URL`, `FT_LLM_MODEL`, and that `DASHSCOPE_API_KEY` is the default source. Remove `DEEPSEEK_*` from the docs.

## Acceptance (`test_ft_ai_provider.py`, mock `urllib.request.urlopen`, no network)
- No env vars set → the request goes to `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` with model `qwen-plus`, and the `Authorization` header equals `"Bearer " + extract.DEFAULT_DASHSCOPE_KEY`. Compare inside the test; never print it.
- `DASHSCOPE_API_KEY=test-a` → uses `test-a`. `FT_LLM_API_KEY=test-b` overrides it. `FT_LLM_MODEL` / `FT_LLM_BASE_URL` override their defaults.
- A 401 maps to the key-invalid message; a JSON body in `choices[0].message.content` is parsed as before.
- Manual (owner, optional): on a DB copy, click "AI 生成提示" (after V4b) or call one Copilot question. One real call costs a few fen.

Commit message: `feat(first-touch): use the project's DashScope key for all First Touch AI calls`
