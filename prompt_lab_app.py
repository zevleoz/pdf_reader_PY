"""Y4 Prompt Lab — Standalone 测试台.

一个完全独立的 Flask 应用，用于迭代 Y4 AI 解读的 system prompt。
- 端口 5555，无登录（本地 dev 工具）
- 迭代只动 prompts/ai_interpreter_lab.md（工作副本），不碰生产 prompt
- 满意后通过 /api/promote 一键晋升到生产（prompts/ai_interpreter.md），旧版本自动备份

启动方式：
    cd /Users/jefflau/projects/pdf_report_converter/PDF_converter
    python prompt_lab_app.py
    # 浏览器打开 http://localhost:5555
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
TEST_CASES_DIR = DATA_DIR / "lab_test_cases"
LAB_VERSIONS_DIR = PROMPTS_DIR / "lab_versions"
PROD_VERSIONS_DIR = PROMPTS_DIR / "versions"

# 关键文件
LAB_PROMPT_PATH = PROMPTS_DIR / "ai_interpreter_lab.md"        # 工作副本
PROD_PROMPT_PATH = PROMPTS_DIR / "ai_interpreter.md"           # 生产

# 自动创建目录
LAB_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
PROD_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
TEST_CASES_DIR.mkdir(parents=True, exist_ok=True)

# 如果 lab prompt 不存在，从生产复制一份
if not LAB_PROMPT_PATH.exists() and PROD_PROMPT_PATH.exists():
    LAB_PROMPT_PATH.write_text(PROD_PROMPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")

# ---------------------------------------------------------------------------
# DashScope 配置（复用 extract.py 的默认 key）
# ---------------------------------------------------------------------------
try:
    import extract as _extract  # type: ignore
    DEFAULT_DASHSCOPE_KEY = getattr(_extract, "DEFAULT_DASHSCOPE_KEY", "")
except Exception:
    DEFAULT_DASHSCOPE_KEY = ""

DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY", DEFAULT_DASHSCOPE_KEY).strip()
AI_MODEL = os.environ.get("AI_TEXT_MODEL", "qwen-plus")
ITERATION_MODEL = os.environ.get("AI_ITERATION_MODEL", "qwen-turbo")
AI_TEMPERATURE = float(os.environ.get("AI_TEMPERATURE", "0.5"))
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# ---------------------------------------------------------------------------
# Flask 应用
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=None,
)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.secret_key = os.environ.get("LAB_SECRET_KEY", "prompt-lab-dev-key")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _get_next_version(versions_dir: Path, prefix: str = "ai_interpreter_v") -> int:
    """Scan directory for files like ai_interpreter_v{n}.md and return next n."""
    if not versions_dir.exists():
        return 1
    nums = []
    for f in versions_dir.glob(f"{prefix}*.md"):
        try:
            n = int(f.stem.split("_v")[1])
            nums.append(n)
        except (ValueError, IndexError):
            pass
    return max(nums) + 1 if nums else 1


def _call_dashscope(messages, temperature=None, max_tokens=8192, timeout=120, model=None):
    """Call DashScope chat completion. Returns (reply, tokens, elapsed_ms)."""
    if not DASHSCOPE_KEY:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY（环境变量或 extract.DEFAULT_DASHSCOPE_KEY）")

    effective_model = model or AI_MODEL
    payload = json.dumps({
        "model": effective_model,
        "messages": messages,
        "temperature": temperature if temperature is not None else AI_TEMPERATURE,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        DASHSCOPE_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {DASHSCOPE_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    reply = result["choices"][0]["message"]["content"]
    tokens = result.get("usage", {}).get("total_tokens", 0)
    elapsed_ms = int((time.time() - t0) * 1000)
    return reply, tokens, elapsed_ms


def _build_context_from_report(report_data: dict) -> str:
    """把 report_data.json 转成给 AI 看的紧凑文本上下文。"""
    schema_items = report_data.get("schema_124", [])
    data_text = "\n".join(
        f"{it.get('code','?')} {it.get('label','?')}：{it.get('value', '—')}"
        for it in schema_items if it.get("value")
    )
    student = report_data.get("student", {})
    student_text = (
        f"学生：{student.get('name','—')}，{student.get('gender','—')}，"
        f"{student.get('grade','—')}，生日：{student.get('birthday','—')}，"
        f"测评日期：{student.get('test_date','—')}"
    )
    return f"{student_text}\n\n测评数据：\n{data_text}"


def _compute_diff(old_text: str, new_text: str) -> str:
    """简单的逐行 diff 摘要。"""
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")
    max_compare = min(len(old_lines), len(new_lines))

    first_diff = None
    last_diff = None
    for i in range(max_compare):
        if old_lines[i] != new_lines[i]:
            if first_diff is None:
                first_diff = i
            last_diff = i

    parts = []
    if first_diff is not None:
        start = max(0, first_diff - 2)
        end = min(max_compare, last_diff + 3)
        parts.append(f"改动区域（第 {start+1}-{end} 行附近）：")
        for i in range(start, end):
            if old_lines[i] != new_lines[i]:
                parts.append(f"  - 旧: {old_lines[i][:100]}")
                parts.append(f"  + 新: {new_lines[i][:100]}")
            else:
                parts.append(f"    {old_lines[i][:100]}")
    if len(new_lines) != len(old_lines):
        parts.append(f"\n行数变化：{len(old_lines)} → {len(new_lines)}")
        if len(new_lines) > len(old_lines):
            parts.append("新增行：")
            for i in range(len(old_lines), len(new_lines)):
                parts.append(f"  + {new_lines[i][:100]}")
        else:
            parts.append("删除行：")
            for i in range(len(new_lines), len(old_lines)):
                parts.append(f"  - {old_lines[i][:100]}")

    return "\n".join(parts) if parts else "无明显差异"


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------
@app.route("/")
def lab_home():
    """独立测试台主页。"""
    return render_template("prompt_lab_standalone.html")


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------
@app.route("/api/prompt", methods=["GET"])
def get_prompt():
    """读取 lab prompt（工作副本）。"""
    return jsonify({"ok": True, "prompt": _read_text(LAB_PROMPT_PATH)})


@app.route("/api/prompt/prod", methods=["GET"])
def get_prod_prompt():
    """读取生产 prompt（用于对比/重置）。"""
    return jsonify({"ok": True, "prompt": _read_text(PROD_PROMPT_PATH)})


@app.route("/api/save", methods=["POST"])
def save_prompt():
    """手动保存 lab prompt（textarea 编辑后保存）。"""
    data = request.get_json(force=True)
    text = (data.get("prompt") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Prompt 不能为空"}), 400

    # 先备份当前 lab prompt
    if LAB_PROMPT_PATH.exists():
        v = _get_next_version(LAB_VERSIONS_DIR)
        (LAB_VERSIONS_DIR / f"ai_interpreter_v{v}.md").write_text(
            LAB_PROMPT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )

    LAB_PROMPT_PATH.write_text(text, encoding="utf-8")
    return jsonify({"ok": True, "saved_at": datetime.now().isoformat(timespec="seconds")})


@app.route("/api/test-cases", methods=["GET"])
def list_test_cases():
    """列出所有可用测试数据。"""
    cases = []
    for f in sorted(TEST_CASES_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            student = data.get("student", {})
            cases.append({
                "id": f.stem,
                "name": student.get("name", f.stem),
                "grade": student.get("grade", "—"),
                "items": len(data.get("schema_124", [])),
            })
        except Exception as e:
            cases.append({"id": f.stem, "name": f.stem, "grade": "—", "items": 0, "error": str(e)})
    return jsonify({"ok": True, "cases": cases})


@app.route("/api/run", methods=["POST"])
def run_interpretation():
    """用当前 lab prompt + 选定测试数据 调 DashScope 出解读。"""
    data = request.get_json(force=True)
    user_message = (data.get("message") or "请给出这份 Y4 报告的完整解读").strip()
    test_case_id = (data.get("test_case") or "cici").strip()

    # 1) 读取 lab prompt
    system_prompt = _read_text(LAB_PROMPT_PATH)
    if not system_prompt:
        return jsonify({"ok": False, "error": "Lab prompt 不存在"}), 400

    # 2) 读取测试数据
    test_path = TEST_CASES_DIR / f"{test_case_id}.json"
    if not test_path.exists():
        return jsonify({"ok": False, "error": f"测试数据 {test_case_id} 不存在"}), 400

    try:
        report_data = json.loads(test_path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"ok": False, "error": f"测试数据解析失败: {e}"}), 400

    context = _build_context_from_report(report_data)

    # 3) 构造 messages
    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是学生测评数据：\n" + context},
        {"role": "user", "content": user_message},
    ]

    # 4) 调 DashScope
    try:
        reply, tokens, elapsed_ms = _call_dashscope(messages)
        return jsonify({
            "ok": True,
            "reply": reply,
            "tokens": tokens,
            "time_ms": elapsed_ms,
            "test_case": test_case_id,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500


@app.route("/api/iterate", methods=["POST"])
def iterate_prompt():
    """根据用户反馈让 AI 自动修改 lab prompt。"""
    data = request.get_json(force=True)
    feedback = (data.get("feedback") or "").strip()
    rating = int(data.get("rating", 3))
    last_output = (data.get("last_output") or "").strip()
    test_case_id = (data.get("test_case") or "cici").strip()

    if not feedback:
        return jsonify({"ok": False, "error": "反馈不能为空"}), 400

    # 1) 读取当前 lab prompt
    current_prompt = _read_text(LAB_PROMPT_PATH)
    if not current_prompt:
        return jsonify({"ok": False, "error": "Lab prompt 不存在"}), 400

    # 2) 备份当前 lab prompt
    v = _get_next_version(LAB_VERSIONS_DIR)
    old_version_path = LAB_VERSIONS_DIR / f"ai_interpreter_v{v}.md"
    old_version_path.write_text(current_prompt, encoding="utf-8")

    # 3) 构造 meta-prompt 让 AI 改 prompt
    # 优化：用压缩格式传输，减少 token 消耗
    meta_prompt = f"""你是 prompt 优化专家。根据用户反馈修改 Y4 测评解读的 system prompt。

当前 system prompt（以 --- 分隔）：
---
{current_prompt}
---

用户反馈：
- 评分：{rating}/5
- 意见：{feedback}
- 上次输出摘要：{last_output[:1500]}

修改要求：
1. 仅改需改进部分，保留好的部分
2. 输出完整修改后的 prompt 全文（非 diff、非解释）
3. 保持 Y4 四维框架（心力/精力/学习力/生涯力）为唯一语言体系
4. 保持指标编号引用规范
5. 不加前缀说明或后缀解释
6. 不包裹 markdown 代码块，输出纯文本"""

    messages = [{"role": "user", "content": meta_prompt}]

    try:
        new_prompt, _, _ = _call_dashscope(
            messages, temperature=0.3, max_tokens=4096, timeout=180,
            model=ITERATION_MODEL,
        )
        new_prompt = new_prompt.strip()

        # 去掉可能的 markdown 代码块包裹
        if new_prompt.startswith("```"):
            lines = new_prompt.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            new_prompt = "\n".join(lines).strip()

        # 4) 写入新 lab prompt
        LAB_PROMPT_PATH.write_text(new_prompt, encoding="utf-8")

        # 5) 计算 diff
        diff = _compute_diff(current_prompt, new_prompt)

        return jsonify({
            "ok": True,
            "old_prompt": current_prompt,
            "new_prompt": new_prompt,
            "diff": diff,
            "version": v,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Prompt 迭代失败: {exc}"}), 500


@app.route("/api/reset", methods=["POST"])
def reset_to_prod():
    """把 lab prompt 重置成生产 prompt（放弃当前迭代）。"""
    if not PROD_PROMPT_PATH.exists():
        return jsonify({"ok": False, "error": "生产 prompt 不存在"}), 400

    # 先备份当前 lab prompt
    if LAB_PROMPT_PATH.exists():
        v = _get_next_version(LAB_VERSIONS_DIR)
        (LAB_VERSIONS_DIR / f"ai_interpreter_v{v}.md").write_text(
            LAB_PROMPT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )

    prod_text = PROD_PROMPT_PATH.read_text(encoding="utf-8")
    LAB_PROMPT_PATH.write_text(prod_text, encoding="utf-8")
    return jsonify({"ok": True, "prompt": prod_text})


@app.route("/api/promote", methods=["POST"])
def promote_to_prod():
    """把 lab prompt 晋升为生产 prompt，并备份旧生产版本。"""
    if not LAB_PROMPT_PATH.exists():
        return jsonify({"ok": False, "error": "Lab prompt 不存在"}), 400

    lab_text = LAB_PROMPT_PATH.read_text(encoding="utf-8")
    if not lab_text.strip():
        return jsonify({"ok": False, "error": "Lab prompt 为空"}), 400

    # 备份当前生产 prompt
    old_prod_text = ""
    if PROD_PROMPT_PATH.exists():
        old_prod_text = PROD_PROMPT_PATH.read_text(encoding="utf-8")
        v = _get_next_version(PROD_VERSIONS_DIR)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"ai_interpreter_v{v}_{timestamp}.md"
        (PROD_VERSIONS_DIR / backup_name).write_text(old_prod_text, encoding="utf-8")

    # 写入新生产 prompt
    PROD_PROMPT_PATH.write_text(lab_text, encoding="utf-8")

    return jsonify({
        "ok": True,
        "promoted_at": datetime.now().isoformat(timespec="seconds"),
        "backup_created": old_prod_text != "",
    })


@app.route("/api/upload-test-case", methods=["POST"])
def upload_test_case():
    """上传新的测试数据 JSON 文件。"""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "未提供文件"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.endswith(".json"):
        return jsonify({"ok": False, "error": "只支持 .json 文件"}), 400

    # 用文件名（去扩展名）作为 id，避免覆盖 cici
    case_id = Path(f.filename).stem
    target = TEST_CASES_DIR / f"{case_id}.json"

    try:
        content = f.read().decode("utf-8")
        data = json.loads(content)  # 验证是合法 JSON
        if "schema_124" not in data:
            return jsonify({"ok": False, "error": "JSON 必须包含 schema_124 字段"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"JSON 解析失败: {e}"}), 400

    target.write_text(content, encoding="utf-8")
    student = data.get("student", {})
    return jsonify({
        "ok": True,
        "case_id": case_id,
        "name": student.get("name", case_id),
        "items": len(data.get("schema_124", [])),
    })


@app.route("/api/status", methods=["GET"])
def status():
    """检查配置状态。"""
    return jsonify({
        "ok": True,
        "has_dashscope_key": bool(DASHSCOPE_KEY),
        "model": AI_MODEL,
        "iteration_model": ITERATION_MODEL,
        "temperature": AI_TEMPERATURE,
        "lab_prompt_exists": LAB_PROMPT_PATH.exists(),
        "prod_prompt_exists": PROD_PROMPT_PATH.exists(),
        "test_cases_count": len(list(TEST_CASES_DIR.glob("*.json"))),
        "lab_versions_count": len(list(LAB_VERSIONS_DIR.glob("*.md"))),
    })


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Y4 Prompt Lab — Standalone 测试台")
    print("=" * 60)
    print(f"Lab prompt:     {LAB_PROMPT_PATH}")
    print(f"Prod prompt:    {PROD_PROMPT_PATH}")
    print(f"Test cases dir: {TEST_CASES_DIR}")
    print(f"Lab versions:   {LAB_VERSIONS_DIR}")
    print(f"DashScope key:  {'已配置' if DASHSCOPE_KEY else '❌ 未配置'}")
    print(f"Run model:      {AI_MODEL}")
    print(f"Iter model:     {ITERATION_MODEL} (faster)")
    print("=" * 60)
    print("启动中... 浏览器打开 http://localhost:5555")
    print("按 Ctrl+C 退出")
    print()
    app.run(host="127.0.0.1", port=5555, debug=True, use_reloader=False)
