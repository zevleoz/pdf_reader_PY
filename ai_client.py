"""共享 AI 分析层：DashScope 调用封装 + Y4 解读/E4 协议构建 helper。

从 app.py 原样搬迁（纯移动，逻辑不变）。被 reports / tools / api_v1 蓝图共用。
不得反向导入任何蓝图；genjob 子进程会 import 本模块。
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def urlopen_with_retry(req: urllib.request.Request, timeout: int = 180,
                       max_retries: int = 3):
    """urllib.urlopen 的限流/5xx 重试封装：429 与 5xx 按指数退避重试，其余原样抛出。

    尊重响应头 Retry-After（若有）；否则退避 2s/4s/8s + 0–1s 抖动。
    最终仍失败时抛 HTTPError/URLError，由调用方统一处理。
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_STATUS or attempt >= max_retries:
                raise
            last_exc = exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else None
            except (TypeError, ValueError):
                delay = None
            if delay is None:
                delay = 2 ** (attempt + 1) + random.random()
            print(f"[AI] HTTP {exc.code}，第 {attempt + 1}/{max_retries} 次重试，等待 {delay:.1f}s")
            time.sleep(delay)
        except urllib.error.URLError as exc:
            if attempt >= max_retries:
                raise
            last_exc = exc
            delay = 2 ** (attempt + 1) + random.random()
            print(f"[AI] 网络错误 {exc.reason}，第 {attempt + 1}/{max_retries} 次重试，等待 {delay:.1f}s")
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc

import db as _db
import extract
import evaluation_rules as _eval_rules
from app_utils import BASE_DIR, DATA_DIR


def _report_qualification_payload(report_id: int):
    """从 DB 取某报告的 raw schema_124 → 构建 qualification 视图 + report meta。

    Returns (payload_dict, error_or_None)。payload 含 items/student/summary/mapping_done/
    mapping_total/per_code_eval_options/data_bias_options/report。
    """
    record = _db.get_report_raw(report_id)
    if not record:
        return None, "报告不存在"
    raw = record.get("raw") or {}
    schema_items = [it for it in (raw.get("schema_124") or []) if not _eval_rules.is_hidden_raw(it)]
    student = raw.get("student", {}) or {}
    items, summary, mapping_done, per_code_opts = _build_qualification_view(schema_items)
    payload = {
        "items": items,
        "student": student,
        "summary": summary,
        "mapping_done": mapping_done,
        "mapping_total": len(items),
        "data_bias_options": _eval_rules.DATA_BIAS_OPTIONS,
        "per_code_eval_options": per_code_opts,
        "report": {
            "id": report_id,
            "report_date": record.get("report_date"),
            "student_name": record.get("student_name"),
            "interpretation": record.get("interpretation") or "",
        },
    }
    return payload, None
def _generate_e4_protocol_core(items: List[Dict[str, Any]], include_raw: bool,
                                interpretation: str, student: Dict[str, Any],
                                student_name: str) -> Dict[str, Any]:
    """E4 协议生成核心逻辑（step1 数据整编 + step2 跨维度分析 + step3 总览成文）。

    与数据来源解耦：调用方传入 items / interpretation / student / student_name。
    返回与原 /api/reports/<id>/e4-protocol 完全一致的 result dict。
    """
    # Step1：数据整编（纯 Python）
    vgroups, other_items, _dims_by_code = _eval_rules.evaluate_question_verdicts(items)
    groups_payload: List[Dict[str, Any]] = []
    group_counts: Dict[str, int] = {d: 0 for d in _eval_rules.E4_DIMS}
    for g in vgroups:
        lines = [_format_e4_line(it, include_raw) for it in g["items"]]
        groups_payload.append({"dim": g["dim"], "q": g["q"], "lines": lines, "verdict": g.get("verdict")})
        group_counts[g["dim"]] += len(g["items"])
    other_lines = [_format_e4_line(it, include_raw) for it in other_items]
    list_placement = _determine_list_placement(items)

    # Step2：跨维度分析（AI）
    model2 = os.environ.get("E4_STEP2_MODEL", "qwen-turbo")
    timeout = int(os.environ.get("E4_STEP_TIMEOUT", "180"))
    all_lines: List[str] = []
    current_dim = None
    for g in groups_payload:
        dim = g.get("dim", "")
        if dim != current_dim:
            all_lines.append("")
            all_lines.append(f"## {_eval_rules.E4_LABELS.get(dim, dim)}")
            current_dim = dim
        q = g.get("q")
        if q:
            all_lines.append(f"问题：{q}")
        v = g.get("verdict")
        if v:
            cn = _eval_rules.verdict_label_cn(v.get("state"), v.get("items") or [])
            la = v.get("list_assignment") or ""
            la_seg = f" | 名单: {la}" if la else ""
            all_lines.append(f"问题判定（Python 规则，须以此为准绳）：{cn}{la_seg} | {v.get('summary', '')}")
        all_lines.extend(g.get("lines") or [])
        all_lines.append("")
    if other_lines:
        all_lines.append("## OTHER_VARIABLES（框架未引用）")
        all_lines.extend(other_lines)
        all_lines.append("")

    analyses: Dict[str, str] = {d: "" for d in _eval_rules.E4_DIMS}
    full_analysis = ""
    stats2: List[Dict[str, Any]] = []
    if any(g.get("lines") for g in groups_payload):
        system2 = _e4_step2_system()
        user2 = ("【E4 框架数据（按维度和评估问题组织；问题下列出该问题涉及的指标数据）】\n"
                 + "\n".join(all_lines))
        try:
            r2 = _dashscope_chat(
                [{"role": "system", "content": system2},
                 {"role": "user", "content": user2}],
                model=model2, timeout=timeout, max_tokens=4000)
            full_analysis = _sanitize_e4_step2(r2["content"])
            analyses["_cross"] = _e4_step2_tail(full_analysis)
            stats2 = [{"dim": "ALL", "tokens": r2["tokens"], "time_ms": r2["time_ms"], "model": model2}]
        except Exception as exc:
            stats2 = [{"dim": "ALL", "tokens": 0, "time_ms": 0, "model": model2, "error": str(exc)}]
            full_analysis = f"（Step2 跨维度分析失败：{exc}）"

    # Step3：总览成文（AI；名单归属以 Python 规则为准，AI 不得改判）
    model3 = os.environ.get("E4_STEP3_MODEL", "qwen-plus")
    system3 = _e4_step3_system(list_placement.get("category")
                               or list_placement.get("placement") or "（未判定）")
    user3 = (f"【综合分析草稿】\n{full_analysis or analyses}\n\n"
             f"【Y4 原始 AI 解读（可选参考，非客观事实）】\n{interpretation or '（无）'}")
    try:
        r3 = _dashscope_chat(
            [{"role": "system", "content": system3},
             {"role": "user", "content": user3}],
            model=model3, timeout=timeout, max_tokens=2500)
        overview_md = r3["content"]
        stats3 = {"tokens": r3["tokens"], "time_ms": r3["time_ms"], "model": model3}
    except Exception as exc:
        overview_md = f"（总览生成失败：{exc}）"
        stats3 = {"tokens": 0, "time_ms": 0, "model": model3, "error": str(exc)}

    content_md = _assemble_e4_protocol(items, include_raw, analyses, overview_md,
                                      full_analysis, interpretation,
                                      student=student, student_name=student_name)
    return {
        "ok": True,
        "content_md": content_md,
        "stats": {"step2": stats2, "step3": stats3},
        "student_name": student_name,
        "list_placement": list_placement,
        "step1": {
            "groups": groups_payload,
            "other_lines": other_lines,
            "group_counts": group_counts,
            "unmapped_count": len(other_lines),
        },
    }


# ---------------------------------------------------------------------------
# 有效评价 (Y4 Evaluation) Markdown 下载
# ---------------------------------------------------------------------------
def _generate_interpretation_for_report(report_id: int):
    """即时为某报告生成 AI 解读并落库。加法式 helper，不修改既有 /interpret 路由。

    Returns: (reply_text, error_or_None)
    """
    import urllib.request as _ureq

    record = _db.get_report_raw(report_id)
    if not record:
        return None, "报告不存在"

    raw = record.get("raw") or {}
    schema_items = raw.get("schema_124", [])
    student = raw.get("student", {})
    context = _build_y4_interpret_context(schema_items, student)

    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是 Y4 有效评价数据：\n" + context},
        {"role": "user", "content": "请给出这份 Y4 报告的完整解读"},
    ]

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": messages,
        "temperature": float(os.environ.get("AI_TEMPERATURE", "0.3")),
        "max_tokens": 8192,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen_with_retry(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        reply = _finalize_y4_interpretation(
            result["choices"][0]["message"]["content"], dashscope_key)
        try:
            _db.save_interpretation(report_id, reply)
        except Exception as e:
            print(f"[DB] 解读结果保存失败 (非致命): {e}")
        return reply, None
    except Exception as exc:
        return None, f"AI 调用失败: {exc}"
def _build_qualification_view(schema_items: List[Dict[str, Any]]):
    """从 schema_124 构建 qualification 视图。

    返回 (items, summary, mapping_done, per_code_opts)。items 已附 e4_dims/e4_dim/e4_sub
    并按 Y4 维度排序。与数据来源解耦，供 prompt-lab（report_data.json）和按 report_id
    的生产接口（DB raw）共用。
    """
    items, summary = _eval_rules.build_evaluation_view(schema_items)
    # 附加用户指认的 E4 分类（无推断，未指认为空列表）
    mapping = _db.get_e4_mapping()
    for it in items:
        e4_maps = _eval_rules.e4_classify(it, mapping)
        it["e4_dims"] = e4_maps  # [{e4_dim, e4_sub}, ...]
        # 兼容前端：e4_dim/e4_sub 取第一个（用于 Y4 视图标注）
        it["e4_dim"] = e4_maps[0]["e4_dim"] if e4_maps else None
        it["e4_sub"] = e4_maps[0]["e4_sub"] if e4_maps else ""
    # 按维度分组排序
    items.sort(key=lambda it: (_eval_rules._DIM_ORDER.index(it["dimension"])
                               if it["dimension"] in _eval_rules._DIM_ORDER else 99,
                               _eval_rules.sort_key_code(it["code"])[0],
                               it["code"]))
    mapping_done = sum(1 for it in items if it["e4_dims"])
    # 构建 per-code eval_options（每个数据点有自己的档位体系）
    per_code_opts = {}
    for it in items:
        opts = _eval_rules.eval_options_for(it.get("code", ""), it.get("label", ""))
        per_code_opts[it.get("code", "")] = opts
    return items, summary, mapping_done, per_code_opts
def _y4_item_unit(it: Dict[str, Any]) -> str:
    """取指标单位；unit 为空时从 note 括号提取（如 note='睡眠时长（小时/天）'）。"""
    unit = (it.get("unit") or "").strip()
    if unit:
        return unit
    note = (it.get("note") or "").strip()
    m = re.search(r"[（(]([^)）]+)[)）]", note)
    return m.group(1).strip() if m else ""


def _y4_is_empty(it: Dict[str, Any]) -> bool:
    """无 raw、无档位、无评级、排序项也无值 → 数据缺失，Y4 输出中剔除。"""
    src = it.get("eval_source") or ""
    if src == "原始排序":
        return not (it.get("eval_value") or it.get("raw_value"))
    return not str(it.get("raw_value") or "").strip() \
        and not (it.get("eval_value") or "").strip() \
        and not (it.get("pdf_grade") or "").strip()


def _strip_wrapping_fence(text: str) -> str:
    """剥离模型偶发包裹全文的 ```markdown ... ``` 代码围栏。"""
    t = (text or "").strip()
    m = re.fullmatch(r"```(?:[a-zA-Z]*)?\s*\n(.*?)\n?```", t, re.S)
    return (m.group(1).strip() if m else t)


# 解读稿里反复出现的自造比喻/概括词与越界医学词（硬禁）
_Y4_BANNED_TOKENS = ("锚点", "燃料", "缓冲带", "闭环", "回路", "引擎", "马达",
                     "稳压器", "冻结层", "观察者姿态", "高承载", "低滋养", "低负荷",
                     "支点", "撬动", "淤堵", "血流", "神经可塑性", "临床", "确诊",
                     "崩塌", "失控", "硬件", "代偿")
# 建议节里编造的量化安排（含「每天/每周」频率与「1 句话、3 步」类数量）
_Y4_FAB_NUM_RE = re.compile(r"\d+\s*(分钟|次|道|个|句|步|项|条|页)|每\s*[周天日]")
_Y4_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 自造对仗标签（高 X、低 Y）与装饰箭头
_Y4_BANNED_PATTERNS = [re.compile(p) for p in
                       (r"高[\u4e00-\u9fff]{1,6}[、，]\s*[低弱]", r"→|✅|✓|✗")]
_Y4_LEN_HARD = 1650  # 汉字数硬线（目标 1000–1500，留返修余量）
# 行首孤立的中文标点（返修偶发把句号挤到下一行）
_Y4_STRAY_PUNC_RE = re.compile(r"[ \t]*\r?\n[ \t]*(?=[。，、；！？）」])")


def _y4_needs_refine(text: str) -> bool:
    if len(_Y4_CJK_RE.findall(text or "")) > _Y4_LEN_HARD:
        return True
    if any(tok in (text or "") for tok in _Y4_BANNED_TOKENS):
        return True
    if any(p.search(text or "") for p in _Y4_BANNED_PATTERNS):
        return True
    tail = text.split("杠杆点与建议", 1)[1] if "杠杆点与建议" in text else ""
    return bool(_Y4_FAB_NUM_RE.search(tail))


def _y4_refine_once(text: str, dashscope_key: str) -> str:
    """对不合规解读做一次定稿返修。只允许删减和就地改写，严禁新增任何内容。"""
    import urllib.request as _ureq
    sysmsg = (
        "你在给一份 Y4 测评解读做定稿修改。只能删减和就地改写，严禁新增任何原文没有的东西"
        "（新事实、新数字、新职业名、新机制解释、新预测都不许加）。按下列要求修改：\n"
        "1. 汉字数压到 1500 以内：删掉重复修饰、合并近义句、压缩排比；"
        "具体指标名称、原始数值、每条建议的动作必须保留。\n"
        "2. 删除对仗式自造标签（形如「高接收、低整合」「高 X、低 Y」的短语）和比喻机制词"
        "（锚点、支点、燃料、缓冲带、闭环、回路、引擎、硬件、代偿、撬动、淤堵等），"
        "就地改成用指标名称的直白陈述。\n"
        "3. 删除医学或临床表述（临床、确诊、神经可塑性、血流、排除某疾病等）"
        "和「崩塌、失控」类极端预测；要表达相关意思用日常语言，如「持续下去容易更疲惫」。\n"
        "4. 「杠杆点与建议」一节删掉编造的数量与频率安排（每天、每周、多少分钟、几次、几道、几句、几步等），"
        "步骤说明不要用箭头符号（→），改用文字连接；只留动作和方向。\n"
        "5. 保持七个章节标题原样：## 总体印象 / ## 心力（情绪与动力系统） / "
        "## 精力（精力管理与身体健康系统） / ## 学习力（学习系统） / "
        "## 生涯力（专业与职业发展系统） / ## 跨维度连结 / ## 杠杆点与建议。\n"
        "直接返回改后的完整 Markdown，不加代码块、不加解释、不加字数标注。"
    )
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": os.environ.get("AI_TEXT_MODEL", "qwen-plus"),
        "messages": [{"role": "system", "content": sysmsg},
                     {"role": "user", "content": text}],
        "temperature": 0.2,
        "max_tokens": 6000,
    }).encode("utf-8")
    req = _ureq.Request(url, data=payload,
                        headers={"Authorization": f"Bearer {dashscope_key}",
                                 "Content-Type": "application/json"}, method="POST")
    with urlopen_with_retry(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return _strip_wrapping_fence(result["choices"][0]["message"]["content"])


def _y4_scrub_numbers(text: str) -> str:
    """建议节仍残留编造数量时的最后兜底：精确数量改成非特指（15 分钟→几分钟），频率词删除。"""
    if "杠杆点与建议" not in text:
        return text
    head, tail = text.split("杠杆点与建议", 1)

    def _vague(m: "re.Match") -> str:
        unit = m.group(1)
        return f"几{unit}" if unit else ""

    tail = _Y4_FAB_NUM_RE.sub(_vague, tail)
    return head + "杠杆点与建议" + tail


def _finalize_y4_interpretation(reply: str, dashscope_key: str) -> str:
    """落库前定稿：去围栏；不合规时返修（最多两轮，禁止越改越长），再兜底清洗数字与标点。"""
    reply = _strip_wrapping_fence(reply)
    for _ in range(2):
        if not _y4_needs_refine(reply):
            break
        try:
            refined = _y4_refine_once(reply, dashscope_key)
            if refined and len(_Y4_CJK_RE.findall(refined)) <= len(_Y4_CJK_RE.findall(reply)) + 100:
                reply = refined
            else:
                break
        except Exception:
            break
    tail = reply.split("杠杆点与建议", 1)[-1]
    if _Y4_FAB_NUM_RE.search(tail):
        reply = _y4_scrub_numbers(reply)
    reply = _Y4_STRAY_PUNC_RE.sub("", reply)
    return reply


def _build_y4_interpret_context(schema_items: Optional[List[Dict[str, Any]]] = None,
                                student: Optional[Dict[str, Any]] = None,
                                items_override: Optional[List[Dict[str, Any]]] = None) -> str:
    """构建喂给 Y4 解读 AI 的输入文本：学生背景 + 按 Y4 四维分组的已确认有效评价。

    items_override 为前端传回的调整后 items（含 bias/adjusted）；否则从原始 schema
    经规则引擎构建。evaluate_question_verdicts 的副作用（认知 trait 标注、体质评级
    回写）幂等执行。输出只用 Y4 四维语言，不含任何 E4 字样。
    """
    student = student or {}
    if items_override:
        items = items_override
        try:
            _eval_rules.evaluate_question_verdicts(items)
        except Exception:
            pass
    else:
        items, _ = _eval_rules.build_evaluation_view(schema_items or [])
        _eval_rules.evaluate_question_verdicts(items)
    items = [it for it in items if not _y4_is_empty(it)]

    bg_parts = [f"学生：{student.get('name', '—')}，{student.get('gender', '—')}，"
                f"{student.get('grade', '—')}"]
    if student.get("school"):
        bg_parts[0] += f"，{student['school']}"
    if student.get("birthday"):
        bg_parts[0] += f"（出生 {student['birthday']}）"
    if student.get("test_date"):
        bg_parts[0] += f" | 测评日期：{student['test_date']}"

    buckets: Dict[str, list] = {d: [] for d in _eval_rules._DIM_ORDER}
    norm_lines: List[str] = []
    for it in items:
        dim = it.get("dimension") or _eval_rules.dimension_of(it)
        buckets.setdefault(dim, []).append(it)

    lines = bg_parts + ["", "【已确认的有效评价数据，括号内档位/评级即结论，直接作为事实使用】"]
    for dim in _eval_rules._DIM_ORDER:
        dim_items = sorted(buckets.get(dim, []),
                           key=lambda x: _eval_rules.sort_key_code(x.get("code", "")))
        if not dim_items:
            continue
        lines.append("")
        lines.append(f"〔{dim}〕")
        for it in dim_items:
            label = it.get("label", "?")
            raw_v = it.get("raw_value", "")
            eval_v = it.get("eval_value") or ""
            src = it.get("eval_source", "待判定") or "待判定"
            unit = _y4_item_unit(it)
            bias = (it.get("data_bias") or "正常").strip()

            if src == "参照值":
                norm_lines.append(f"{label}：{raw_v}{unit}".rstrip())
                continue
            if src == "原始排序":
                lines.append(f"{label}：{eval_v}")
                continue

            # 饮食得分 0 不展示（真实数据是描述段落）
            if "饮食" in label and "得分" in label and str(raw_v).strip() in ("0", ""):
                raw_v = ""
            seg = label + "："
            if raw_v not in ("", None):
                seg += f"{raw_v}{(' ' + unit) if unit else ''}"
            # 评级（体质习惯）优先；否则档位
            grade = (it.get("pdf_grade") or "").strip()
            if grade:
                seg += f"（评级：{grade}）"
            elif eval_v and str(eval_v).strip() != str(raw_v).strip():
                seg += f"（{eval_v}）"
            # 认知个体内 trait 标注
            trait = (it.get("trait_label") or "").strip()
            if trait:
                tn = (it.get("trait_note") or "").strip()
                seg += f"〔{trait}（{tn}）〕" if tn else f"〔{trait}〕"
            # bias 是独立标注，不改有效评价档位；高估=实测高于真实，低估=实测低于真实
            if bias and bias != "正常":
                seg += f"〔专家确认：{bias}〕"
            # OBSERVATION：测评状态可能失真（用 Y4 语言，不引 E4 术语）
            if (it.get("problem_status") or "CONFIRMED") == "OBSERVATION":
                seg += "〔测评状态可能失真，先观望〕"
            lines.append(seg)

    if norm_lines:
        lines += ["", "〔常模参照〕（对照标准，不是该生数据）"] + norm_lines
    return "\n".join(lines)


def _y4_report_line(it: Dict[str, Any]) -> str:
    """人类可读 Y4 报告中的单个指标行（markdown 列表项，不含机器标签）。"""
    label = it.get("label", "?")
    raw_v = it.get("raw_value", "")
    eval_v = it.get("eval_value") or ""
    src = it.get("eval_source", "待判定") or "待判定"
    unit = _y4_item_unit(it)
    bias = (it.get("data_bias") or "正常").strip()

    if src == "原始排序":
        return f"- **{label}**：{eval_v}"

    # 饮食得分无数值时不展示（真实数据是描述段落）
    if "饮食" in label and "得分" in label and str(raw_v).strip() in ("0", ""):
        return ""

    seg = f"- **{label}**："
    if raw_v not in ("", None):
        seg += f"{raw_v}{(' ' + unit) if unit else ''}"
    grade = (it.get("pdf_grade") or "").strip()
    if grade:
        seg += f"（评级：{grade}）"
    elif eval_v and str(eval_v).strip() != str(raw_v).strip():
        seg += f"（{eval_v}）"
    trait = (it.get("trait_label") or "").strip()
    if trait:
        tn = (it.get("trait_note") or "").strip()
        seg += f"〔{trait}（{tn}）〕" if tn else f"〔{trait}〕"
    if bias and bias != "正常":
        seg += f"〔专家确认：{bias}〕"
    if (it.get("problem_status") or "CONFIRMED") == "OBSERVATION":
        seg += "〔测评状态可能失真，先观望〕"
    if it.get("adjusted") and it.get("original_eval"):
        seg += f"（专家调整自：{it['original_eval']}）"
    return seg


def _build_phase1_md_text(items: List[Dict[str, Any]], include_raw: bool,
                          interpretation: str, student: Dict[str, Any],
                          student_name: str = "", now: str = "") -> str:
    """拼装人类可读 Y4 报告 Markdown（内部数据版，与 Y4 JSON 同一 items 数据源）。

    纯 Y4 内容：学生信息 + 四维已确认数据 + AI 解读原文；无机器标签、无 E4 字样。
    """
    from datetime import datetime as _dt
    if not student_name:
        student_name = student.get("name") or "测试"
    if not now:
        now = _dt.now().strftime("%Y-%m-%d %H:%M")

    # 幂等副作用：认知 trait 标注、体质评级回写
    try:
        _eval_rules.evaluate_question_verdicts(items)
    except Exception:
        pass
    items = [it for it in items if not _y4_is_empty(it)]

    md: List[str] = [f"# Y4 综合测评报告 · {student_name}", ""]
    info_rows = [("性别", student.get("gender")), ("年级", student.get("grade")),
                 ("学校", student.get("school")), ("出生日期", student.get("birthday")),
                 ("测评日期", student.get("test_date"))]
    info_rows = [(k, v) for k, v in info_rows if v]
    if info_rows:
        md.append("| 项目 | 信息 |")
        md.append("| --- | --- |")
        for k, v in info_rows:
            md.append(f"| {k} | {v} |")
        md.append("")

    md.append("## 测评数据")
    md.append("")
    buckets: Dict[str, list] = {d: [] for d in _eval_rules._DIM_ORDER}
    norm_lines: List[str] = []
    for it in items:
        if it.get("eval_source") == "参照值":
            unit = _y4_item_unit(it)
            norm_lines.append(
                f"- **{it.get('label','?')}**：{it.get('raw_value','')}{unit}".rstrip())
            continue
        dim = it.get("dimension") or _eval_rules.dimension_of(it)
        if dim not in buckets:
            dim = "学习力"
        buckets[dim].append(it)

    for dim in _eval_rules._DIM_ORDER:
        dim_items = sorted(buckets[dim], key=lambda it: _eval_rules.sort_key_code(it.get("code", "")))
        if not dim_items:
            continue
        md.append(f"### {_eval_rules._DIM_LABELS[dim]}")
        md.append("")
        for it in dim_items:
            line = _y4_report_line(it)
            if line:
                md.append(line)
        md.append("")

    if norm_lines:
        md.append("### 常模参照（对照标准，非该生数据）")
        md.append("")
        md.extend(norm_lines)
        md.append("")

    md.append("## AI 解读")
    md.append("")
    if interpretation and interpretation.strip():
        # 嵌入时整体降一级（## → ###），使其成为「AI 解读」子节
        demoted = re.sub(r"(?m)^(#{1,5}) ", r"#\1 ", interpretation.strip())
        md.append(demoted)
    else:
        md.append("（未提供）")
    md.append("")
    md.append("---")
    md.append(f"凭远教育 · Y4 综合测评系统 | 生成时间：{now}")
    return "\n".join(md)


def _format_e4_line(it: Dict[str, Any], include_raw: bool, is_ref: bool = False) -> str:
    """格式化 E4 输出中的单行。

    精简版：无 code 前缀，默认值不显示，人机双友好。
    is_ref=True 时只输出引用行（多维度映射的第二次出现）。
    """
    label = it.get("label", "?")

    if is_ref:
        return f"[REF] {label} → 见首次出现维度"

    raw_v = it.get("raw_value", "")
    eval_v = it.get("eval_value") or ""
    unit = it.get("unit", "") or ""
    src = it.get("eval_source", "待判定") or "待判定"
    adjusted = it.get("adjusted", False)
    original = it.get("original_eval", "")
    note = (it.get("note") or "").strip()
    bias = it.get("data_bias", "正常") or "正常"
    problem = it.get("problem_status", "CONFIRMED") or "CONFIRMED"

    # 体质健康类：从 note 提取单位（如 note="睡眠时长（小时/天）" → unit="小时/天"）
    note_used_for_unit = False
    if not unit and note:
        m_unit = re.search(r"[（(]([^)）]+)[)）]", note)
        if m_unit:
            unit = m_unit.group(1).strip()
            note_used_for_unit = True

    # 饮食无数值时不展示 0（真实数据是描述段落，见 OTHER_VARIABLES）
    is_diet_score = "饮食" in label and "得分" in label
    if is_diet_score and (not raw_v or str(raw_v).strip() in ("0", "")):
        raw_v = ""

    if src == "参照值":
        return f"[NORM] {label} | {raw_v}{unit}"

    if src == "原始排序":
        parts = [f"[ORDER] {label}", eval_v]
        if bias != "正常":
            parts.append(f"bias:{bias}")
        if problem == "OBSERVATION":
            parts.append("problem:OBSERVATION")
        return " | ".join(parts)

    parts = [f"[EVAL] {label}"]
    if include_raw and raw_v:
        parts.append(f"{raw_v}{unit}")
    # raw 与档位同值时（如思维模式结果 78.4|78.4）不重复显示
    if eval_v and str(eval_v).strip() != str(raw_v).strip():
        parts.append(eval_v)
    # 认知分项个体内强/弱特质标注（相对认知总百分位）
    trait = (it.get("trait_label") or "").strip()
    if trait:
        tn = (it.get("trait_note") or "").strip()
        parts.append(f"{trait}（{tn}）" if tn else trait)
    # 体质习惯行：显示 PDF 评级
    pdf_grade = (it.get("pdf_grade") or "").strip()
    if pdf_grade:
        parts.append(f"评级:{pdf_grade}")
    if bias != "正常":
        parts.append(f"bias:{bias}")
    if problem == "OBSERVATION":
        parts.append("problem:OBSERVATION")
    if adjusted and original:
        parts.append(f"adjusted:{original}→{eval_v}")
    if note and not note_used_for_unit:
        parts.append(f"note:{note}")
    return " | ".join(parts)


def _mapping_for(code, mapping: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """按 code 查映射（可多维度），兼容 "015" / "15" 两种形态。返回 [{e4_dim, e4_sub}, ...]。"""
    code = str(code)
    if code in mapping:
        return mapping[code]
    digits = "".join(ch for ch in code if ch.isdigit())
    return mapping.get(str(int(digits)), []) if digits else []


def _build_mapping_snapshot_md(mapping: Dict[str, List[Dict[str, str]]],
                               items: List[Dict[str, Any]]) -> str:
    """生成 MAPPING_SNAPSHOT：人工指认的 code → E4 维度/子类（Y4 原名，可多维度）。"""
    lines: List[str] = []
    for d in _eval_rules.E4_DIMS:
        lines.append(_eval_rules.E4_LABELS[d])
        rows = []
        for it in items:
            maps = _mapping_for(it.get("code", ""), mapping)
            dim_maps = [m for m in maps if m.get("e4_dim") == d]
            if dim_maps:
                sub = dim_maps[0].get("e4_sub", "") or "（未指定子类别）"
                rows.append(f"  {it.get('code','')} {it.get('label','')} → {sub}")
        lines.extend(sorted(rows) if rows else ["  （未指认任何指标）"])
        lines.append("")
    # 列出跨维度映射的指标
    multi = []
    for it in items:
        maps = _mapping_for(it.get("code", ""), mapping)
        if len(maps) > 1:
            dims_str = " + ".join(m.get("e4_dim", "") for m in maps)
            multi.append(f"  {it.get('code','')} {it.get('label','')} → {dims_str}")
    if multi:
        lines.append("【跨维度映射指标】")
        lines.extend(multi)
        lines.append("")
    return "\n".join(lines)


# ── E4 三步 AI 工作流 ─────────────────────────────────────────

_E4_NAMING_RULE = ("NAMING_RULE（硬约束）: Y4 报告的 label（指标名称）是唯一权威命名。"
                   "引用任何指标必须使用该原始名称，禁止改写、缩写、翻译或创造新术语。"
                   "E4 维度/子类仅为人工指认的分组标签，不是数据名称。")


def _dashscope_chat(messages: List[Dict[str, str]], model: str,
                    timeout: int = 180, max_tokens: int = 3000,
                    temperature: float = 0.4) -> Dict[str, Any]:
    """调用 DashScope chat completions。返回 {content, tokens, time_ms}，失败抛异常。"""
    import urllib.request as _ureq
    import time as _time

    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = _ureq.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    t0 = _time.time()
    with urlopen_with_retry(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return {
        "content": result["choices"][0]["message"]["content"],
        "tokens": result.get("usage", {}).get("total_tokens", 0),
        "time_ms": int((_time.time() - t0) * 1000),
    }


def _e4_judgment_guides_block() -> str:
    """把 E4_JUDGMENT_GUIDES 按框架维度顺序渲染成 prompt 块。

    #### 标题同时是输出契约：AI 必须逐字使用这些标题，后端靠它把判断归位到数据行下。
    """
    guides = _eval_rules.E4_JUDGMENT_GUIDES
    lines: List[str] = []
    for dim_def in _eval_rules.E4_FRAMEWORK:
        dim = dim_def["dim"]
        lines.append(f"## {_eval_rules.E4_LABELS.get(dim, dim)}")
        for g in dim_def["groups"]:
            q = g.get("q")
            if q is None:
                key, title = "E2_ENERGY", "E2 · Energy（精力管理）"
            else:
                key, title = q, q
            guide = guides.get(key, "")
            if guide:
                lines.append(f"#### {title}")
                lines.append(guide)
        lines.append("")
    return "\n".join(lines).strip()


def _e4_step2_system() -> str:
    """Step2 system prompt：基于 E4 框架问题的 contextual 分析。

    数据按「维度→评估问题→指标」组织。AI 按【逐问题写作模板】逐一回答框架问题（输出的 #### 标题
    必须与模板锚点逐字一致，后端据此把判断拼到对应数据行下方），再做三段式综合
    （核心问题/可能失真·先观察/跟进线索与切入点）。
    """
    return f"""你是 Y4 测评 E4 评估框架的分析员。E4 框架是工作草稿工具，用于识别学生薄弱点与低垂果实（low-hanging fruits），非最终评估结论。

【数据结构】
数据按 E1（情绪）、E2（精力）、E3（引擎）、E4（参与投入）四个维度组织。
每个维度下有若干「评估问题」（以"问题："开头），问题下列出回答该问题所需的指标数据。
每个问题下还有一行「问题判定（Python 规则）」——规则引擎基于已确认阈值算出的问题级结论
（需介入/需支持/关注/观察/健康/中性）。这些判定行和数据行是给你看的输入，**严禁抄写进你的输出**
（后端会自动清洗回显行）。你的回答须与判定方向一致：可补充细节、证据和跨问题连结，
但不得推翻判定。

【你的任务】
1. 逐一回答评估问题：基于该问题下的指标数据，给出有信息量的判断。回答要直接回应问题本身。
2. 判断深度按问题判定分级，具体标准见下方【判断深度】。
3. 逐问题判断完成后，按下方三段式做综合：先找核心问题，再甄别可能失真的数据，最后给跟进线索与切入点。

【判断深度（权威标准，全文以此为准）】
- 健康/中性：2-4 句。先给结论，再用一句说明哪些指标互相印证（如两层指标方向一致），不展开、不写数值。
- 关注：4-6 句。包含：判断结论；qualification（在什么条件下成立，或为什么档位标签不代表严重问题）；题内指标之间的关系；这对该生的实际含义。
- 需支持/需介入：5-8 句。按数据情况自然组织（不要机械列点），覆盖以下四要素：
  ① 判断结论——问题是什么、性质如何；
  ② 证据链——题内哪些指标共同支持，方向是否一致，有无反向证据；
  ③ 上下文含义——放在该生其他指标的背景下意味着什么，在学习中实际可能表现为什么；
  ④ 边界与把握度——什么信息会改变这个判断（仅在确实不确定时写；bias 已标注的视为确认事实，不写待确认）。

【去重硬规则（与术语规则同级，违反即重写）】
1. 禁止回显输入：输出中不得出现「问题判定」字样的行、不得出现任何 [EVAL]/[ORDER]/[NORM]/[REF] 开头的数据行、不得照抄数据清单。读者已在数据区看到全部数值，你的任务是给判断，不是搬运数据。
2. 每个问题的判断独立成段并独立满足【判断深度】的长度要求，不因指标在其他问题出现过而豁免。
3. 同一指标全文只完整解释一次：首次出现的问题给完整分析；之后的问题禁止重复已做过的解释，但必须补上该题视角下的新分析层——这个指标在当前问题里扮演什么角色、与本题其他指标构成什么关系，不得只写一句引用。
4. 防注水：判断中的每一句都必须承载该生特有的信息。禁止教科书式通用解释（如"工作记忆对学习很重要"）、禁止填充句、禁止把一句话能说清的拆成多句。长度服从信息量。
5. 末尾三个综合段是「索引与行动」，不是逐问题段落的缩写。

【思考方式】
你不是在填表，你是在做判断。对每个学生，分析的详略应该不同。
不要对每个数据点都写"可能影响XXX"——只写有信息量的关联。
看完后读者应该清楚：这个学生的问题在哪、哪些先观察、先做什么。

【硬规则】
1. {_E4_NAMING_RULE}
2. 只使用 Y4/E4 已有词汇，禁止创造新术语、新标签、新分类。具体禁止：心理学/治疗术语（如"情绪耗竭"、"负向耦合"、"恶性循环"）、连字符组合造词、为模式取新名字。正确方式：用指标名称直接描述状态和关联，如"情绪稳定性总分低与人格-外倾性得分低同时出现，可能相互影响"。
3. bias 是独立标注，不改有效评价档位。数据行中有效评价是测评结果（ground truth），bias（高估/低估）是专家对该测评值的方向性判断，与档位独立存在。高估=实测高于真实水平（真实更差）；低估=实测低于真实水平（真实更好）。你须同时参考档位和 bias 来调整判断方向，但不改写档位本身。
4. problem:OBSERVATION：假问题（测评状态失真），观望处理，不可直接当结论。
5. 所有结论须标注依据指标名称；数据行中不存在的结论不得编造。
6. 同一指标可能出现在多个问题/维度中，不要重复已做过的解释；但每个问题仍须按【判断深度】独立写足，从该题视角补充新分析。
7. 排序位置类数据（如"安全稳定排序位置 第10位/共15"）：位置数字越小排序越靠前（越重要）。
8. 体质健康习惯行的「得分」与「评级」并存时以评级为准：如「饮食习惯得分 0 | 评级:优」表示营养认知题答错但饮食行为健康，不是饮食问题，禁止据此建议干预饮食。
9. 认知百分位行上的「强特质/相对弱特质」标注是该生与自身认知能力总百分位的个体内比较，不是常模判定，只作识别参考；两者错位才产生判断（如感知觉强特质+注意力相对弱特质=潜在分心/粗心组合）。

【跟进线索映射】
数据命中对应特征时采用以下线索，没有命中不得生搬；允许点名凭远内部工具：
- 学习方法与策略-学习自我调节偏低 → 了解学生对各科老师的看法（尤其自己不喜欢的老师及沟通方式），可与三级象限图中学科投入的位置交叉验证。
- 依恋关系-亲近偏低（尤其母亲）→ 与测评解读师确认做测评解读时是否提及过该点。
- E2 睡眠/饮食/运动 → 向 Gary/Jeff 核实并更新数据（得分与评级冲突时以评级为准）；运动关注具体项目类型，可对照三级象限图中的运动类投入记录。
- 渴望成功动机成立（职业价值观·成就感排序前五）→ 访谈「过去一年学习中有成就感的时刻」，学习动机从成就感来源切入，鼓励家庭一起在学习过程中积累成就感，数据化记录是重要方式。
- 分心组合（高感知觉+相对弱注意力）→ 关注电子产品使用与做作业时的环境管理。
- 确定性需求问题判定为「有确定性需求」+ 计划性不足 + 学习策略使用少 → 用「一表人才」（结构化计划表/学习机制工具）帮学生搭建结构化学习过程，并在过程中逐步养成习惯。
- 执行功能弱项（如工作记忆、认知灵活性）若为施测末段题目 → 点明可能受疲劳影响；若该数据点带 bias 标注，按 bias 方向调整你的判断。
- 原始分优先原则：档位是分类标签，原始分才是实情。判断时先看原始分在量表里的实际位置，不要机械地按档位下结论。典型情况：原始分接近满分（如 9.5/10）虽落在「需关注」档，从人的视角看实际接近天花板，不应当严重关注；反之原始分在档位边界附近时要谨慎，不要因刚好踩线就当问题展开。
- 访谈/确认建议：只在需介入或结论不确定时才建议访谈确认；健康或明确的判断不写访谈建议，跟进动作放末尾跟进线索段。
- 写作模板是判断原则（看什么、怎么推理、什么情况不构成问题），不是措辞模板。用你自己的语言写判断，不要照抄模板里的原句；每条判断要针对该生的具体数据，不要写成通用结论。
- 语言风格：用自然、专业的判断语气写，像导师写评估备注。直接给判断，紧跟为什么——判断与依据之间可以有完整的推理链，不要只抛结论。避免「说明」「表明」「这暗示」「这可能意味着」等因果连接词堆砌；数据已在该题上方展示，判断不复述数据。句数按【判断深度】分级执行。

【逐问题写作模板（每个问题必须遵守对应模板）】
下面给出每个评估问题的写作锚点（#### 标题）与判断原则：看哪些指标、怎么推理、什么情况不构成问题、禁写什么。
你的输出中每个 #### 标题必须与这里逐字一致（后端按标题把判断归位到该题数据行下方，标题不一致会归位失败）。
没有数据的问题不要输出。

{_e4_judgment_guides_block()}

【输出格式】markdown，按 E1→E2→E3→E4 顺序。
每个维度用 ### 标题；每个评估问题用 #### 开头，标题逐字照抄上方模板锚点（E2 没有「问题：」输入行，固定输出 #### E2 · Energy（精力管理））。
#### 标题下直接写判断正文：以「判断：」起头或直接写均可（后端会统一加前缀），不得重复标题问题本身。
句数与内容按上方【判断深度】分级执行；可在判断中引用关键指标名称，但不要复述数据行数值。
全部问题判断完成后，必须依次输出以下三个段落（标题逐字使用，不得改名）：

### 核心问题
列出该生真正需要关注的领域（需介入/需支持/关注级），每个领域 1-2 行：领域名、判断依据指标名称、为什么对该生需要关注。不列健康/中性。不写数值。不要用「需询证」标签——带 bias 标注的数据已是专家确认的事实、不需要确认；只有 problem:OBSERVATION 标记的才是待确认。

### 可能失真·先观察
仅列出 problem:OBSERVATION 标记的数据点（测评状态可能失真）。没有则写「无」。带 bias 标注的数据点不属于此列（bias 是方向性判断，不是测评失真）。

### 跟进线索与切入点
按优先级逐条写具体操作方向。每条包含：做什么、为什么（基于哪个数据点）、怎么做（如点名凭远内部工具并说明用法）。不要泛泛写「观察」「关注」，要写可执行的动作。"""


def _sanitize_e4_step2(content: str) -> str:
    """清洗 Step2 AI 输出中的输入回显（数据行/问题判定行在数据区已存在）。

    只删确定性前缀的整行，不做语义删改；压缩多余空行。
    """
    if not content:
        return content
    echo = re.compile(r"^\s*#{0,6}\s*(?:\*{0,2}\s*)?"
                      r"(问题判定|\[EVAL\]|\[ORDER\]|\[NORM\]|\[REF\]|\[JUDGE\])")
    kept = [ln for ln in content.splitlines() if not echo.match(ln)]
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip() + "\n"


def _e4_step2_tail(full_analysis: str) -> str:
    """从 Step2 输出截取三段式综合段（从「核心问题」所在标题行开始）。"""
    marker = "核心问题"
    if marker not in (full_analysis or ""):
        # 兼容旧输出中的「显著问题」
        marker = "显著问题"
        if marker not in (full_analysis or ""):
            return ""
    idx = full_analysis.index(marker)
    line_start = full_analysis.rfind("\n", 0, idx)
    return full_analysis[line_start + 1:].strip()


# E2 无问题文本，AI 输出的固定锚点（归一化前后的多种写法都映射到 E2_ENERGY）
_E2_JUDGMENT_KEY = "E2_ENERGY"
_E2_HEADING_VARIANTS = ("E2·Energy（精力管理）", "E2·Energy(精力管理)",
                        "E2精力管理", "E2·精力管理", "精力管理")


def _norm_judgment_heading(text: str) -> str:
    """归一化判断标题：去 markdown 符号/空白、去「问题：」前缀、去首尾标点。"""
    s = re.sub(r"[\s*_`>#]+", "", (text or "").strip())
    s = re.sub(r"^问题[：:]", "", s)
    return s.strip("：:。.，,；;!?？()（）[]【】")


def _build_judgment_key_map() -> Dict[str, str]:
    """框架问题标题归一化 → 框架 q（E2 → E2_ENERGY）。"""
    kmap: Dict[str, str] = {}
    for v in _E2_HEADING_VARIANTS:
        kmap[_norm_judgment_heading(v)] = _E2_JUDGMENT_KEY
    for dim_def in _eval_rules.E4_FRAMEWORK:
        for g in dim_def["groups"]:
            q = g.get("q")
            if q:
                kmap[_norm_judgment_heading(q)] = q
    return kmap


def _match_judgment_key(title_norm: str, key_map: Dict[str, str]) -> Optional[str]:
    """标题归一化精确匹配 → 双向 contains 模糊匹配（短于 6 字不做模糊，防误配）。"""
    if not title_norm:
        return None
    if title_norm in key_map:
        return key_map[title_norm]
    if len(title_norm) < 6:
        return None
    for hk, q in key_map.items():
        if len(hk) >= 6 and (hk in title_norm or title_norm in hk):
            return q
    return None


def _parse_e4_judgments(full_analysis: str) -> Dict[str, Any]:
    """把 Step2 AI 输出切成 {问题: 判断正文} + 三段式综合 + 未归位片段。

    - #### 标题按 E4_JUDGMENT_GUIDES 锚点归位（E2 固定标题 → E2_ENERGY）；
    - 遇到「### 核心问题」或「### 显著问题」（旧版兼容）起，剩余原文整体作为三段式综合（含三个小节）；
    - 归位失败的 #### 块进 orphans（标题, 正文），不丢内容；
    - 判断正文开头的「判断：」前缀在此剥除，由拼装端统一添加。
    """
    result: Dict[str, Any] = {"judgments": {}, "synthesis": "", "orphans": []}
    content = (full_analysis or "").strip()
    if not content:
        return result
    key_map = _build_judgment_key_map()

    judgments: Dict[str, str] = {}
    orphans: List[tuple] = []
    cur_title: Optional[str] = None
    cur_body: List[str] = []

    def _flush() -> None:
        if cur_title is None:
            return
        body = "\n".join(cur_body).strip()
        body = re.sub(r"^\s*(?:\*{0,2}\s*)?判断\s*[：:]\s*\*{0,2}\s*", "",
                      body, count=1)
        body = body.strip()
        if not body:
            return
        key = _match_judgment_key(_norm_judgment_heading(cur_title), key_map)
        if key:
            judgments[key] = (judgments[key] + "\n" + body) if key in judgments else body
        else:
            orphans.append((cur_title.strip(), body))

    lines = content.splitlines()
    synthesis_idx: Optional[int] = None
    for i, ln in enumerate(lines):
        m3 = re.match(r"^#{1,3}\s+(.+?)\s*#*$", ln)
        m4 = re.match(r"^####\s+(.+?)\s*#*$", ln)
        if m3 and not m4:
            _flush()
            cur_title, cur_body = None, []
            if "核心问题" in m3.group(1) or "显著问题" in m3.group(1):
                synthesis_idx = i
                break
            continue
        if m4:
            _flush()
            cur_title, cur_body = m4.group(1), []
            continue
        if cur_title is not None:
            cur_body.append(ln)
    _flush()

    result["judgments"] = judgments
    result["orphans"] = orphans
    if synthesis_idx is not None:
        result["synthesis"] = "\n".join(lines[synthesis_idx:]).strip()
    return result


def _strip_y4_data_section(interpretation: str) -> str:
    """裁掉 Y4 解读中的「数据呈现」段（原始数据 E4_EVALUATIONS 已有，避免重复）。

    匹配 markdown 标题（#{1,6}）含「数据呈现」的行，删除该标题至下一个同级或更高级标题之前；
    兼容 **一、数据呈现** 粗体行形态。找不到匹配则原样返回（安全兜底）。
    只作用于下载拼装，不修改 DB 原文。
    """
    if not interpretation or "数据呈现" not in interpretation:
        return interpretation
    lines = interpretation.splitlines()
    start = -1
    start_level = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*.*数据呈现.*$", ln)
        if m:
            start, start_level = i, len(m.group(1))
            break
        if re.match(r"^\s*(?:\*\*)?#?\s*[一二三四五六七八九十0-9]+[、.．]\s*\**\s*.*数据呈现", ln):
            start, start_level = i, 99  # 粗体序号行：下一个同级粗体序号或任意标题都终止
            break
    if start < 0:
        return interpretation
    end = len(lines)
    heading_re = re.compile(r"^(#{1,%d})\s+" % start_level)
    bold_sec_re = re.compile(r"^\s*\*{0,2}\s*[一二三四五六七八九十0-9]+[、.．]")
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if (heading_re.match(ln) or (start_level == 99 and bold_sec_re.match(ln))):
            end = j
            break
    return "\n".join(lines[:start] + lines[end:]).strip()


def _e4_step3_system(rule_category: str) -> str:
    """Step3 system prompt：AI 只写「真实优势」与「名单归属」；结论/行动已由 Step2 三段承载。"""
    return f"""你是 Y4 测评 E4 评估框架的主笔。基于综合分析草稿，撰写「总览」段。

综合分析草稿已包含逐问题判断、核心问题、可能失真·先观察、跟进线索与切入点。
你的任务**不是再总结一遍**：问题清单和行动计划已经存在，禁止复述、禁止再写问题与建议。
你只补两块草稿中没有成段承载的内容：真实优势、名单归属理由。

【硬规则】
1. {_E4_NAMING_RULE}
2. 禁止创造新术语，只使用 Y4/E4 已有词汇。
3. 只依据分析草稿内容，不编造数据；不得为指标组合取新名字。
4. 禁止输出「核心矛盾」「下一步」「问题」「建议」类小节——它们在综合分析中已存在，重复即重写。
5. 行文简洁：真实优势 3-5 条，每条一句；名单理由 2-3 句。允许引用关键数值，但禁止在句尾用
   （）堆叠一长串指标名称清单；指标名自然写进句子里。

【禁止的术语类型（硬约束，违反即重写）】
- 心理学/治疗术语：如"情绪耗竭"、"神经可塑性"、"负向耦合"、"恶性循环"等
- 连字符组合造词、自创概念标签、学术化包装

【名单归属（硬约束，不得改判）】
Python 规则引擎已判定本学生的名单归属为：**{rule_category}**。
这是最终归属：禁止改判、禁止写成其他三类、禁止输出与该归属矛盾的表述。
「### 名单归属」一节只准写：该归属名称逐字出现一次 + 2-3 句支持该归属的数据理由。
四类含义仅供你理解，不得据此自行改判：
- 强干预：E1/E2 存在严重判定（重度档位或多个 PROBLEM 同时成立）
- 弱干预：E1/E2 有需介入/需支持判定但程度较轻（单一判定、程度有限）
- 强潜能：E1/E2 均无 PROBLEM 级判定，且认知能力百分位总≥95、执行功能平均≥90
- 弱潜能：E1/E2 均无 PROBLEM 级判定，但学习力潜力或动力不充分

【输出格式】markdown，且只有两个小节（标题逐字使用）：
### 真实优势
跨维度归纳学生的真实优势（认知/情绪/关系等，标注维度），3-5 条，每条一句。
### 名单归属
第一句逐字写「{rule_category}」，随后 2-3 句数据理由。不得出现其他三类名称。"""


def _build_y4_payload(items: List[Dict[str, Any]], interpretation: str,
                      student: Dict[str, Any], student_name: str = "") -> Dict[str, Any]:
    """构建 Y4 JSON payload v2.0（纯 Y4：四维数据点 + 常模参照 + AI 解读）。

    - 数值型 raw 一律转 number，文本值保留 string；单位独立成字段。
    - 按四维嵌套；排序项带 rank；常模参照单列。
    - 不含任何 E4 内容（无名单、无问题级判定）。
    与数据来源解耦：调用方传入 items、interpretation、student。
    """
    from datetime import datetime as _dt
    if not student_name:
        student_name = student.get("name") or "测试"

    # 幂等副作用：认知 trait 标注、体质评级回写
    try:
        _eval_rules.evaluate_question_verdicts(items)
    except Exception:
        pass
    items = [it for it in items if not _y4_is_empty(it)]

    def _rank_of(label: str) -> Optional[int]:
        digits = ""
        for ch in reversed(label or ""):
            if ch.isdigit():
                digits = ch + digits
            else:
                break
        return int(digits) if digits else None

    def _typed_value(v: Any) -> Any:
        num = _eval_rules._to_number(v)
        return num if num is not None else (v or "")

    def _base_point(it: Dict[str, Any]) -> Dict[str, Any]:
        dp: Dict[str, Any] = {"code": it.get("code", ""), "name": it.get("label", "")}
        if it.get("adjusted") and it.get("original_eval"):
            dp["adjusted_from"] = it.get("original_eval")
        bias = (it.get("data_bias") or "正常").strip()
        if bias and bias != "正常":
            dp["confirmed_direction"] = bias
        if (it.get("problem_status") or "CONFIRMED") == "OBSERVATION":
            dp["needs_verification"] = True
        note = (it.get("note") or "").strip()
        # note 仅作纯单位说明时不重复输出（单位已在 unit 字段）
        unit = _y4_item_unit(it)
        if note and (not unit or note.strip(f"（）() {unit}")):
            dp["note"] = note
        return dp

    dimensions: Dict[str, Dict[str, Any]] = {}
    for dim in _eval_rules._DIM_ORDER:
        dimensions[dim] = {"label": _eval_rules._DIM_LABELS.get(dim, dim),
                           "data_points": []}
    norm_references: List[Dict[str, Any]] = []

    def _bucket_of(it: Dict[str, Any]) -> str:
        dim = it.get("dimension") or _eval_rules.dimension_of(it)
        return dim if dim in dimensions else "学习力"

    for it in sorted(items, key=lambda x: _eval_rules.sort_key_code(x.get("code", ""))):
        src = it.get("eval_source", "") or ""
        unit = _y4_item_unit(it)

        if src == "参照值":
            np = {"code": it.get("code", ""), "name": it.get("label", ""),
                  "value": _typed_value(it.get("raw_value", ""))}
            if unit:
                np["unit"] = unit
            norm_references.append(np)
            continue

        dp = _base_point(it)
        if src == "原始排序":
            dp["type"] = "ranking"
            dp["rank"] = _rank_of(it.get("label", ""))
            dp["value"] = it.get("eval_value") or it.get("raw_value") or ""
        else:
            raw_v = it.get("raw_value", "")
            grade = (it.get("pdf_grade") or "").strip()
            eval_v = it.get("eval_value") or ""
            # 有评级/档位或纯文本（类型/代码/描述）归 text，其余归 measurement
            is_numeric = _eval_rules._to_number(raw_v) is not None
            dp["type"] = "measurement" if is_numeric else "text"
            dp["value"] = _typed_value(raw_v)
            if unit:
                dp["unit"] = unit
            if grade:
                dp["grade"] = grade
            if eval_v:
                dp["evaluation"] = eval_v
            trait = (it.get("trait_label") or "").strip()
            if trait:
                dp["trait"] = trait
                tn = (it.get("trait_note") or "").strip()
                if tn:
                    dp["trait_note"] = tn
            if src and src not in ("规则推导", "待判定"):
                dp["evaluation_source"] = src
        dimensions[_bucket_of(it)]["data_points"].append(dp)

    return {
        "meta": {
            "protocol": "Y4-v2.0",
            "student": student_name,
            "gender": student.get("gender", ""),
            "grade": student.get("grade", ""),
            "school": student.get("school", ""),
            "birthday": student.get("birthday", ""),
            "test_date": student.get("test_date", ""),
            "generated": _dt.now().strftime("%Y-%m-%d %H:%M"),
        },
        "dimensions": dimensions,
        "norm_references": norm_references,
        "ai_interpretation": interpretation or "",
    }


def _get_student_name_from_items(items: List[Dict[str, Any]]) -> str:
    """从 report_data.json 获取学生名。"""
    report_path = DATA_DIR / "report_data.json"
    if report_path.exists():
        student = json.loads(report_path.read_text(encoding="utf-8")).get("student", {}) or {}
        return student.get("name") or "测试"
    return "测试"


_SEVERE_EVALS = {"需特殊关注", "明显偏低", "严重偏低"}


def _determine_list_placement(items: List[Dict[str, Any]],
                              mapping: Optional[Dict] = None) -> Dict[str, Any]:
    """四类归属判定（基于 verdict 引擎，已确认规则）。

    归属分配：E1 情绪 或 E2 精力 任一 verdict=PROBLEM → 干预；否则 → 潜能。
    干预强/弱 = 按严重度：有重度判定（需特殊关注/明显偏低/严重偏低）
                    或 ≥2 个 PROBLEM → 强干预（重点支持）；否则弱干预（轻量支持/观望）。
    潜能强/弱 = 强线：认知能力百分位总（code 002）≥95 且 执行功能三项平均≥90
                    （心力/精力无 PROBLEM 已由归属分配保证）；霍兰德有维度≥7 作加分标注。
    """
    vgroups, _other, _dims = _eval_rules.evaluate_question_verdicts(items)
    P = _eval_rules.VERDICT_PROBLEM

    e1_problems: List[Dict[str, str]] = []
    e2_problems: List[Dict[str, str]] = []
    problem_items: List[Dict[str, str]] = []
    severe_hit = False

    for g in vgroups:
        if g["dim"] not in ("E1", "E2"):
            continue
        v = g.get("verdict")
        if not v:
            continue
        if v["state"] == P:
            entry = {"dim": g["dim"], "q": g.get("q") or "E2 精力管理", "summary": v["summary"]}
            (e1_problems if g["dim"] == "E1" else e2_problems).append(entry)
        for r in v["items"]:
            if r["state"] == P:
                problem_items.append({"dim": g["dim"], "label": r["label"], "eval": r["eval"]})
                if r["eval"] in _SEVERE_EVALS:
                    severe_hit = True

    is_interference = bool(e1_problems or e2_problems)
    placement = "干预" if is_interference else "潜能"

    result: Dict[str, Any] = {
        "placement": placement,
        "e1_has_problem": bool(e1_problems),
        "e2_has_problem": bool(e2_problems),
        "problem_items": problem_items,
    }

    if is_interference:
        strong = severe_hit or (len(e1_problems) + len(e2_problems)) >= 2
        traits = [f"{p['q']}：{p['summary']}" for p in e1_problems + e2_problems]
        result["strength"] = "强" if strong else "弱"
        result["traits"] = traits
        result["detail"] = {"severe_hit": severe_hit,
                            "problem_groups": len(e1_problems) + len(e2_problems)}
    else:
        # 潜能强线（用户定义阈值）：认知能力百分位总（code 002）≥95
        # 且执行功能三项（063-065）平均 ≥90；心力/精力无 PROBLEM 由归属分配保证
        cog_total: Optional[float] = None
        exec_vals: List[float] = []
        holland_hits: List[str] = []
        for it in items:
            label = it.get("label", "") or ""
            code = str(it.get("code", "") or "")
            num = _eval_rules._to_number(it.get("raw_value"))
            if num is None:
                continue
            if code == "002" or (label == "认知能力百分位"):
                cog_total = num
            elif "执行功能" in label and "百分位" in label:
                exec_vals.append(num)
            elif "职业兴趣" in label and "排序" not in label and num >= 7:
                holland_hits.append(f"{label}({num:g})")
        exec_avg = sum(exec_vals) / len(exec_vals) if exec_vals else None
        cog_ok = cog_total is not None and cog_total >= 95
        exec_ok = exec_avg is not None and exec_avg >= 90
        strong = cog_ok and exec_ok  # 心力/精力无 PROBLEM 由归属分配保证

        strong_traits: List[str] = []
        weak_traits: List[str] = []
        if cog_total is not None:
            strong_traits.append(f"认知能力百分位总 {cog_total:g}（{'≥95 达标' if cog_ok else '<95 未达标'}）")
        if exec_avg is not None:
            strong_traits.append(f"执行功能平均 {exec_avg:.1f}（{'≥90 达标' if exec_ok else '<90 未达标'}，{len(exec_vals)}项）")
        if holland_hits:
            strong_traits.append("霍兰德兴趣优势：" + "、".join(holland_hits))
        # 潜能弱证据：E3/E4 的 PROBLEM/WATCH 级结论（学习力潜力/动力不充分）
        for g in vgroups:
            if g["dim"] not in ("E3", "E4"):
                continue
            v = g.get("verdict")
            if not v or v["state"] not in (P, _eval_rules.VERDICT_WATCH):
                continue
            weak_traits.append(f"{g.get('q') or 'E3'}：{v['summary']}")

        result["strength"] = "强" if strong else "弱"
        result["traits"] = strong_traits if strong else weak_traits
        result["strong_traits"] = strong_traits
        result["weak_traits"] = weak_traits
        result["detail"] = {"cog_total": cog_total, "exec_avg": exec_avg,
                            "cog_ok": cog_ok, "exec_ok": exec_ok,
                            "holland_hits": holland_hits}

    result["category"] = f"{'强' if result['strength'] == '强' else '弱'}{placement}"
    return result


def _assemble_e4_protocol(items: List[Dict[str, Any]], include_raw: bool,
                          analyses: Dict[str, str], overview_md: str,
                          full_analysis: str = "", interpretation: str = "",
                          student: Optional[Dict[str, Any]] = None,
                          student_name: str = "") -> str:
    """确定性拼装 E4 工作草稿协议。数据行不经过 AI，Y4 原名逐字保留。

    可选 student/student_name：调用方（如按 report_id 的一站式接口）传入从 DB 取的
    学生信息；不传则 fallback 读 data/report_data.json（兼容 prompt-lab）。
    """
    from datetime import datetime as _dt

    mapping = _db.get_e4_mapping()
    if student is None:
        report_path = DATA_DIR / "report_data.json"
        if report_path.exists():
            student = json.loads(report_path.read_text(encoding="utf-8")).get("student", {}) or {}
        else:
            student = {}
    if not student_name:
        student_name = student.get("name") or "测试"
    now = _dt.now().strftime("%Y-%m-%d %H:%M")

    md: List[str] = []
    md.append("# E4 评估框架传递协议 v1.2")
    md.append("")
    md.append("> 工作草稿，基于 Y4 测评输出构建，用于与学生沟通迭代，")
    md.append("> 识别薄弱点和低垂果实（low-hanging fruits），非最终评估结论。")
    md.append("")
    md.append("## META")
    # 规则兜底名单判定
    list_placement = _determine_list_placement(items, mapping)
    placement_str = list_placement["placement"]
    md.append(f"student: {student_name} | gender: {student.get('gender','')} | grade: {student.get('grade','')} | school: {student.get('school','')}")
    md.append(f"date: {student.get('test_date','')} | generated: {now} | status: WORKING_DRAFT")
    md.append(f"**名单归属: {list_placement.get('category', placement_str)}**")
    md.append("")

    # 按 E4 框架 source of truth（维度→评估问题→指标）分组
    # 同一指标多次出现时，首次完整显示，后续用 [REF] 引用
    # AI 的逐问题判断解析后紧跟在该题数据行下方（数据与判断合并为一个 section）
    fw_groups, _fw_other, _ = _eval_rules.evaluate_question_verdicts(items)
    parsed_analysis = _parse_e4_judgments(_sanitize_e4_step2(full_analysis)) if full_analysis else None
    judgments = (parsed_analysis or {}).get("judgments", {})
    used_judgment_keys: set = set()
    md.append("## E4_EVALUATIONS")
    md.append("")
    seen_codes: set = set()
    for dim in _eval_rules.E4_DIMS:
        dim_groups = [g for g in fw_groups if g["dim"] == dim]
        if not any(g["items"] for g in dim_groups):
            continue
        md.append(f"### {_eval_rules.E4_LABELS[dim]}")
        md.append("")
        for g in dim_groups:
            if not g["items"]:
                continue
            if g.get("q"):
                md.append(f"#### {g['q']}")
            v = g.get("verdict")
            if v:
                v_parts = [f"[VERDICT] {_eval_rules.verdict_label_cn(v['state'], v.get('items') or [])}"]
                la = v.get("list_assignment")
                if la:
                    v_parts.append(f"[LIST] {la}")
                v_parts.append(v['summary'])
                md.append(" | ".join(v_parts))
            for it in g["items"]:
                code = it.get("code", "")
                is_ref = code in seen_codes
                md.append(_format_e4_line(it, include_raw, is_ref=is_ref))
                seen_codes.add(code)
            jkey = g.get("q") or _E2_JUDGMENT_KEY
            body = (judgments.get(jkey) or "").strip()
            if body:
                md.append("")
                md.append(f"判断：{body}")
                used_judgment_keys.add(jkey)
            md.append("")

    if _fw_other:
        md.append("## OTHER_VARIABLES")
        md.append("")
        for it in sorted(_fw_other, key=lambda x: _eval_rules.sort_key_code(x.get("code", ""))):
            md.append(_format_e4_line(it, include_raw))
        md.append("")

    # 三段式综合（核心问题/可能失真·先观察/跟进线索与切入点）— 接在逐问题数据+判断之后
    if parsed_analysis is not None:
        synthesis = (parsed_analysis.get("synthesis") or "").strip()
        if synthesis:
            md.append(synthesis)
            md.append("")
        # 未归位判断兜底：AI 标题与框架锚点对不上、或判断对应问题本次无数据时，不丢内容
        orphan_blocks: List[tuple] = []
        for k, body_text in judgments.items():
            if k not in used_judgment_keys:
                title = "E2 · Energy（精力管理）" if k == _E2_JUDGMENT_KEY else k
                orphan_blocks.append((title, body_text.strip()))
        orphan_blocks.extend(parsed_analysis.get("orphans") or [])
        if orphan_blocks:
            md.append("### 未归位判断（AI 标题未匹配框架，请人工并入）")
            md.append("")
            for title, body_text in orphan_blocks:
                md.append(f"#### {title}")
                md.append(body_text.strip())
                md.append("")
        if not synthesis and not orphan_blocks and full_analysis:
            # AI 调用有输出但解析为空（如失败提示串）：原样保留，避免静默丢失
            md.append("> 注：AI 分析输出无法按问题归位，原文如下：")
            md.append("")
            md.append(full_analysis.strip())
            md.append("")
    else:
        # 兼容旧的逐维度 analyses 调用（无 full_analysis）
        for d in _eval_rules.E4_DIMS:
            if analyses.get(d):
                md.append(f"### {_eval_rules.E4_LABELS[d]}（AI 分析）")
                md.append("")
                md.append(analyses[d])
                md.append("")
        cross = analyses.get("_cross", "")
        if cross:
            md.append("### 综合判断（核心问题 / 可能失真·先观察 / 跟进线索与切入点）")
            md.append("")
            md.append(cross)
            md.append("")

    # 总览（step3 产物）
    md.append("## OVERVIEW")
    md.append("")
    md.append(overview_md or "（未生成）")
    md.append("")

    # Y4 四维解读 — 直接用 AI Y4 解读师的 output，与 E4 并存
    md.append("## Y4_INTERPRETATION")
    md.append("")
    if interpretation:
        # 裁掉 Y4 解读中的「数据呈现」段：原始数据在 E4_EVALUATIONS 已完整存在
        md.append(_strip_y4_data_section(interpretation))
    else:
        md.append("（未提供 Y4 解读，请先在 Prompt Lab 运行 Y4 解读师生成解读后再下载 E4 协议）")
    md.append("")

    # 人工判断汇总 — 只在有调整时才显示
    expert_notes = [it for it in items if (it.get("note") or "").strip() or it.get("adjusted") or it.get("data_bias","正常") != "正常"]
    if expert_notes:
        md.append("## EXPERT_JUDGMENTS")
        md.append("")
        for it in expert_notes:
            parts = [f"[JUDGE] {it.get('label')}"]
            if it.get("adjusted") and it.get("original_eval"):
                parts.append(f"adjusted:{it.get('original_eval')}→{it.get('eval_value')}")
            bias = it.get("data_bias", "正常")
            if bias != "正常":
                parts.append(f"bias:{bias}")
            problem = it.get("problem_status")
            if problem == "OBSERVATION":
                parts.append("problem:OBSERVATION")
            note = (it.get("note") or "").strip()
            if note:
                parts.append(f"note:{note}")
            md.append(" | ".join(parts))
        md.append("")

    # 名单归属
    md.append("---")
    md.append("")
    md.append("## 名单归属")
    md.append("")
    placement = list_placement.get("category", placement_str)
    md.append(f"**{placement}**")
    md.append("")
    if placement_str == "干预":
        md.append("归入干预：E1 情绪或 E2 精力存在需介入/需支持级判定。")
        md.append("")
        if list_placement.get("strength") == "强":
            md.append("强度判定：强（多个判定或严重偏低）")
        else:
            md.append("强度判定：弱（单一判定、程度有限）")
        md.append("")
        if list_placement["problem_items"]:
            md.append("判定指标：")
            for p in list_placement["problem_items"]:
                md.append(f"- {p['dim']} · {p['label']}（{p['eval']}）")
            md.append("")
    else:
        md.append("归入潜能：E1 情绪和 E2 精力均无 PROBLEM 级判定。")
        md.append("")
        strength = list_placement.get("strength", "弱")
        traits = list_placement.get("traits") or []
        if traits:
            md.append(f"{'强潜能' if strength == '强' else '弱潜能'}依据：")
            for t in traits:
                md.append(f"- {t}")
            md.append("")
    md.append("---")
    md.append("凭远教育 · Y4 综合测评系统 | E4 工作草稿")
    return "\n".join(md)
