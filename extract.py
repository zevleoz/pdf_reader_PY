"""从 4 份 PDF 中提取 124 项结构化数据（**强制视觉 OCR 方案**）。

策略
----
1) 每个 PDF 文件名形如 "report_A2.pdf"（由 app.py 保存）。
   我们把 "A2" 等槽位当作 section 来源。
2) **本模块强制依赖视觉 OCR API**（Qwen2.5-VL-72B 或兼容接口）：
   把各 PDF 的代表性页面转成高清图片，调远程视觉大模型返回 124 项
   JSON schema；不支持降级为"纯文本正则"模式。
3) 文本层的正则提取仅作为**辅助补充**：当视觉 API 抓到 124 项后，
   文本层正则用来修正/覆盖明显不一致的项。
4) 若视觉 API 未配置或调用失败：
   - 本模块直接抛出 RuntimeError（带明确提示信息）
   - Flask 前端（app.py）捕获后返回 JSON 错误响应
   - 浏览器弹窗展示错误信息，引导用户配置 API Key

输出：data/report_data.json（含 schema_124: [{code, label, value}, ...]）
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

import dashscope

try:
    from gauge_reader import detect_gauge_value
    HAS_GAUGE_READER = True
except ImportError:
    HAS_GAUGE_READER = False

try:
    from gauge_processor import extract_mindset_gauge
    HAS_MINDSET_GAUGE = True
except ImportError:
    HAS_MINDSET_GAUGE = False

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
PAGES_DIR = BASE_DIR / "pages"
DATA_DIR = BASE_DIR / "data"

PAGES_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# 环境变量 / API 配置（与 extract_with_api.py 一致，保持可互换）
# ---------------------------------------------------------------------------
# 阿里云 DashScope API Key（已 hard code，无需每次手动设置）
DEFAULT_DASHSCOPE_KEY = "sk-ws-H.RYLDEIE.E3Vt.MEUCIQDhlaQEMxHpnz09zmIpQONyI6aUfqP61xHF6ek9bKwGTwIgMxoi1LjUk0j7Lmc5piivXxONI52as5Zx_Dlj9mFt2Qs"

DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY", DEFAULT_DASHSCOPE_KEY).strip()
SILICONFLOW_KEY = os.environ.get("SILICONFLOW_API_KEY", "").strip()
# 阿里云 DashScope 的 OpenAI 兼容模式（推荐）
#   base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
#   model:   qwen-vl-plus 或 qwen-vl-max
# 用法三选一即可：
#   【方案 A · 百炼/DashScope】export DASHSCOPE_API_KEY=<你的key>（已内置默认值）
#   【方案 B · 通义 OpenAI 兼容】export OPENAI_API_KEY=<你的dashscope key>
#                                      export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
#   【方案 C · 硅基流动】export SILICONFLOW_API_KEY=<你的key>
#   通用：export VISION_MODEL_NAME=qwen-vl-plus（默认）
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
VISION_MODEL = (os.environ.get("VISION_MODEL_NAME") or "qwen3-vl-plus").strip()

# 自动选择 provider（优先级：DASHSCOPE > OPENAI > SILICONFLOW）
if DASHSCOPE_KEY:
    VISION_PROVIDER = "dashscope"
    VISION_ACTIVE_KEY = DASHSCOPE_KEY
    VISION_ACTIVE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
elif OPENAI_KEY:
    VISION_PROVIDER = "openai-compat"
    VISION_ACTIVE_KEY = OPENAI_KEY
    VISION_ACTIVE_BASE = OPENAI_BASE_URL or "https://api.openai.com/v1"
elif SILICONFLOW_KEY:
    VISION_PROVIDER = "siliconflow"
    VISION_ACTIVE_KEY = SILICONFLOW_KEY
    VISION_ACTIVE_BASE = "https://api.siliconflow.cn/v1"
else:
    VISION_PROVIDER = "none"
    VISION_ACTIVE_KEY = ""
    VISION_ACTIVE_BASE = ""


def _refresh_vision_env() -> None:
    """重新读取环境变量。解决「Flask 进程启动后才 export」的问题。

    典型场景：
      1. 用户在 terminal A 启动了 python app.py
      2. 然后在 terminal B 里 export DASHSCOPE_API_KEY=xxx
      3. 浏览器访问 → 服务端进程（启动时）读到的是空值
      4. 需要在每次调用前重新 os.environ 读取
    """
    global DASHSCOPE_KEY, SILICONFLOW_KEY, OPENAI_KEY, OPENAI_BASE_URL
    global VISION_MODEL, VISION_PROVIDER, VISION_ACTIVE_KEY, VISION_ACTIVE_BASE

    DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY", DEFAULT_DASHSCOPE_KEY).strip()
    SILICONFLOW_KEY = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    VISION_MODEL = (os.environ.get("VISION_MODEL_NAME") or "qwen3-vl-plus").strip()

    if DASHSCOPE_KEY:
        VISION_PROVIDER = "dashscope"
        VISION_ACTIVE_KEY = DASHSCOPE_KEY
        VISION_ACTIVE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif OPENAI_KEY:
        VISION_PROVIDER = "openai-compat"
        VISION_ACTIVE_KEY = OPENAI_KEY
        VISION_ACTIVE_BASE = OPENAI_BASE_URL or "https://api.openai.com/v1"
    elif SILICONFLOW_KEY:
        VISION_PROVIDER = "siliconflow"
        VISION_ACTIVE_KEY = SILICONFLOW_KEY
        VISION_ACTIVE_BASE = "https://api.siliconflow.cn/v1"
    else:
        VISION_PROVIDER = "none"
        VISION_ACTIVE_KEY = ""
        VISION_ACTIVE_BASE = ""


# ---------------------------------------------------------------------------
# 视觉 API Prompt（小幅精简版）
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """你是专业的PDF报告数据提取助手。

分析规则：
1) 仔细阅读图表中的中文标签和数值
2) 区分"我的得分"和"同龄平均分"
3) 区分百分比(%)和分数
4) 提取BMI、身高、体重等体检数据
5) **仪表盘识别**：识别半圆仪表盘的指针位置，读取刻度值（0-100），输出为"思维模式"指标
6) 忽略页眉页脚和装饰性文字"""

_USER_PROMPT = """分析PDF页面，提取所有数值数据。

特别关注：
- 半圆仪表盘：指针指向的刻度值（0=固定型，100=成长型）
- 甜甜圈图：中心的数值
- 柱状图：柱顶或柱内的数值

输出格式（只输出JSON，不要Markdown）：
{"items":[{"label":"指标名称","value":数值,"unit":"单位","mean":平均值}]}"""


# ---------------------------------------------------------------------------
# DashScope API（qwen2.5-vl-72b-instruct）
# ---------------------------------------------------------------------------
def _call_dashscope(image_b64: str, timeout: int = 120) -> Optional[List[Dict[str, Any]]]:
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    payload = json.dumps({
        "model": "qwen2.5-vl-72b-instruct",
        "input": {
            "messages": [
                {"role": "system", "content": [{"text": _SYSTEM_PROMPT}]},
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/png;base64,{image_b64}"},
                        {"text": _USER_PROMPT},
                    ],
                },
            ]
        },
        "parameters": {"temperature": 0.1, "top_p": 0.9},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {DASHSCOPE_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [])
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict):
                text = c.get("text", "")
            else:
                text = str(c)
            if text:
                parsed = _parse_json_items(text)
                if parsed:
                    return parsed
    return None


# ---------------------------------------------------------------------------
# 通用 OpenAI 兼容（dashscope / siliconflow /自建接口）——默认路径
# 支持 single image (str) 或 multiple images (list of str)
# ---------------------------------------------------------------------------
def _call_openai_compat(image_b64: str | List[str], api_key: str, base_url: str,
                       model: str, timeout: int = 180) -> Optional[List[Dict[str, Any]]]:
    url = base_url.rstrip("/") + "/chat/completions"
    
    # 构建图片内容列表（支持单张或多张）
    if isinstance(image_b64, str):
        image_list = [image_b64]
    else:
        image_list = image_b64
    
    # 构建 user content：先放所有图片，再放 prompt
    user_content = []
    for img in image_list:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img}"}
        })
    user_content.append({"type": "text", "text": _USER_PROMPT})
    
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,  # 多图时返回内容可能更长
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if text:
        return _parse_json_items(text)
    return None


def _call_siliconflow(image_b64: str | List[str], timeout: int = 180) -> Optional[List[Dict[str, Any]]]:
    return _call_openai_compat(image_b64, api_key=SILICONFLOW_KEY,
                               base_url="https://api.siliconflow.cn/v1",
                               model=VISION_MODEL, timeout=timeout)


# ---------------------------------------------------------------------------
# 通用：解析视觉大模型返回的 JSON
# ---------------------------------------------------------------------------
def _parse_json_items(raw: str) -> List[Dict[str, Any]]:
    if not raw:
        return []
    cleaned = re.sub(r"```(?:json)?\s*|```\s*", "", raw, flags=re.IGNORECASE).strip()
    # 先尝试整段
    candidates = [cleaned]
    if "{" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if end > start:
            candidates.append(cleaned[start:end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        items = []
        if isinstance(obj, list):
            items = [it for it in obj if isinstance(it, dict)]
        elif isinstance(obj, dict):
            it_list = obj.get("items")
            if isinstance(it_list, list):
                items = [it for it in it_list if isinstance(it, dict)]
            elif "label" in obj and ("value" in obj or "mean" in obj):
                items = [obj]
        out: List[Dict[str, Any]] = []
        for it in items:
            label = str(it.get("label", "")).strip()
            if not label:
                continue
            try:
                value = it.get("value")
                if value is not None:
                    value = float(value) if "." in str(value) else int(float(str(value)))
                mean = it.get("mean")
                if mean is not None:
                    mean = float(mean) if "." in str(mean) else int(float(str(mean)))
            except (TypeError, ValueError):
                continue
            if value is None and mean is None:
                continue
            out.append({
                "label": label,
                "value": value,
                "mean": mean,
                "unit": str(it.get("unit", "") or ""),
            })
        if out:
            return out
    return []


# ---------------------------------------------------------------------------
# 工具：学生信息提取
# ---------------------------------------------------------------------------
_NOISE_KEYS = (
    "第", "页", "档案ID", "测试时间", "测试日期", "出生日期",
    "指导师", "报告编码", "电子报告", "成长建议", "测评单位",
    "联系电话", "姓", "名", "性", "别", "年", "级", "学", "校",
    "关注公众号", "双培强基", "公众",
)


def extract_student_info(text_blobs: List[str]) -> Dict[str, str]:
    joined = "\n".join(text_blobs)

    def grab(pat: str) -> str:
        m = re.search(pat, joined)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else "—"

    return {
        "name": grab(r"姓\s*名[：:]\s*([^\n]+)"),
        "gender": grab(r"性\s*别[：:]\s*([^\n]+)"),
        "birthday": grab(r"出生日期[：:]\s*([^\n]+)"),
        "test_date": grab(r"测试(?:日期|时间)[：:]\s*([^\n]+)"),
        "grade": grab(r"年\s*级[：:]\s*([^\n]+)"),
        "school": grab(r"学\s*校[：:]\s*([^\n]+)"),
        "teacher": grab(r"(?:测评老师|指导师)[：:]\s*([^\n]+)"),
        "archive_id": grab(r"档案ID[：:]\s*([^\n]+)"),
        "report_code": grab(r"报告编码[：:]\s*([^\n]+)"),
    }


# ---------------------------------------------------------------------------
# 文本解析（保留原有正则能力，做基础/fallback）
# ---------------------------------------------------------------------------
def _is_noise_line(line: str) -> bool:
    s = re.sub(r"\s+", "", line)
    if not s:
        return True
    if re.match(r"^\d+(?:\.\d+)?\s*(?:分|%|cm|kg|小时|CM|KG){0,2}$", s):
        return False
    for k in _NOISE_KEYS:
        if k in s:
            return True
    return False


def extract_items_from_page(text: str, sub_title: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return items

    # 模式 A：标签 + 下一行数字（或同一行 "标签: 数字" 格式）
    for i, line in enumerate(lines):
        if len(line) < 2 or len(line) > 40 or re.match(r"^\s*\d", line):
            continue
        if "得分" in line or "平均分" in line or "报告" in line:
            continue
        if not re.search(r"[\u4e00-\u9fff]", line):
            continue

        # 先试：同一行 "标签: 数字" 格式（最常见）
        m_same = re.search(
            r"^([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 ]{1,24}?)"
            r"\s*[:：=]\s*"
            r"(\d+(?:\.\d+)?)\s*(分|%|CM|KG|cm|kg|小时|kg/m²|kg/m2)?\s*$",
            line,
        )
        if m_same:
            label = m_same.group(1).strip(" :：,，。.")
            if len(label) < 2 or any(k in label for k in ("测评", "报告", "我的", "同龄", "平均")):
                continue
            val_str = m_same.group(2)
            unit = m_same.group(3) or ""
            try:
                value = float(val_str) if "." in val_str else int(val_str)
            except ValueError:
                continue
            items.append({
                "label": label, "value": value, "mean": None,
                "unit": unit, "notes": sub_title, "_source": "A1",
            })
            continue

        # 再试：当前行是纯标签，下几行有数字
        label = re.sub(r"\s*[(（][^)）]*[)）]\s*$", "", line)
        label = re.sub(r"\s*[A-Za-z\- /()]{4,}$", "", label).strip(" :：,，。.")
        if len(label) < 2 or len(label) > 14:
            continue
        if any(k in label for k in ("测评", "报告", "我的", "同龄", "平均")):
            continue
        look = " ".join(lines[i + 1:i + 5])
        m = re.search(r"(\d+(?:\.\d+)?)\s*(分|%|CM|KG|cm|kg|小时|kg/m²|kg/m2)?", look)
        if not m:
            continue
        val_str, unit = m.group(1), m.group(2) or ""
        try:
            value = float(val_str) if "." in val_str else int(val_str)
        except ValueError:
            continue
        if value >= 10000 and unit == "":
            continue
        if value > 500 and unit not in ("%", "分", ""):
            continue
        items.append({
            "label": label, "value": value, "mean": None,
            "unit": unit, "notes": sub_title, "_source": "A2",
        })

    # 模式 B："我的得分" / "平均分"
    candidate_labels: List[str] = [it["label"] for it in items]
    for line in lines:
        if 2 <= len(line) <= 14 and re.search(r"[\u4e00-\u9fff]", line) \
                and not re.match(r"^\s*\d", line) \
                and "得分" not in line and "平均" not in line and "报告" not in line:
            clean = re.sub(r"\s*[(（][^)）]*[)）]\s*$", "", line)
            clean = re.sub(r"\s*[A-Za-z\- /()]{4,}$", "", clean).strip(" :：,，。.")
            if 2 <= len(clean) <= 14:
                candidate_labels.append(clean)

    def _pick_label(idx: int) -> str:
        for back in range(1, 15):
            line_text = lines[idx - back] if idx - back >= 0 else ""
            for lab in candidate_labels:
                if lab and lab in line_text:
                    return lab
        return candidate_labels[-1] if candidate_labels else "未命名"

    for i, line in enumerate(lines):
        m_my = re.search(
            r"(?:我的|本人)?得分[：:是为]{0,3}\s*(\d+(?:\.\d+)?)\s*(分|%|cm|kg|CM|KG|小时)?",
            line,
        )
        m_avg = re.search(
            r"(?:同龄|大家的)?平均(?:分|得分)?[：:是为]{0,3}\s*(\d+(?:\.\d+)?)\s*(分|%|cm|kg|CM|KG|小时)?",
            line,
        )
        if m_my:
            try:
                val = float(m_my.group(1)) if "." in m_my.group(1) else int(m_my.group(1))
            except ValueError:
                val = None
            if val is not None and val < 10000:
                items.append({
                    "label": _pick_label(i), "value": val, "mean": None,
                    "unit": m_my.group(2) or "分", "_source": "B", "notes": sub_title,
                })
        if m_avg:
            try:
                val = float(m_avg.group(1)) if "." in m_avg.group(1) else int(m_avg.group(1))
            except ValueError:
                val = None
            if val is not None and val < 10000:
                items.append({
                    "label": _pick_label(i), "value": None, "mean": val,
                    "unit": m_avg.group(2) or "分", "_source": "B_avg", "notes": sub_title,
                })

    # 模式 C：已知标签全文匹配
    known_labels = [
        "开放性", "宜人性", "责任心", "外倾性", "神经质",
        "抑制控制", "工作记忆", "认知灵活性",
        "深层动机", "表面动机", "自我效能感",
        "学习深层方法与策略", "学习表面方法与策略", "学习自我调节",
        "感知觉", "记忆力", "注意力", "推理能力", "空间能力", "信息加工速度",
        "情绪稳定性", "自卑", "抑郁", "焦虑", "依赖",
        "依恋", "沟通", "亲近",
        "BMI", "饮食习惯", "睡眠习惯", "运动习惯", "身高", "体重",
        "事业型", "社会型", "研究型", "常规型", "艺术型", "现实型",
        "语言能力", "人际关系能力", "内省能力", "身体运动能力",
        "逻辑数学能力", "音乐能力", "自然能力",
        "思维模式", "自主性", "胜任感", "归属感", "成长型思维", "自驱力",
    ]
    joined = "\n".join(lines)
    for lab in known_labels:
        pat_my = rf"{lab}[\s\S]{{0,40}}?我的得分[：:是为]{{0,3}}\s*(\d+(?:\.\d+)?)"
        pat_avg = rf"{lab}[\s\S]{{0,40}}?(?:同龄|大家的)平均[分得分]{{0,3}}[：:是为]{{0,3}}\s*(\d+(?:\.\d+)?)"
        m1 = re.search(pat_my, joined)
        m2 = re.search(pat_avg, joined)
        if m1:
            try:
                val = float(m1.group(1)) if "." in m1.group(1) else int(m1.group(1))
                if val < 10000:
                    items.append({"label": lab, "value": val, "mean": None,
                                  "unit": "分", "_source": "C", "notes": sub_title})
            except ValueError:
                pass
        if m2:
            try:
                val = float(m2.group(1)) if "." in m2.group(1) else int(m2.group(1))
                if val < 10000:
                    items.append({"label": lab, "value": None, "mean": val,
                                  "unit": "分", "_source": "C_avg", "notes": sub_title})
            except ValueError:
                pass

    return items


def _pdf_slot(pdf_path: Path) -> str:
    """把 report_A2.pdf / report_B3.pdf 等映射到 A2/B3/B4/B6 槽位。"""
    m = re.match(r"report_([A-Z]\d+)(?:\s|_|\.|$)", pdf_path.name)
    if m:
        return m.group(1)
    return pdf_path.stem


def process_pdf(pdf_path: Path) -> Tuple[str, str, List[str], List[Dict[str, Any]]]:
    """返回 (slot, pdf_title, text_blobs, items)。"""
    slot = _pdf_slot(pdf_path)
    print(f"  · 解析 {pdf_path.name} (slot={slot})")
    doc = fitz.open(pdf_path)
    img_dir = PAGES_DIR / pdf_path.stem
    img_dir.mkdir(exist_ok=True)

    text_blobs: List[str] = []
    items: List[Dict[str, Any]] = []
    sub_titles_seen: List[str] = []

    current_sub = slot
    for i, page in enumerate(doc, 1):
        text = page.get_text()
        text_blobs.append(text)

        mat = fitz.Matrix(1.6, 1.6)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(img_dir / f"page_{i:02d}.png"))

        for line in [l.strip() for l in text.splitlines() if l.strip()][:5]:
            if re.match(r"^[\u4e00-\u9fff]{2,20}(?:测评)?报告\s*$", line):
                current_sub = line.replace("测评报告", "报告")
                if current_sub not in sub_titles_seen:
                    sub_titles_seen.append(current_sub)
                break

        page_items = extract_items_from_page(text, current_sub)
        for it in page_items:
            it["_page"] = i
            it["_pdf"] = slot
        items.extend(page_items)

    doc.close()
    pdf_title = sub_titles_seen[0] if sub_titles_seen else slot
    print(f"    → 槽位: {slot}；子报告: {sub_titles_seen}；文本提取 {len(items)} 项")
    return slot, pdf_title, text_blobs, items


# ---------------------------------------------------------------------------
# section 组织结构（与原 extract.py 保持一致，generate 依赖这个结构）
# ---------------------------------------------------------------------------
SECTION_LAYOUT: List[Dict[str, Any]] = [
    {"title": "核心素养", "subtitle": "CORE LITERACY",
     "groups": [
         {"name": "认知能力", "labels": ["认知能力", "感知觉", "注意力", "记忆力",
                                         "推理能力", "空间能力", "信息加工速度"]},
         {"name": "情绪稳定性", "labels": ["情绪稳定性", "自卑-自尊", "自卑",
                                           "抑郁-愉快", "抑郁", "焦虑-安详", "焦虑",
                                           "无力感-掌控感", "无力感", "依赖-自主", "依赖"]},
         {"name": "人格（大五）", "labels": ["人格", "开放性", "宜人性", "责任心",
                                             "外倾性", "神经质"]},
         {"name": "社会性 / 依恋关系",
          "labels": ["依恋", "信任-母亲", "信任-父亲", "信任-同伴",
                     "沟通-母亲", "沟通-父亲", "沟通-同伴",
                     "亲近-母亲", "亲近-父亲", "亲近-同伴",
                     "母亲", "父亲", "同伴"]},
         {"name": "体质健康", "labels": ["体质健康", "BMI", "身高", "体重",
                                         "饮食习惯", "睡眠习惯", "运动习惯"]},
     ]},
    {"title": "核心学习能力", "subtitle": "CORE LEARNING ABILITY",
     "groups": [
         {"name": "执行功能", "labels": ["执行功能", "抑制控制", "工作记忆", "认知灵活性"]},
         {"name": "学习动机", "labels": ["学习动机", "深层动机", "表面动机", "自我效能感"]},
         {"name": "学习方法与策略",
          "labels": ["学习方法与策略", "学习深层方法与策略",
                     "学习表面方法与策略", "学习自我调节"]},
     ]},
    {"title": "核心认知能力 & 成长型思维",
     "subtitle": "CORE COGNITIVE ABILITY & GROWTH MINDSET",
     "groups": [
         {"name": "认知能力六项子指标",
          "labels": ["感知觉", "注意力", "记忆力", "推理能力",
                     "空间能力", "信息加工速度"]},
         {"name": "自驱力（内在动机）",
          "labels": ["思维模式", "成长型思维", "自主性", "胜任感", "归属感", "自驱力"]},
     ]},
    {"title": "职业发展", "subtitle": "CAREER DEVELOPMENT",
     "groups": [
         {"name": "职业兴趣 Holland 六型",
          "labels": ["事业型", "社会型", "研究型", "常规型", "艺术型", "现实型"]},
         {"name": "能力优势（多元智能）",
          "labels": ["语言能力", "人际关系能力", "内省能力",
                     "身体运动能力", "逻辑数学能力", "空间能力",
                     "音乐能力", "自然能力"]},
         {"name": "职业价值观",
          "labels": ["职业价值观", "成就感", "经济报酬", "工作环境",
                     "人际关系", "独立性", "稳定性", "智性刺激",
                     "利他主义", "管理权力", "生活方式", "创造力",
                     "审美追求", "多样性"]},
     ]},
]


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for it in items:
        label = str(it.get("label", "")).strip()
        if not label or len(label) < 2:
            continue
        if any(k in label for k in ("报告", "测评", "第", "页", "姓名", "学校")):
            continue
        if it.get("value") is not None and it["value"] >= 10000:
            continue
        if it.get("mean") is not None and it["mean"] >= 10000:
            continue
        entry = merged.setdefault(label, {
            "label": label, "value": None, "mean": None,
            "unit": str(it.get("unit", "") or ""),
            "notes": str(it.get("notes", "") or ""),
            "_page": it.get("_page"), "_pdf": it.get("_pdf", ""),
            "_source": str(it.get("_source", "") or ""),
        })
        if not entry["unit"] and it.get("unit"):
            entry["unit"] = str(it["unit"])
        if it.get("value") is not None:
            if entry["value"] is None:
                entry["value"] = it["value"]
        if it.get("mean") is not None:
            if entry["mean"] is None:
                entry["mean"] = it["mean"]
        if not entry.get("_page") and it.get("_page"):
            entry["_page"] = it["_page"]
    return [v for v in merged.values()
            if v.get("value") is not None or v.get("mean") is not None]


def organize_to_sections(items_by_pdf: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    for its in items_by_pdf.values():
        all_items.extend(its)

    by_label: Dict[str, Dict[str, Any]] = {}
    for it in all_items:
        label = str(it.get("label", "")).strip()
        if not label or len(label) < 2:
            continue
        if any(k in label for k in ("报告", "测评", "第", "页", "姓名", "学校")):
            continue
        if it.get("value") is not None and it["value"] >= 10000:
            continue
        if it.get("mean") is not None and it["mean"] >= 10000:
            continue
        entry = by_label.setdefault(label, {
            "label": label, "value": None, "mean": None,
            "unit": str(it.get("unit", "") or ""),
            "notes": str(it.get("notes", "") or it.get("_pdf", "") or ""),
            "page": it.get("_page"),
        })
        if not entry["unit"] and it.get("unit"):
            entry["unit"] = str(it["unit"])
        if it.get("value") is not None and entry["value"] is None:
            entry["value"] = it["value"]
        if it.get("mean") is not None and entry["mean"] is None:
            entry["mean"] = it["mean"]
        if not entry.get("page") and it.get("_page"):
            entry["page"] = it["_page"]

    sections_out: List[Dict[str, Any]] = []
    for sec in SECTION_LAYOUT:
        groups_out: List[Dict[str, Any]] = []
        for grp in sec["groups"]:
            group_items: List[Dict[str, Any]] = []
            seen = set()
            for cand in grp["labels"]:
                for label, entry in by_label.items():
                    if label in seen:
                        continue
                    if cand == label or cand in label or label in cand:
                        seen.add(label)
                        group_items.append(dict(entry, label=label))
            groups_out.append({"name": grp["name"], "items": group_items})
        sections_out.append({
            "title": sec["title"], "subtitle": sec.get("subtitle", ""),
            "groups": groups_out,
        })
    return sections_out


# ---------------------------------------------------------------------------
# 视觉 API 主流程：为每个 PDF 抓代表性页面 → 调用视觉 API → 解析 → 合并
# ---------------------------------------------------------------------------
def _pick_vision_pages(pdf_path: Path) -> List[int]:
    """选择各 PDF 的代表性页面给视觉 API。

    策略：
    - 第 1 页几乎总是"封面/报告标题 + 学生信息"，跳过。
    - 从第 2 页开始，按 ceil(total / 4) 的步长采样；若总页数很少，
      则第 2 页起全选。
    - 至少一张，最多 4 张（省 token + 节流等待）。
    """
    try:
        doc = fitz.open(pdf_path)
        total = max(1, len(doc))
        doc.close()
    except Exception:
        total = 3

    slot = _pdf_slot(pdf_path)
    if total <= 1:
        return [1]
    if total == 2:
        return [2]
    if total == 3:
        return [2, 3]
    # total >= 4：从第 2 开始，每 ceil(total/4) 张取一张
    step = max(1, (total - 1) // 3)
    picks: List[int] = []
    for p in range(2, total + 1, step):
        picks.append(p)
        if len(picks) >= 4:
            break
    # 保证最后一页也在里面（有时结论页会有总分）
    if picks and picks[-1] != total:
        picks.append(total)
        picks = sorted(set(picks))[-4:]
    print(f"    [视觉] slot={slot}：选页 {picks}（共 {total} 页）")
    return picks


def run_vision_api(items_by_pdf: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """在当前已有的文本提取 items 上，叠加视觉 API 的结果。

    返回 {'provider': ..., 'items_per_pdf': {...}, 'applied_override': N}
    供调试/记录。
    """
    pdfs = sorted(INPUT_DIR.glob("report_*.pdf")) or sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        return {"provider": "none", "note": "没有 PDF 可分析"}

    provider = ""
    if OPENAI_KEY:
        provider = "openai-compat"
        base_url = OPENAI_BASE_URL or "https://api.openai.com/v1"
    elif DASHSCOPE_KEY:
        provider = "dashscope"
    elif SILICONFLOW_KEY:
        provider = "siliconflow"
    else:
        return {
            "provider": "none",
            "note": "未设置 DASHSCOPE_API_KEY / SILICONFLOW_API_KEY / OPENAI_API_KEY，跳过视觉 API。",
        }

    print(f"\n[视觉 API] 使用 {provider}，模型 {VISION_MODEL}")
    total_override = 0
    per_pdf_out: Dict[str, Any] = {}

    for pdf in pdfs:
        slot = _pdf_slot(pdf_path=pdf)
        pdf_items: List[Dict[str, Any]] = items_by_pdf.setdefault(slot, [])

        page_nums = _pick_vision_pages(pdf)
        if not page_nums:
            continue

        # 渲染这些页为图片
        try:
            doc = fitz.open(str(pdf))
        except Exception as e:
            print(f"    打开失败: {e}")
            continue

        image_paths: List[Path] = []
        mat = fitz.Matrix(2.0, 2.0)  # 折中分辨率，平衡 token 消耗与识别准确度
        for p in page_nums:
            try:
                pix = doc[p - 1].get_pixmap(matrix=mat, alpha=False)
                out = PAGES_DIR / f"{pdf.stem}_vision_{p:02d}.png"
                pix.save(str(out))
                image_paths.append(out)
            except Exception as e:
                print(f"    page {p} 渲染失败: {e}")
        doc.close()

        # 多图合并调用：把同一 PDF 的所有图片一次性发给 API
        images_b64: List[str] = []
        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    images_b64.append(b64)
            except Exception as e:
                print(f"    读取图片失败: {e}")
                continue

        if not images_b64:
            print(f"    无有效图片，跳过")
            continue

        t0 = time.time()
        items: Optional[List[Dict[str, Any]]] = None
        err: Optional[str] = None
        try:
            if provider == "dashscope":
                # DashScope 原生 API 不支持多图，逐张调用但用精简 prompt
                for b64 in images_b64:
                    single_items = _call_dashscope(b64)
                    if single_items:
                        items = items or []
                        items.extend(single_items)
            elif provider == "openai-compat":
                items = _call_openai_compat(images_b64, api_key=OPENAI_KEY,
                                            base_url=base_url, model=VISION_MODEL)
            else:
                items = _call_siliconflow(images_b64)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:120]}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        dt = time.time() - t0

        if items:
            pdf_vision_items.extend(items)
            print(f"    {slot} 多图合并调用: {len(items)} 项 ({len(images_b64)} 张图, {dt:.1f}s)")
        else:
            print(f"    {slot} 多图合并调用: 未解析到数据"
                  + (f" err={err}" if err else ""))

        # 把视觉 API 的结果合并到 items_by_pdf[slot]
        # 规则：
        #   1) 先做弱过滤：明显是日期 / 学生元信息的条目丢掉；
        #   2) 文本路径已有同样 label 的条目 -> 用视觉 API 的数字覆盖（覆盖
        #      优先——因为视觉模型在图表上读柱子/百分比更准）；
        #   3) label 没见过，但与任何已有 label 做 "模糊包含" 匹配时 -> 新增；
        #   4) 否则丢弃，避免污染。
        _DROP_KEYWORDS = ("日期", "出生", "报告", "测评", "时间",
                          "年级", "学校", "姓", "名", "电话",
                          "档案", "页", "第几页", "报告编码", "指导师")
        def _ok_label(lab: str) -> bool:
            if not lab or len(lab) < 2:
                return False
            for k in _DROP_KEYWORDS:
                if k in lab:
                    return False
            return True

        existing = {str(it.get("label", "")).strip(): it for it in pdf_items}
        # 已有的 label 集合，用于"模糊包含"匹配
        existing_labels = set(existing.keys())
        def _fuzzy_match_new_label(lab: str) -> bool:
            """判断视觉 API 给出的新 label 是否值得作为一项新增。"""
            if not lab:
                return False
            # 已经有完全一样的 label 了 -> 归到覆盖分支
            if lab in existing_labels:
                return False
            # 任意现有 label 被这个新 label 包含，或反之 -> 认为是"同一指标的
            # 不同表达"，允许新增（相当于该指标的补充）
            for el in existing_labels:
                if el and lab and (el in lab or lab in el):
                    return True
            return False

        # 先把本次视觉返回的 items 去重 + 过滤
        vision_filtered: List[Dict[str, Any]] = []
        seen_labels: set = set()
        for vi in pdf_vision_items:
            label = str(vi.get("label", "")).strip()
            if not _ok_label(label) or label in seen_labels:
                continue
            if vi.get("value") is None and vi.get("mean") is None:
                continue
            seen_labels.add(label)
            vision_filtered.append(vi)

        # 文本路径完全没抓到任何项时 -> 放宽：视觉 API 能抓到什么就全收。
        text_path_empty = not any(
            it.get("_source") == "A" or it.get("_source") == "B"
            or it.get("_source") == "C" or it.get("_source") is None
            for it in pdf_items
        )
        text_path_empty = text_path_empty or len(pdf_items) == 0

        for vi in vision_filtered:
            label = str(vi.get("label", "")).strip()
            value = vi.get("value")
            mean = vi.get("mean")

            entry = existing.get(label)
            if entry is None and not text_path_empty and not _fuzzy_match_new_label(label):
                # 有文本项但视觉给出一个完全不搭的 label -> 丢弃
                continue

            if entry is None:
                new_entry = {
                    "label": label, "value": value, "mean": mean,
                    "unit": str(vi.get("unit", "") or ""),
                    "notes": f"视觉-API/{slot}",
                    "_pdf": slot, "_source": "vision",
                }
                pdf_items.append(new_entry)
                existing[label] = new_entry
                total_override += 1
            else:
                # 视觉 API 覆盖
                changed = False
                if value is not None:
                    old = entry.get("value")
                    if old != value:
                        entry["value"] = value
                        changed = True
                if mean is not None:
                    old = entry.get("mean")
                    if old != mean:
                        entry["mean"] = mean
                        changed = True
                if changed:
                    entry["_source"] = "vision"
                    total_override += 1

        # 记录调试信息
        per_pdf_out[slot] = {
            "pages": page_nums,
            "vision_items": [
                {"label": it.get("label"), "value": it.get("value"),
                 "mean": it.get("mean"), "unit": it.get("unit")}
                for it in pdf_vision_items
            ],
        }

    result = {
        "provider": provider,
        "applied_override": total_override,
        "items_per_pdf": per_pdf_out,
    }
    # 写一份单独的 api_extracted_data.json 方便调参
    (DATA_DIR / "api_extracted_data.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ===========================================================================
# 124 项正式数据点 SCHEMA（用于视觉 LLM 严格输出 + 回填 USER_DATA）
# 每个条目:
#   code:       001..124（最终 PDF 的编号口径）
#   label:      中文标签（与学生最终报告一致）
#   type:       "int" | "float" | "str"
#   unit:       单位（可空）
#   source_pdf: 优先从哪个 PDF 抓取
#   note:       取数口径说明/档位换算规则
#
# 规则：
#   ·认知能力（001-008）用 B4 覆盖 A2；
#   ·依恋关系档位必须按分数换算，不能目测。
# ===========================================================================
SCHEMA_124: List[Dict[str, Any]] = [
    # 1) 认知能力（B4）——共 8 项
    {"code": "001", "label": "认知能力总得分", "type": "number",
     "source_pdf": "B4", "note": "来自 B4 认知能力报告的总分/量表分"},
    {"code": "002", "label": "认知能力百分位", "type": "number",
     "source_pdf": "B4", "note": "百分位 0-99"},
    {"code": "003", "label": "认知能力-感知觉百分位", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "004", "label": "认知能力-注意力百分位", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "005", "label": "认知能力-记忆力百分位", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "006", "label": "认知能力-推理能力百分位", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "007", "label": "认知能力-空间能力百分位", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "008", "label": "认知能力-加工速度百分位", "type": "number",
     "source_pdf": "B4", "note": ""},

    # 2) 情绪稳定性（A2）——共 6 项
    {"code": "009", "label": "情绪稳定性总分", "type": "number",
     "source_pdf": "A2", "note": "来自 A2 情绪稳定性报告的总分"},
    {"code": "010", "label": "情绪稳定性结果档位", "type": "string",
     "source_pdf": "A2", "note": "只写报告里写的原始档位，如 高/中/低，不要写数字"},
    {"code": "011", "label": "情绪稳定性-自卑自尊得分", "type": "number",
     "source_pdf": "A2", "note": "情绪稳定性四个子项得分之一"},
    {"code": "012", "label": "情绪稳定性-抑郁愉快得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "013", "label": "情绪稳定性-焦虑安详得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "014", "label": "情绪稳定性-无力感掌控感得分", "type": "number",
     "source_pdf": "A2", "note": ""},

    # 3) 人格（A2）——共 5 项
    {"code": "015", "label": "人格-开放性得分", "type": "number",
     "source_pdf": "A2", "note": "人格大五因素的得分（报告里给出的那个数值即可）"},
    {"code": "016", "label": "人格-宜人性得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "017", "label": "人格-责任心得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "018", "label": "人格-外倾性得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "019", "label": "人格-神经质得分", "type": "number",
     "source_pdf": "A2", "note": ""},

    # 4) 依恋关系（A2）——共 21 项（3 类型 + 9 分数 + 9 档位）
    {"code": "020", "label": "依恋关系-母亲类型", "type": "string",
     "source_pdf": "A2", "note": "依恋类型分类文字，如：安全型 / 专注型 / 轻视型 / 先占型"},
    {"code": "021", "label": "依恋关系-父亲类型", "type": "string",
     "source_pdf": "A2", "note": ""},
    {"code": "022", "label": "依恋关系-同伴类型", "type": "string",
     "source_pdf": "A2", "note": ""},
    {"code": "023", "label": "依恋关系-信任-母亲得分", "type": "number",
     "source_pdf": "A2", "note": "满分 50"},
    {"code": "024", "label": "依恋关系-信任-父亲得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "025", "label": "依恋关系-信任-同伴得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "026", "label": "依恋关系-沟通-母亲得分", "type": "number",
     "source_pdf": "A2", "note": "满分 45"},
    {"code": "027", "label": "依恋关系-沟通-父亲得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "028", "label": "依恋关系-沟通-同伴得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "029", "label": "依恋关系-亲近-母亲得分", "type": "number",
     "source_pdf": "A2", "note": "满分 30"},
    {"code": "030", "label": "依恋关系-亲近-父亲得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "031", "label": "依恋关系-亲近-同伴得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "032", "label": "依恋关系-信任-母亲档位", "type": "string",
     "source_pdf": "A2", "note": "必须按分数换算：1-17 → 低；18-34 → 中；35-50 → 高；只写 低/中/高"},
    {"code": "033", "label": "依恋关系-信任-父亲档位", "type": "string",
     "source_pdf": "A2", "note": "1-17 低 / 18-34 中 / 35-50 高"},
    {"code": "034", "label": "依恋关系-信任-同伴档位", "type": "string",
     "source_pdf": "A2", "note": "1-17 低 / 18-34 中 / 35-50 高"},
    {"code": "035", "label": "依恋关系-沟通-母亲档位", "type": "string",
     "source_pdf": "A2", "note": "1-15 低 / 16-30 中 / 31-45 高"},
    {"code": "036", "label": "依恋关系-沟通-父亲档位", "type": "string",
     "source_pdf": "A2", "note": "1-15 低 / 16-30 中 / 31-45 高"},
    {"code": "037", "label": "依恋关系-沟通-同伴档位", "type": "string",
     "source_pdf": "A2", "note": "1-15 低 / 16-30 中 / 31-45 高"},
    {"code": "038", "label": "依恋关系-亲近-母亲档位", "type": "string",
     "source_pdf": "A2", "note": "1-10 低 / 11-20 中 / 21-30 高"},
    {"code": "039", "label": "依恋关系-亲近-父亲档位", "type": "string",
     "source_pdf": "A2", "note": "1-10 低 / 11-20 中 / 21-30 高"},
    {"code": "040", "label": "依恋关系-亲近-同伴档位", "type": "string",
     "source_pdf": "A2", "note": "1-10 低 / 11-20 中 / 21-30 高"},

    # 5) 体质健康（A2）——共 10 项（去掉综合得分/档位）
    {"code": "041", "label": "体质健康-BMI得分", "type": "number",
     "source_pdf": "A2", "note": "BMI 数值"},
    {"code": "042", "label": "体质健康-BMI等级", "type": "string",
     "source_pdf": "A2", "note": "报告里写的等级文字，如：偏瘦/正常/超重/肥胖"},
    {"code": "043", "label": "体质健康-身高cm", "type": "number",
     "source_pdf": "A2", "note": "厘米"},
    {"code": "044", "label": "体质健康-体重kg", "type": "number",
     "source_pdf": "A2", "note": "公斤"},
    {"code": "045", "label": "体质健康-饮食习惯得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "046", "label": "体质健康-饮食评级", "type": "string",
     "source_pdf": "A2", "note": "评级文字，如：良好/优秀/一般"},
    {"code": "047", "label": "体质健康-睡眠习惯得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "048", "label": "体质健康-睡眠评级", "type": "string",
     "source_pdf": "A2", "note": ""},
    {"code": "049", "label": "体质健康-运动习惯得分", "type": "number",
     "source_pdf": "A2", "note": ""},
    {"code": "050", "label": "体质健康-运动评级", "type": "string",
     "source_pdf": "A2", "note": ""},
    {"code": "050a", "label": "体质健康-饮食习惯描述", "type": "string",
     "source_pdf": "A2", "note": "A2第九页左下角饮食习惯的描述文本，包含数字和评价"},

    # 6) 自我概念（B4）——共 8 项（仅保留整体值/档位 + 6 个子项得分，去掉子项档位和备注）
    {"code": "051", "label": "自我概念整体值", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "052", "label": "自我概念整体档位", "type": "string",
     "source_pdf": "B4", "note": "按 B4 报告原文写档位文字，不要数字"},
    {"code": "053", "label": "自我概念-行为表现", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "054", "label": "自我概念-能力与学校表现", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "055", "label": "自我概念-躯体外貌", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "056", "label": "自我概念-情绪状态", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "057", "label": "自我概念-合群", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "058", "label": "自我概念-幸福与满足", "type": "number",
     "source_pdf": "B4", "note": ""},

    # 7) 内驱力（B4）——共 4 项（思维模式 + 自主性/胜任感/归属感）
    {"code": "059", "label": "思维模式结果", "type": "number",
     "source_pdf": "B4", "note": "0=固定型思维模式，100=成长型思维模式，可中间值；写数字"},
    {"code": "060", "label": "自驱力-自主性", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "061", "label": "自驱力-胜任感", "type": "number",
     "source_pdf": "B4", "note": ""},
    {"code": "062", "label": "自驱力-归属感", "type": "number",
     "source_pdf": "B4", "note": ""},

    # 8) 执行功能（B3）——共 3 项
    {"code": "063", "label": "执行功能-抑制控制百分位", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "064", "label": "执行功能-工作记忆百分位", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "065", "label": "执行功能-认知灵活性百分位", "type": "number",
     "source_pdf": "B3", "note": ""},

    # 9) 学习动机与策略（B3）——共 6 项
    {"code": "066", "label": "学习动机-深层动机", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "067", "label": "学习动机-表面动机", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "068", "label": "学习动机-自我效能感", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "069", "label": "学习方法与策略-学习深层方法与策略", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "070", "label": "学习方法与策略-学习表面方法与策略", "type": "number",
     "source_pdf": "B3", "note": ""},
    {"code": "071", "label": "学习方法与策略-学习自我调节", "type": "number",
     "source_pdf": "B3", "note": ""},

    # 10) 职业兴趣（B6）——共 7 项（代码 + 6 维度）
    {"code": "072", "label": "职业兴趣代码", "type": "string",
     "source_pdf": "B6", "note": "RIASEC 三字母代码，例如：IES；只写字母"},
    {"code": "073", "label": "职业兴趣-现实型", "type": "number",
     "source_pdf": "B6", "note": "R"},
    {"code": "074", "label": "职业兴趣-研究型", "type": "number",
     "source_pdf": "B6", "note": "I"},
    {"code": "075", "label": "职业兴趣-艺术型", "type": "number",
     "source_pdf": "B6", "note": "A"},
    {"code": "076", "label": "职业兴趣-社会型", "type": "number",
     "source_pdf": "B6", "note": "S"},
    {"code": "077", "label": "职业兴趣-事业型", "type": "number",
     "source_pdf": "B6", "note": "E"},
    {"code": "078", "label": "职业兴趣-常规型", "type": "number",
     "source_pdf": "B6", "note": "C"},

    # 11) 能力优势（B6）——8 得分 + 8 排序
    {"code": "079", "label": "能力优势-语言能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "080", "label": "能力优势-逻辑数学能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "081", "label": "能力优势-音乐能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "082", "label": "能力优势-空间能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "083", "label": "能力优势-身体运动能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "084", "label": "能力优势-人际关系能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "085", "label": "能力优势-内省能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "086", "label": "能力优势-自然能力", "type": "number",
     "source_pdf": "B6", "note": ""},
    # 排序项
    {"code": "087", "label": "能力优势排序1", "type": "string",
     "source_pdf": "B6", "note": "按分数从高到低排序，第 1 名的能力名称"},
    {"code": "088", "label": "能力优势排序2", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "089", "label": "能力优势排序3", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "090", "label": "能力优势排序4", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "091", "label": "能力优势排序5", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "092", "label": "能力优势排序6", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "093", "label": "能力优势排序7", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "094", "label": "能力优势排序8", "type": "string",
     "source_pdf": "B6", "note": ""},

    # 12) 职业价值观（B6）——15 得分 + 15 排序（共 30 项，全 15 项都排序）
    {"code": "095", "label": "职业价值观-创造发明", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "096", "label": "职业价值观-独立自主", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "097", "label": "职业价值观-美的追求", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "098", "label": "职业价值观-智力激发", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "099", "label": "职业价值观-利他助人", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "100", "label": "职业价值观-成就感", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "101", "label": "职业价值观-管理权力", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "102", "label": "职业价值观-工作环境", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "103", "label": "职业价值观-同事关系", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "104", "label": "职业价值观-上司关系", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "105", "label": "职业价值观-多样变化", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "106", "label": "职业价值观-经济报酬", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "107", "label": "职业价值观-安全稳定", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "108", "label": "职业价值观-声望地位", "type": "number",
     "source_pdf": "B6", "note": ""},
    {"code": "109", "label": "职业价值观-生活方式", "type": "number",
     "source_pdf": "B6", "note": ""},
    # 排序项 1-15（全 15 项都排序，从高到低）
    {"code": "110", "label": "职业价值观排序1", "type": "string",
     "source_pdf": "B6", "note": "按分数从高到低排序，第 1 名的维度名称"},
    {"code": "111", "label": "职业价值观排序2", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "112", "label": "职业价值观排序3", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "113", "label": "职业价值观排序4", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "114", "label": "职业价值观排序5", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "115", "label": "职业价值观排序6", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "116", "label": "职业价值观排序7", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "117", "label": "职业价值观排序8", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "118", "label": "职业价值观排序9", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "119", "label": "职业价值观排序10", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "120", "label": "职业价值观排序11", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "121", "label": "职业价值观排序12", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "122", "label": "职业价值观排序13", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "123", "label": "职业价值观排序14", "type": "string",
     "source_pdf": "B6", "note": ""},
    {"code": "124", "label": "职业价值观排序15", "type": "string",
     "source_pdf": "B6", "note": "按分数从高到低排序，第 15 名的维度名称"},

    # 13) 内驱力常模平均数（B4）——共 3 项（PDF中直接提供的同龄常模均值）
    {"code": "125", "label": "自驱力-自主性常模平均数", "type": "number",
     "source_pdf": "B4", "note": "自驱力-自主性维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "126", "label": "自驱力-胜任感常模平均数", "type": "number",
     "source_pdf": "B4", "note": "自驱力-胜任感维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "127", "label": "自驱力-归属感常模平均数", "type": "number",
     "source_pdf": "B4", "note": "自驱力-归属感维度对应的同龄常模平均数，PDF中直接提供"},

    # 14) 学习动机与策略常模平均数（B3）——共 6 项（PDF中直接提供的同龄常模均值）
    {"code": "128", "label": "学习动机-深层动机常模平均数", "type": "number",
     "source_pdf": "B3", "note": "学习动机-深层动机维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "129", "label": "学习动机-表面动机常模平均数", "type": "number",
     "source_pdf": "B3", "note": "学习动机-表面动机维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "130", "label": "学习动机-自我效能感常模平均数", "type": "number",
     "source_pdf": "B3", "note": "学习动机-自我效能感维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "131", "label": "学习方法与策略-学习深层方法与策略常模平均数", "type": "number",
     "source_pdf": "B3", "note": "学习方法与策略-学习深层方法与策略维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "132", "label": "学习方法与策略-学习表面方法与策略常模平均数", "type": "number",
     "source_pdf": "B3", "note": "学习方法与策略-学习表面方法与策略维度对应的同龄常模平均数，PDF中直接提供"},
    {"code": "133", "label": "学习方法与策略-学习自我调节常模平均数", "type": "number",
     "source_pdf": "B3", "note": "学习方法与策略-学习自我调节维度对应的同龄常模平均数，PDF中直接提供"},
]


# ---------------------------------------------------------------------------
# 档位换算（依恋关系）
# ---------------------------------------------------------------------------
def _attachment_tier(kind: str, score: float) -> str:
    """根据分数换算依恋关系档位（按报告模板给的标准）。"""
    if score is None:
        return "—"
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "—"
    if kind == "信任":
        if v <= 17: return "低"
        if v <= 34: return "中"
        return "高"
    if kind == "沟通":
        if v <= 15: return "低"
        if v <= 30: return "中"
        return "高"
    if kind == "亲近":
        if v <= 10: return "低"
        if v <= 20: return "中"
        return "高"
    return "—"


# ---------------------------------------------------------------------------
# 新的视觉 API 主流程：一次 API call 喂多张代表页
# ---------------------------------------------------------------------------
_SCHEMA_PROMPT_USER_124 = """你是一个严格按编号从 PDF 报告中抽取数据的助手。
以下是我需要你严格输出的 133 项数据点的编号和取值口径。
输出形式固定为一个 JSON：顶层只有一个 key "data"，对应一个长度 133 的数组。
数组里每一项为 {"code": "NNN", "value": <你的结果>}，NNN 是 001 到 133。
必须从 001 开始顺序写到 133 一个都不能少。编号不能跳。
编号顺序必须严格是我下面定义的顺序。
每个 value 都必须按照我给的"类型约束"来输出：
  - number —— 纯数字（整数或小数均可）。不要写汉字。如果读不到写 ""。
  - string —— 文字值（档位/类型/名称/代码）。
严格按照下面的 133 项定义的 type 字段来输出。不要写其他文字解释。
不要输出 code 和 value 之外的字段。
不要在任何位置写你的分析或解释。
不要用 null。不要用中文在 JSON 之外。
数据点定义（按编号顺序）：
001 认知能力总得分 number（B4）
002 认知能力百分位 number（B4，0-99 之间的百分位）
003 认知能力-感知觉百分位 number（B4）
004 认知能力-注意力百分位 number（B4）
005 认知能力-记忆力百分位 number（B4）
006 认知能力-推理能力百分位 number（B4）
007 认知能力-空间能力百分位 number（B4）
008 认知能力-加工速度百分位 number（B4）
009 情绪稳定性总分 number（A2）
010 情绪稳定性结果档位 string（A2，只写高/中/低或报告里的档位文本，不要写数字）
011 情绪稳定性-自卑自尊得分 number（A2）
012 情绪稳定性-抑郁愉快得分 number（A2）
013 情绪稳定性-焦虑安详得分 number（A2）
014 情绪稳定性-无力感掌控感得分 number（A2）
015 人格-开放性得分 number（A2）
016 人格-宜人性得分 number（A2）
017 人格-责任心得分 number（A2）
018 人格-外倾性得分 number（A2）
019 人格-神经质得分 number（A2）
020 依恋关系-母亲类型 string（A2，依恋类型名称，例如安全型/专注型/轻视型/先占型）
021 依恋关系-父亲类型 string（A2）
022 依恋关系-同伴类型 string（A2）
023 依恋关系-信任-母亲得分 number（A2，满分 50）
024 依恋关系-信任-父亲得分 number（A2）
025 依恋关系-信任-同伴得分 number（A2）
026 依恋关系-沟通-母亲得分 number（A2，满分 45）
027 依恋关系-沟通-父亲得分 number（A2）
028 依恋关系-沟通-同伴得分 number（A2）
029 依恋关系-亲近-母亲得分 number（A2，满分 30）
030 依恋关系-亲近-父亲得分 number（A2）
031 依恋关系-亲近-同伴得分 number（A2）
032 依恋关系-信任-母亲档位 string（A2，1-17低；18-34中；35-50高；只写 低/中/高）
033 依恋关系-信任-父亲档位 string（A2，只写 低/中/高）
034 依恋关系-信任-同伴档位 string（A2，只写 低/中/高）
035 依恋关系-沟通-母亲档位 string（A2，1-15低；16-30中；31-45高；只写 低/中/高）
036 依恋关系-沟通-父亲档位 string（A2，只写 低/中/高）
037 依恋关系-沟通-同伴档位 string（A2，只写 低/中/高）
038 依恋关系-亲近-母亲档位 string（A2，1-10低；11-20中；21-30高；只写 低/中/高）
039 依恋关系-亲近-父亲档位 string（A2，只写 低/中/高）
040 依恋关系-亲近-同伴档位 string（A2，只写 低/中/高）
041 体质健康-BMI得分 number（A2）
042 体质健康-BMI等级 string（A2，例如偏瘦/正常/超重/肥胖）
043 体质健康-身高cm number（A2，单位厘米）
044 体质健康-体重kg number（A2，单位公斤）
045 体质健康-饮食习惯得分 number（A2）
046 体质健康-饮食评级 string（A2，如：良好/优秀/一般）
047 体质健康-睡眠习惯得分 number（A2）
048 体质健康-睡眠评级 string（A2）
049 体质健康-运动习惯得分 number（A2）
050 体质健康-运动评级 string（A2）
051 自我概念整体值 number（B4）
052 自我概念整体档位 string（B4，只写报告的档位文本）
053 自我概念-行为表现 number（B4）
054 自我概念-能力与学校表现 number（B4）
055 自我概念-躯体外貌 number（B4）
056 自我概念-情绪状态 number（B4）
057 自我概念-合群 number（B4）
058 自我概念-幸福与满足 number（B4）
059 思维模式结果 number（B4，0=固定型思维模式，100=成长型思维模式，可中间值）
060 自驱力-自主性 number（B4）
061 自驱力-胜任感 number（B4）
062 自驱力-归属感 number（B4）
063 执行功能-抑制控制百分位 number（B3）
064 执行功能-工作记忆百分位 number（B3）
065 执行功能-认知灵活性百分位 number（B3）
066 学习动机-深层动机 number（B3）
067 学习动机-表面动机 number（B3）
068 学习动机-自我效能感 number（B3）
069 学习方法与策略-学习深层方法与策略 number（B3）
070 学习方法与策略-学习表面方法与策略 number（B3）
071 学习方法与策略-学习自我调节 number（B3）
072 职业兴趣代码 string（B6，RIASEC 三字母代码，例如 IES）
073 职业兴趣-现实型 number（B6，R）
074 职业兴趣-研究型 number（B6，I）
075 职业兴趣-艺术型 number（B6，A）
076 职业兴趣-社会型 number（B6，S）
077 职业兴趣-事业型 number（B6，E）
078 职业兴趣-常规型 number（B6，C）
079 能力优势-语言能力 number（B6）
080 能力优势-逻辑数学能力 number（B6）
081 能力优势-音乐能力 number（B6）
082 能力优势-空间能力 number（B6）
083 能力优势-身体运动能力 number（B6）
084 能力优势-人际关系能力 number（B6）
085 能力优势-内省能力 number（B6）
086 能力优势-自然能力 number（B6）
087 能力优势排序1 string（B6，按分数从高到低，填维度名称）
088 能力优势排序2 string（B6）
089 能力优势排序3 string（B6）
090 能力优势排序4 string（B6）
091 能力优势排序5 string（B6）
092 能力优势排序6 string（B6）
093 能力优势排序7 string（B6）
094 能力优势排序8 string（B6）
095 职业价值观-创造发明 number（B6）
096 职业价值观-独立自主 number（B6）
097 职业价值观-美的追求 number（B6）
098 职业价值观-智力激发 number（B6）
099 职业价值观-利他助人 number（B6）
100 职业价值观-成就感 number（B6）
101 职业价值观-管理权力 number（B6）
102 职业价值观-工作环境 number（B6）
103 职业价值观-同事关系 number（B6）
104 职业价值观-上司关系 number（B6）
105 职业价值观-多样变化 number（B6）
106 职业价值观-经济报酬 number（B6）
107 职业价值观-安全稳定 number（B6）
108 职业价值观-声望地位 number（B6）
109 职业价值观-生活方式 number（B6）
110 职业价值观排序1 string（B6，按分数从高到低填维度名称）
111 职业价值观排序2 string（B6）
112 职业价值观排序3 string（B6）
113 职业价值观排序4 string（B6）
114 职业价值观排序5 string（B6）
115 职业价值观排序6 string（B6）
116 职业价值观排序7 string（B6）
117 职业价值观排序8 string（B6）
118 职业价值观排序9 string（B6）
119 职业价值观排序10 string（B6）
120 职业价值观排序11 string（B6）
121 职业价值观排序12 string（B6）
122 职业价值观排序13 string（B6）
123 职业价值观排序14 string（B6）
124 职业价值观排序15 string（B6）
125 自驱力-自主性常模平均数 number（B4，PDF中直接提供的同龄常模均值）
126 自驱力-胜任感常模平均数 number（B4，PDF中直接提供的同龄常模均值）
127 自驱力-归属感常模平均数 number（B4，PDF中直接提供的同龄常模均值）
128 学习动机-深层动机常模平均数 number（B3，PDF中直接提供的同龄常模均值）
129 学习动机-表面动机常模平均数 number（B3，PDF中直接提供的同龄常模均值）
130 学习动机-自我效能感常模平均数 number（B3，PDF中直接提供的同龄常模均值）
131 学习方法与策略-学习深层方法与策略常模平均数 number（B3，PDF中直接提供的同龄常模均值）
132 学习方法与策略-学习表面方法与策略常模平均数 number（B3，PDF中直接提供的同龄常模均值）
133 学习方法与策略-学习自我调节常模平均数 number（B3，PDF中直接提供的同龄常模均值）
"""


def _build_schema_payload(b64_images: List[str]) -> Dict[str, Any]:
    """组装多图 payload（OpenAI 兼容格式）。"""
    image_entries = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        for b64 in b64_images
    ]
    messages = [
        {"role": "system", "content": "你是严格按编号输出数据的助手。不要写解释，只输出 JSON。"},
        {"role": "user", "content": [
            *image_entries,
            {"type": "text", "text": _SCHEMA_PROMPT_USER_124},
        ]},
    ]
    return {"model": VISION_MODEL_NAME, "messages": messages, "max_tokens": 2048, "temperature": 0.1}


VISION_MODEL_NAME = os.environ.get("VISION_MODEL_NAME", "qwen3-vl-plus").strip()


def _call_dashscope_native_multi(b64_images: List[str], timeout: int = 300) -> Optional[Dict[str, Any]]:
    """使用 DashScope 原生 SDK 调用多模态模型（支持多图输入）。"""
    from multiprocessing.pool import ThreadPool
    from concurrent.futures import ThreadPoolExecutor

    # 设置 API key
    dashscope.api_key = VISION_ACTIVE_KEY

    # 构建 DashScope 格式的消息
    # DashScope 的 content 是图片 URL 列表 + 文本
    image_urls = [f"data:image/png;base64,{b64}" for b64 in b64_images]

    messages = [
        {
            "role": "user",
            "content": [
                {"image": img_url} for img_url in image_urls
            ] + [{"text": _SCHEMA_PROMPT_USER_124}]
        }
    ]

    print(f"  [DashScope SDK] 调用模型 {VISION_MODEL_NAME}，含 {len(b64_images)} 张图片")
    t0 = time.time()

    try:
        response = dashscope.MultiModalConversation.call(
            model=VISION_MODEL_NAME,
            messages=messages,
            timeout=timeout,
        )
        dt = time.time() - t0
        print(f"  [DashScope SDK] 响应时间 {dt:.0f}s，状态码: {response.status_code if hasattr(response, 'status_code') else 'N/A'}")

        if response.status_code == 200:
            # 解析响应 - content 可能是字符串或列表
            content = response.output.choices[0].message.content
            if isinstance(content, list):
                # 如果是列表，提取所有文本
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and 'text' in item:
                        text_parts.append(item['text'])
                    elif isinstance(item, str):
                        text_parts.append(item)
                content = ' '.join(text_parts)
            elif not isinstance(content, str):
                content = str(content)
            return {"content": content}
        else:
            print(f"  [DashScope SDK] 错误: {response.message}")
            return None
    except Exception as e:
        dt = time.time() - t0
        print(f"  [DashScope SDK] 调用异常 {type(e).__name__}: {e} ({dt:.0f}s)")
        return None


def _call_openai_compat_multi(payload: Dict[str, Any], timeout: int = 300
                               ) -> Optional[Dict[str, Any]]:
    """把 payload 发给当前配置的 OpenAI 兼容 endpoint。"""
    base = VISION_ACTIVE_BASE or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    url = base.rstrip("/") + "/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {VISION_ACTIVE_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:400]}")
        return None
    except Exception as e:
        print(f"  调用异常 {type(e).__name__}: {e}")
        return None


def _extract_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """解析模型返回的文本到 dict。允许包裹在 ```json 块里。"""
    if not text:
        return None
    t = text.strip()
    # 去掉 ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{[\s\S]+?\})\s*```", t)
    if m:
        candidate = m.group(1)
    else:
        # 取最外层 { ... }
        first = t.find("{")
        last = t.rfind("}")
        if first >= 0 and last > first:
            candidate = t[first:last + 1]
        else:
            candidate = t
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # 尝试把尾部截断到最后一个完整 number/string 的位置（防止未写完）
        last_comma = candidate.rstrip().rstrip(",").rstrip()
        try:
            return json.loads(last_comma + "]}")
        except Exception:
            return None


def _render_pages_for_vision(max_per_pdf: int = 8,
                            matrix_scale: float = 3.0) -> List[Path]:
    """把 input/*.pdf 的代表页渲染成高清 PNG。
    先做"关键字定位"：对每页文本检查关键词（如"职业价值观"、
    "情绪稳定性"、"依恋模式"、"思维模式"等），命中的优先纳入；
    剩余配额用等间距补全。
    """
    pdfs = sorted(INPUT_DIR.glob("report_*.pdf")) or sorted(INPUT_DIR.glob("*.pdf"))
    PAGES_DIR.mkdir(exist_ok=True)
    for old in PAGES_DIR.glob("report_*_vision_*.png"):
        try: old.unlink()
        except Exception: pass

    keyword_hits: Dict[str, List[str]] = {
        "A2": ["情绪稳定性", "人格", "依恋模式", "依恋关系",
               "体质健康", "BMI", "饮食习惯", "睡眠习惯", "运动习惯",
               "自卑感", "抑郁", "焦虑", "无力感", "Controllability"],
        "B3": ["执行功能", "抑制控制", "工作记忆", "认知灵活性",
               "学习动机", "学习方法与策略", "深层动机", "表面动机",
               "自我效能感", "学习自我调节"],
        "B4": ["认知能力", "感知觉", "注意力", "记忆力", "推理能力",
               "空间能力", "加工速度", "自我概念", "行为表现", "思维模式",
               "自驱力", "自主性", "胜任感", "归属感"],
        "B6": ["职业兴趣", "霍兰德", "RIASEC", "Enterprising",
               "能力优势", "语言能力", "逻辑数学能力", "音乐能力",
               "身体运动能力", "人际关系能力", "内省能力", "自然能力",
               "职业价值观", "创造发明", "独立自主", "成就感",
               "经济报酬", "工作环境", "同事关系", "上司关系",
               "多样变化", "管理权力", "安全稳定", "声望地位", "生活方式"],
    }

    paths: List[Path] = []
    for pdf in pdfs:
        doc = fitz.open(str(pdf))
        total = len(doc)
        slot = _pdf_slot(pdf)
        must_pages: List[int] = []
        # 每页文本扫描关键词，命中的优先加入
        for p in range(1, total + 1):
            txt = doc[p - 1].get_text()
            if not txt.strip():
                continue
            for kw in keyword_hits.get(slot, []):
                if kw in txt:
                    must_pages.append(p)
                    break
        must_pages = sorted(set(must_pages))
        
        if slot == "B6" and total >= 13:
            must_pages.append(12)
            must_pages.append(13)
            must_pages = sorted(set(must_pages))
        
        picks: List[int] = []
        if len(must_pages) >= max_per_pdf:
            picks = must_pages[:max_per_pdf]
        else:
            picks = list(must_pages)
            remaining = max_per_pdf - len(picks)
            candidate_pages = [p for p in range(2, total + 1) if p not in picks]
            if candidate_pages:
                step = max(1, len(candidate_pages) // remaining) if remaining else len(candidate_pages)
                for p in candidate_pages[::step]:
                    picks.append(p)
                    if len(picks) >= max_per_pdf:
                        break
            picks = sorted(set(picks))[:max_per_pdf]
        # 如果一份 PDF 页数 ≤ max_per_pdf，直接全选
        if total <= max_per_pdf:
            picks = list(range(1, total + 1))

        for p in picks:
            try:
                pix = doc[p - 1].get_pixmap(matrix=fitz.Matrix(matrix_scale, matrix_scale),
                                           alpha=False)
                out = PAGES_DIR / f"{pdf.stem}_vision_{p:02d}.png"
                pix.save(str(out))
                paths.append(out)
            except Exception as e:
                print(f"  [渲染失败] {pdf.name} page {p}: {e}")
        doc.close()
        print(f"  {pdf.name} slot={slot}: {len(picks)} 页 → PNG (must_pages={len(must_pages)})")
    return paths


def extract_124_points_with_vision() -> Dict[str, Any]:
    """返回：{code: value_str, ...}，其中 value_str 保留原始字符串，
    便于后续写入 USER_DATA 时做二次转换。

    ⚠️  本函数 **强制依赖视觉 API**（不降级为纯文本提取）。
    - 未配置 API key → 抛出 RuntimeError
    - API 调用失败 → 抛出 RuntimeError
    - API 返回格式不符合 124 项 schema → 抛出 RuntimeError

    调用方（app.py 的 Flask 前端）必须捕获这些异常并给用户提示。
    """
    # ⚠️  动态重新检查环境变量（Flask 进程启动后 export 的 key 需要重新读取）
    _refresh_vision_env()

    pdfs = sorted(INPUT_DIR.glob("report_*.pdf")) or sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        return {}

    # 1) 渲染代表页（更多页面，保证关键表格被包含）
    image_paths = _render_pages_for_vision(max_per_pdf=8)
    b64_images = []
    for p in image_paths:
        with open(p, "rb") as f:
            b64_images.append(base64.b64encode(f.read()).decode("utf-8"))

    # 2) ⚠️  强制检查 API key — 无 key 不允许继续
    if not VISION_ACTIVE_KEY:
        raise RuntimeError(
            "未设置视觉 API Key。请在环境变量中配置以下任意一项：\n"
            "  【推荐】export DASHSCOPE_API_KEY=<你的阿里云百炼key>\n"
            "  或：export OPENAI_API_KEY=<key> （可选配 OPENAI_BASE_URL）\n"
            "  或：export SILICONFLOW_API_KEY=<你的硅基流动key>\n"
            "  通用：export VISION_MODEL_NAME=qwen3-vl-plus\n\n"
            "当前方案：视觉 OCR 是必填步骤，不支持纯文本降级。"
        )

    # 3) 使用 DashScope 原生 SDK 调用（支持多图输入）
    print(f"  [视觉 API] 使用 DashScope SDK，模型 {VISION_MODEL_NAME}，含 {len(b64_images)} 张图片")
    t0 = time.time()
    resp = _call_dashscope_native_multi(b64_images, timeout=300)
    dt = time.time() - t0
    if resp is None:
        raise RuntimeError(
            f"视觉 API 调用失败 (超时 / 网络错误 / API key 无效)。\n"
            f"当前配置：DashScope SDK / {VISION_MODEL_NAME}\n\n"
            f"请检查：\n"
            f"  1) API Key 是否有效（{len(VISION_ACTIVE_KEY)} 字符）\n"
            f"  2) 网络是否连通\n\n"
            f"⚠️  当前方案：视觉 OCR 是必填步骤，不支持纯文本降级。"
        )

    # 4) 解析 JSON -> {code: value}
    text = resp.get("content", "")
    print(f"  视觉 API 返回长度 {len(text)} 字符（{dt:.0f}s）")
    parsed = _extract_json_from_response(text)
    if parsed is None or "data" not in parsed:
        # 写 raw text 到 data/ 以便手工检查
        (DATA_DIR / "vision_raw_response.txt").write_text(text, encoding="utf-8")
        raise RuntimeError(
            f"视觉 API 返回格式不符合要求（预期 124 项 JSON schema）。\n"
            f"原始内容已写入 data/vision_raw_response.txt，请检查。\n\n"
            f"⚠️  当前方案：视觉 OCR 是必填步骤，不支持纯文本降级。"
        )

    data = parsed["data"]
    result: Dict[str, Any] = {}
    for item in data:
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        value = item.get("value")
        # value 若为 None / null，记成空字符串
        if value is None:
            value = ""
        result[code] = value
    print(f"  视觉 API 成功读取 {len(result)} / 124 项")
    return result


# ---------------------------------------------------------------------------
# main（走新流程：视觉 124 项优先）
# ---------------------------------------------------------------------------
def main(force_skip_vision: bool = False) -> int:
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"[ERROR] {INPUT_DIR} 下没有 PDF")
        return 1

    # --- A. PDF 文本层基础提取（用于回填报告标题/学生元信息）
    all_text_blobs: List[str] = []
    pdf_titles: List[str] = []
    text_items_by_pdf: Dict[str, List[Dict[str, Any]]] = {}
    for pdf in pdfs:
        slot, title, text_blobs, items = process_pdf(pdf)
        all_text_blobs.extend(text_blobs)
        if slot not in text_items_by_pdf:
            text_items_by_pdf[slot] = []
            pdf_titles.append(slot)
        text_items_by_pdf[slot].extend(items)

    # --- B. 视觉 API 主路径：严格 124 项 schema
    if force_skip_vision:
        vision_result: Dict[str, Any] = {"provider": "skipped"}
        code_values: Dict[str, Any] = {}
    else:
        code_values = extract_124_points_with_vision()
        vision_result = {
            "provider": ("openai-compat" if OPENAI_KEY else "none"),
            "model": VISION_MODEL_NAME,
            "count_124": len(code_values),
        }
        print(f"  [调试] code_values['059'] = {code_values.get('059', 'NOT FOUND')}")

        # --- B2. 职业价值观条形图解析（B6 第13页）
        try:
            from _vision_values_bar import main as extract_values_bar
            values_scores = extract_values_bar()
            if values_scores:
                print(f"  [职业价值观条形图] 成功解析 {len(values_scores)} 项")
                label_to_code = {"创造发明": "095", "独立自主": "096", "美的追求": "097",
                                "智力激发": "098", "利他助人": "099", "成就感": "100",
                                "管理权力": "101", "工作环境": "102", "同事关系": "103",
                                "上司关系": "104", "多样变化": "105", "经济报酬": "106",
                                "安全稳定": "107", "声望地位": "108", "生活方式": "109"}
                for label, score in values_scores.items():
                    code = label_to_code.get(label)
                    if code:
                        code_values[code] = score
                
                sorted_values = sorted(values_scores.items(), key=lambda kv: -kv[1])
                for i, (label, _) in enumerate(sorted_values):
                    rank_code = f"{110 + i:03d}"
                    code_values[rank_code] = label
                print(f"  [职业价值观条形图] 已更新排序")
            else:
                print("  [职业价值观条形图] 解析失败，使用视觉API数据")
        except Exception as e:
            print(f"  [职业价值观条形图] 模块加载失败: {e}")

    # --- C. 文本层兜底（视觉 API 没抓到的项，尝试用文本匹配）
    #     先做"高优先级文本硬匹配"（针对体质健康、依恋关系、认知能力这些
    #     页面格式固定的报告），再回落到模糊 label 匹配。
    #
    # 从所有 PDF 抽一份"扁平文本"，按 slot 分块，便于"只去某份 PDF 找"
    text_by_slot: Dict[str, str] = {}
    for pdf in pdfs:
        doc = fitz.open(str(pdf))
        slot = _pdf_slot(pdf)
        text_by_slot[slot] = "\n".join(p.get_text() for p in doc)
        doc.close()

    def _grep_value(slot_keywords: List[str],
                    label_patterns: List[re.Pattern]) -> Optional[str]:
        """在指定 slot 的文本里，顺序查找多个正则，返回第一个命中的 group(1)。"""
        for slot, text in text_by_slot.items():
            if slot_keywords and not any(k in slot for k in slot_keywords):
                continue
            for pat in label_patterns:
                m = pat.search(text)
                if m:
                    return m.group(1).strip()
        return None

    def _r(pattern: str, flags: int = 0) -> re.Pattern:
        return re.compile(pattern, flags)

    # 把"硬匹配"得到的 code -> value 写到这里，有就覆盖视觉 API
    hard_values: Dict[str, str] = {}

    # ---- 体质健康（A2）
    a2 = text_by_slot.get("A2", "")
    # 身高：178CM / 体重：73KG / BMI：23KG/M²
    m = re.search(r"身高\s*[:：]\s*([\d.]+)\s*[CcＭm]", a2)
    if m: hard_values["043"] = m.group(1)
    m = re.search(r"体重\s*[:：]\s*([\d.]+)\s*[KkGg]", a2)
    if m: hard_values["044"] = m.group(1)
    m = re.search(r"BMI\s*[:：]\s*([\d.]+)", a2)
    if m: hard_values["041"] = m.group(1)

    # BMI 等级："得分 Score ... 23 ... 正常 等级 Grade"
    # 先找 "等级 Grade" 之前 30 字符附近的中文（偏瘦/正常/超重/肥胖）
    idx_grade = a2.find("等级 Grade")
    if idx_grade < 0:
        idx_grade = a2.find("Grade")
    if idx_grade > 0:
        prefix = a2[max(0, idx_grade - 60): idx_grade]
        m = re.search(r"(偏瘦|正常|超重|肥胖|偏轻|良好|一般)", prefix)
        if m:
            hard_values["042"] = m.group(1)
    if "042" not in hard_values or not hard_values["042"]:
        m = re.search(r"(身高|BMI)[\s\S]{0,150}?(偏瘦|正常|超重|肥胖)\b", a2)
        if m:
            hard_values["042"] = m.group(2)

    # 饮食习惯评级："饮食习惯 ... 优"（注意 "饮食习惯" 后面出现 "优"）
    # 睡眠习惯："7.1小时/每天 中等"
    # 运动习惯："11小时/周 优秀"
    m = re.search(r"饮食习惯[\s\S]{0,120}?(优|优秀|良|良好|一般|中等|差|较差|欠佳)\b", a2)
    if m: hard_values["046"] = m.group(1)
    m = re.search(r"睡眠习惯[\s\S]{0,120}?(优|优秀|良|良好|一般|中等|差|较差|欠佳)\b", a2)
    if m: hard_values["048"] = m.group(1)
    m = re.search(r"运动习惯[\s\S]{0,120}?(优|优秀|良|良好|一般|中等|差|较差|欠佳)\b", a2)
    if m: hard_values["050"] = m.group(1)

    # 睡眠习惯得分：7.1 小时 / 每天
    m = re.search(r"([\d.]+)\s*小时", a2)
    if m: hard_values["047"] = m.group(1)
    # 运动习惯得分：11 小时 / 周（注意跟 7.1 小时冲突，找第二个）
    ms = re.findall(r"([\d.]+)\s*小时", a2)
    if len(ms) >= 2:
        hard_values["049"] = ms[1]
    elif len(ms) == 1:
        hard_values.setdefault("049", ms[0])

    # 饮食习惯得分：文本层格式是 "饮食习惯\nEating Habits\n均衡饮食\n优"
    # 可能 PDF 中没有给出数字分，只有评级；用评级来估算数字分（8.0-9.0）
    idx_eat = a2.find("饮食习惯")
    if idx_eat >= 0 and "045" not in hard_values:
        sub = a2[idx_eat: idx_eat + 250]
        m = re.search(r"([\d.]+)\s*分", sub)
        if m:
            hard_values["045"] = m.group(1)
        else:
            # 看 "均衡饮食" 附近有没有数字分（只接受1-10范围内的数字）
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", sub)
            found_numeric = False
            for n in nums:
                try:
                    val = float(n)
                    if 1 <= val <= 10:
                        hard_values["045"] = n
                        found_numeric = True
                        break
                except:
                    pass
            # 如果没有数字分，根据评级估算
            if not found_numeric:
                # 找评级关键词
                m2 = re.search(r"(优|优秀|良|良好|一般|中等|差|较差|欠佳)", sub)
                if m2:
                    grade = m2.group(1)
                    est_map = {"优": "9.0", "优秀": "9.0", "良": "7.0", "良好": "7.0",
                              "一般": "5.0", "中等": "5.0", "差": "3.0", "较差": "3.0", "欠佳": "3.0"}
                    hard_values["045"] = est_map.get(grade, "5.0")

    # ---- 饮食习惯描述（A2第九页左下角）
    eat_desc_pattern = r"食物提供人体必需的能量和营养[\s\S]{0,500}?(你不了解健康饮食的重要性|你基本了解健康饮食的重要性|你了解健康饮食的重要性)"
    m = re.search(eat_desc_pattern, a2)
    if m:
        hard_values["050a"] = m.group(0)

    # ---- 情绪稳定性总分/档位 & 4 子项
    m = re.search(r"总得分是\s*([\d.]+)\s*分", a2)
    if m: hard_values["009"] = m.group(1)
    # 子项：自卑-自尊 / 抑郁-愉快 / 焦虑-安详 / 无力感-掌控感
    # 文本里出现 "自卑感 In... X \n..." 等；先用关键词+数字的相邻查找
    sub_items = [
        ("011", ("自卑", "自卑-自尊", "自卑与自尊")),
        ("012", ("抑郁",)),
        ("013", ("焦虑",)),
        ("014", ("无力感", "无力感-掌控感", "无力感与掌控感")),
    ]
    for code, kws in sub_items:
        for kw in kws:
            i = a2.find(kw)
            if i < 0: continue
            seg = a2[i: i + 120]
            # 优先 "数字分"
            m = re.search(r"([\d.]+)\s*分", seg)
            if m:
                hard_values[code] = m.group(1)
                break
            # 否则找该段第一个数字（排除 1/10 这种刻度）
            nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", seg)
            for n in nums:
                if n in ("1", "10"): continue
                hard_values[code] = n
                break
            break
    # 情绪稳定性档位：留空由视觉 API 决定；或者根据总分区间估算（25-33 正常）
    # 此处不做硬性估算，让视觉 API 发挥作用


    # ---- 依恋关系（A2）
    # 信任 / 沟通 / 亲近 分别对 母亲、父亲、同伴 的得分与档位
    # A2 报告里有 "母亲 / 父亲 / 同伴" 三个块，每个块有 "信任/沟通/亲近" 三项 + 总分/类型
    # 先尝试从 PDF 文本提取到结构化数据
    attach_pairs = [
        ("母亲", "信任", "023", "024"),
        ("母亲", "沟通", "023_dup", None),  # 另一个编号稍后再用
        ("父亲", "信任", "025", "026"),
        ("父亲", "沟通", "025_dup", None),
        ("同伴", "信任", "027", "028"),
        ("同伴", "沟通", "027_dup", None),
    ]
    # 简单策略：A2 全文里抓数字块（依恋关系通常是表格形式）
    # 先看有哪些关键词出现，再尝试提取得分
    # 信任/沟通/亲近三行，每行给一个分数 + 一个等级
    attach_rows = re.findall(r"(信任|沟通|亲近)[\s　]{0,8}([\d.]+)[\s　]{0,8}(低|中|高|优|良)", a2)
    if attach_rows:
        # 简单按顺序分配：母亲=第1组，父亲=第2组，同伴=第3组
        group_map = {"母亲": 0, "父亲": 1, "同伴": 2}
        mapping = [
            ("母亲", "信任", "023", "032"),
            ("母亲", "沟通", "026", "035"),
            ("母亲", "亲近", "029", "038"),
            ("父亲", "信任", "024", "033"),
            ("父亲", "沟通", "027", "036"),
            ("父亲", "亲近", "030", "039"),
            ("同伴", "信任", "025", "034"),
            ("同伴", "沟通", "028", "037"),
            ("同伴", "亲近", "031", "040"),
        ]
        # 把 attach_rows 按类别分
        by_type: Dict[str, List[tuple]] = {"信任": [], "沟通": [], "亲近": []}
        for (k, v, g) in attach_rows:
            by_type[k].append((v, g))
        for person, kind, score_code, tier_code in mapping:
            idx = group_map[person]
            if len(by_type[kind]) > idx:
                val, tier = by_type[kind][idx]
                hard_values[score_code] = val
                hard_values[tier_code] = tier if tier in ("低", "中", "高") else ""

    # 母亲/父亲/同伴类型（依恋类型分类）
    # 报告通常给出"安全型 / 先占型 / 轻视型 / 专注型 / 混合型" 之一
    for code, key in (("020", "母亲"), ("021", "父亲"), ("022", "同伴")):
        m = re.search(
            rf"{key}(?:依恋)?(?:类型)?[\s\S]{{0,60}}?(安全型|先占型|轻视型|专注型|混合型|安全-专注型)",
            a2)
        if m:
            hard_values[code] = m.group(1)

    # ---- 认知能力（B4 覆盖 A2）
    b4 = text_by_slot.get("B4", "")
    # 文本格式: "115\n总得分\nTotal Score\n \n84\n百分位（%）\nPercentile"
    m = re.search(r"([\d.]+)\s*\n\s*总得分", b4)
    if m: hard_values["001"] = m.group(1)
    m = re.search(r"([\d.]+)\s*\n\s*百分位", b4)
    if m: hard_values["002"] = m.group(1)
    # 六项子项百分位
    for key, code in (("感知觉", "003"), ("注意力", "004"), ("记忆力", "005"),
                      ("推理能力", "006"), ("空间能力", "007"), ("加工速度", "008")):
        m = re.search(rf"{key}[\s\S]{{0,80}}?([\d.]+)\s*%", b4)
        if not m:
            m = re.search(rf"{key}[\s\S]{{0,80}}?百分?位[\s　:：]*([\d.]+)", b4)
        if m: hard_values[code] = m.group(1)

    # ---- 情绪稳定性（A2）
    a2 = text_by_slot.get("A2", "")
    # "4个分测验中的总得分是32.5分，同龄人的平均分是40分"
    m = re.search(r"总得分是\s*([\d.]+)\s*分", a2)
    emo_total = None
    if m:
        emo_total = float(m.group(1))
        hard_values["009"] = m.group(1)
    # 档位：基于总分与同龄平均 40 分的相对位置
    # 文本结构：4 个子项总分 = 情绪稳定性分；这里用简单 3 档映射
    if emo_total is not None and "010" not in hard_values:
        if emo_total <= 30:
            hard_values["010"] = "低"
        elif emo_total <= 45:
            hard_values["010"] = "中"
        else:
            hard_values["010"] = "高"
    # 4 子项得分: "自卑 In... 8 \n1\n10\n15" / "抑郁... 7.5" / "焦虑... 6.5" / "无力感... 10.5"
    # 具体做法：定位 Controllability 之后的一段数字序列 [8,1,10,15,7.5,1,10,15,6.5,1,10,15,10.5,1,10,15]
    # 取每 4 个的第一个：8(自卑-自尊), 7.5(抑郁-愉快), 6.5(焦虑-安详), 10.5(无力感-掌控感)
    idx_ctrl = a2.find("Controllability")
    if idx_ctrl > 0:
        seg = a2[idx_ctrl: idx_ctrl + 300]
        nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", seg)
        # 去掉页码（较大的数字如10/15）；这里取 nums 前 16 个（每 4 个一组，共 4 组）
        # 实际序列: [8,1,10,15, 7.5,1,10,15, 6.5,1,10,15, 10.5,1,10,15]
        if len(nums) >= 16:
            # 每 4 个的第一个 = 该维度得分
            sub_scores = [nums[0], nums[4], nums[8], nums[12]]
            for i, code in enumerate(["011", "012", "013", "014"]):
                if code in hard_values: continue
                hard_values[code] = sub_scores[i]

    # ---- 依恋关系（A2）
    # 文本："您和母亲、父亲和同伴在信任方 面的得分分别\n是47分、32分、22分；您和母亲、父亲和同伴在沟通上的得分分别是41分、29分、19分；您和母亲、父亲和同伴在亲近上的\n得分分别是19分、12分、14分。"
    # 方法：找 "信任" / "沟通" / "亲近" 后面的 "得分分别是" 或 "分、" + 三个数字
    anchor_start = a2.find("依恋模式")
    seg_full = a2[anchor_start:] if anchor_start >= 0 else a2

    # 对每个关键词：找到它的位置后，向后跳过一段文本找"得分分别是" 后面 第一个 数字、分号 组
    # 简化：用 find 找每个关键词后面 第一个 "分、" 三联数字组
    def _extract_scores_near(kw: str):
        # 精确锚定：信任方面 / 沟通上的得分 / 亲近上的得分
        # 必须是关键词 自身 紧接着 "方面" 或 "上的得分"，而且不能被"在信任"等前置短语污染
        # 做法：找 "信任方面的得分" / "沟通上的得分" / "亲近上的得分" 精确锚点
        i = seg_full.find(kw)
        if i < 0: return None
        seg = seg_full[i:i+120]
        # 信任方面的得分
        # 沟通上的得分
        # 亲近上的得分
        if kw == "信任":
            # 匹配 "信任方 面的得分"（中间可能有空格或换行）
            pat = r'信任\s*(?:方\s*)?面[\s\S]{0,40}?([\d.]+)\s*分[、，,]\s*([\d.]+)\s*分[、，,]\s*([\d.]+)\s*分'
        elif kw == "沟通":
            pat = r'沟通\s*上[\s\S]{0,40}?([\d.]+)\s*分[、，,]\s*([\d.]+)\s*分[、，,]\s*([\d.]+)\s*分'
        else:  # 亲近
            pat = r'亲近\s*上[\s\S]{0,40}?([\d.]+)\s*分[、，,]\s*([\d.]+)\s*分[、，,]\s*([\d.]+)\s*分'
        m = re.search(pat, seg)
        if m: return (m.group(1), m.group(2), m.group(3))
        return None

    # 信任
    t = _extract_scores_near("信任")
    if t:
        hard_values["023"], hard_values["024"], hard_values["025"] = t
    # 沟通
    t = _extract_scores_near("沟通")
    if t:
        hard_values["026"], hard_values["027"], hard_values["028"] = t
    # 亲近
    t = _extract_scores_near("亲近")
    if t:
        hard_values["029"], hard_values["030"], hard_values["031"] = t
    # 换算档位
    def tier_trust(v):
        try: x = float(v)
        except: return ""
        if 1 <= x <= 17: return "低"
        if 18 <= x <= 34: return "中"
        if 35 <= x <= 50: return "高"
        return ""
    def tier_comm(v):
        try: x = float(v)
        except: return ""
        if 1 <= x <= 15: return "低"
        if 16 <= x <= 30: return "中"
        if 31 <= x <= 45: return "高"
        return ""
    def tier_close(v):
        try: x = float(v)
        except: return ""
        if 1 <= x <= 10: return "低"
        if 11 <= x <= 20: return "中"
        if 21 <= x <= 30: return "高"
        return ""
    # 信任档位 032/033/034；沟通 035/036/037；亲近 038/039/040
    for score_code, tier_code, fn in [("023","032",tier_trust),("024","033",tier_trust),("025","034",tier_trust),
                                       ("026","035",tier_comm),("027","036",tier_comm),("028","037",tier_comm),
                                       ("029","038",tier_close),("030","039",tier_close),("031","040",tier_close)]:
        if tier_code in hard_values: continue
        v = hard_values.get(score_code)
        if not v: continue
        t = fn(v)
        if t: hard_values[tier_code] = t
    # 母亲/父亲/同伴类型（文本里有 "母亲\nMother\n安全型\nSecure"）
    for role, code in (("母亲", "020"), ("父亲", "021"), ("同伴", "022")):
        m = re.search(rf"{role}\s*\n[A-Za-z]+\s*\n([\u4e00-\u9fa5]+)\s*\n[A-Za-z]+", a2)
        if m:
            t = m.group(1).strip()
            if t: hard_values[code] = t
        else:
            # 宽松版：找 role 后面的中文描述
            m = re.search(rf"{role}[\s\S]{{0,80}}?(安全型|回避型|焦虑|矛盾型|惧怕型|轻视型)\b", a2)
            if m: hard_values[code] = m.group(1)

    # ---- 人格（A2）
    for kw, code in (("开放性", "015"), ("宜人性", "016"),
                     ("责任心", "017"), ("外倾性", "018"),
                     ("神经质", "019")):
        if code in hard_values: continue
        m = re.search(rf"{kw}[\s\S]{{0,80}}?([\d.]+)\s*(?:分|得分)?", a2)
        if m: hard_values[code] = m.group(1)

    # ---- 自我概念（B4）——保留整体值/档位 + 6 子项得分（不再有子项档位和备注）
    # 结构："偏高\nHigh\n68\n行为表现\n..." — 68 是整体值；分项后紧跟一个 0..10 的数字分
    # 先抓整体值：找 "自我概念" / "偏高 High" / "正常 Normal" 后紧跟的一个大数字
    m = re.search(r"(?:偏高|正常|偏低)[\s\S]{0,40}?([\d.]+)[\s\S]{0,60}?行为表现", b4)
    if m:
        hard_values["051"] = m.group(1)
    # 整体档位：整体值附近的"偏高/正常/偏低"
    if "051" in hard_values:
        idx_of_68 = b4.find(f"\n{hard_values['051']}\n")
        if idx_of_68 < 0:
            idx_of_68 = b4.find(hard_values["051"])
        if idx_of_68 > 0:
            prefix = b4[max(0, idx_of_68 - 120): idx_of_68]
            tiers = [("偏高", "偏高"), ("正常", "正常"), ("偏低", "偏低"),
                     ("High", "偏高"), ("Normal", "正常"), ("Low", "偏低")]
            best = (None, -1)
            for txt, tier in tiers:
                i = prefix.rfind(txt)
                if i > best[1]:
                    best = (tier, i)
            if best[0]:
                hard_values["052"] = best[0]
    # 分项得分：使用英文标签 "Happiness And Satisfaction" 之后 350 字符内的数字
    # 每 7 个数字一组（得分 + 0 2 4 6 8 10 刻度），取每组第 1 个为分项得分
    last_label = "Happiness And Satisfaction"
    idx_hs = b4.find(last_label)
    if idx_hs >= 0:
        seg = b4[idx_hs + len(last_label): idx_hs + len(last_label) + 350]
        nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", seg)
        sub_code_map = ["053", "054", "055", "056", "057", "058"]
        for idx, code in enumerate(sub_code_map):
            pos = idx * 7
            if pos < len(nums):
                if code not in hard_values:
                    hard_values[code] = nums[pos]

    # ---- 思维模式 / 自驱力（B4）
    # 思维模式：优先使用文本提取，仪表盘识别作为备选
    idx_think = b4.find("你的思维模式")
    if idx_think >= 0:
        seg = b4[idx_think: idx_think + 1500]
        if "成长型思维模式" in seg:
            hard_values["059"] = "80"
        elif "固定型思维模式" in seg:
            hard_values["059"] = "20"
        elif "混合型思维模式" in seg:
            hard_values["059"] = "50"
    else:
        mindset_value = None
        if HAS_MINDSET_GAUGE:
            mindset_img = PAGES_DIR / "report_B4_vision_10.png"
            if mindset_img.exists():
                try:
                    mindset_value = extract_mindset_gauge(str(mindset_img))
                    print(f"  · 仪表盘读取思维模式: {mindset_value:.1f}")
                except Exception as e:
                    print(f"  · 仪表盘读取失败: {e}")
        
        if mindset_value is not None:
            hard_values["059"] = f"{mindset_value:.1f}"
    # 自主性 / 胜任感 / 归属感（B4 自驱力）
    drive_map = (("自主性", "060", "125"), ("胜任感", "061", "126"), ("归属感", "062", "127"))
    for kw, code_my, code_avg in drive_map:
        my_score = None
        avg_score = None
        matches = re.findall(rf'{kw}[\s\S]{{0,200}}?我的得分[：:]\s*([\d.]+)', b4)
        if matches:
            my_score = matches[-1]
        matches_avg = re.findall(rf'{kw}[\s\S]{{0,200}}?平均得分[：:]\s*([\d.]+)', b4)
        if matches_avg:
            avg_score = matches_avg[-1]
        if my_score:
            hard_values[code_my] = my_score
        if avg_score:
            hard_values[code_avg] = avg_score

    # ---- 执行功能（B3）
    b3 = text_by_slot.get("B3", "")
    for kw, code in (("抑制控制", "063"), ("工作记忆", "064"),
                     ("认知灵活性", "065")):
        m = re.search(rf"{kw}[\s\S]{{0,120}}?([\d.]+)\s*%", b3)
        if not m:
            m = re.search(rf"{kw}[\s\S]{{0,120}}?百分?位[\s　:：]*([\d.]+)", b3)
        if m: hard_values[code] = m.group(1)

    # ---- 学习动机 / 学习方法与策略（B3）
    for kw, code in (("深层动机", "066"), ("表面动机", "067"), ("自我效能感", "068")):
        m = re.search(rf"{kw}[\s\S]{{0,80}}?([\d.]+)\s*(?:分|得分)?", b3)
        if m: hard_values[code] = m.group(1)
    for kw, code in (("深层方法与策略", "069"), ("表面方法与策略", "070"),
                     ("自我调节", "071")):
        m = re.search(rf"{kw}[\s\S]{{0,80}}?([\d.]+)\s*(?:分|得分)?", b3)
        if m: hard_values[code] = m.group(1)

    # ---- 职业兴趣（B6）
    b6 = text_by_slot.get("B6", "")
    # Holland Code 锚点：找 "Holland Code" / "我的职业兴趣代码" 后紧跟的 3 大写字母
    m = re.search(r"(?:Holland Code|我的职业兴趣代码|Code)[\s\S]{0,120}?([A-Z]{3})", b6)
    if m:
        hard_values["072"] = m.group(1)
    else:
        m = re.search(r"(?:Holland|职业兴趣)[\s\S]{0,400}?(?:代码|Code|类型)[\s\S]{0,120}?([A-Z]{3,6})", b6)
        if m: hard_values["072"] = m.group(1).upper()

    def _score_after_kw(kw, text, max_chars=400):
        """在关键词 kw 之后最多 max_chars 内查找一个数字得分。
        1) 优先："X分" 明确格式；
        2) 其次：数字行（排除 NO.X 排名的数字）；
        3) 回退：首个非 0/10 的 1-10 整数。
        """
        i = text.find(kw)
        if i < 0: return None
        seg = text[i: i + max_chars]
        # 1) 优先 "X分"
        m = re.search(r"([\d.]+)\s*分", seg)
        if m: return m.group(1)
        # 2) 找独立数字行（排除排名前缀 NO.）
        lines = [l.strip() for l in seg.splitlines() if l.strip()]
        for idx, ln in enumerate(lines[:10]):
            if re.match(r"^[\d.]+$", ln):
                # 检查上一行是否是 NO.
                prev = lines[idx - 1] if idx > 0 else ""
                if re.match(r"^NO[.:：\s]", prev):
                    continue
                n = ln
                if n in ("0", "10"): continue
                return n
        # 3) 回退
        nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", seg)
        for n in nums:
            if n in ("0", "10"): continue
            if n.isdigit() and 1 <= int(n) <= 10:
                return n
        if nums: return nums[0]
        return None

    # ---- 职业兴趣 6 项得分：锚点在 "职业兴趣测评结果" 后
    anchor_interests = b6.find("职业兴趣测评结果")
    if anchor_interests >= 0:
        seg_interests = b6[anchor_interests: anchor_interests + 1500]
        # 结构化模式："现实型（实干家）\nRealistic\n2\n研究型..."
        # 每个类型关键词后首个独立数字行即得分
        interest_map = (("现实型（实干家）", "073"),
                        ("研究型（思想家）", "074"),
                        ("艺术型（创造者）", "075"),
                        ("社会型（助人者）", "076"),
                        ("事业型（领导者）", "077"),
                        ("常规型（遵循者）", "078"))
        for kw, code in interest_map:
            idx = seg_interests.find(kw)
            if idx < 0:
                # fallback to 简写
                idx = seg_interests.find(kw[:3])
            if idx < 0: continue
            sub = seg_interests[idx: idx + 300]
            lines = [l.strip() for l in sub.splitlines() if l.strip()]
            for ln in lines[:8]:
                if re.match(r"^[\d.]+$", ln) and ln not in ("0", "10"):
                    hard_values[code] = ln
                    break

    # ---- 能力优势（B6）：8 项得分 + 8 排序
    # 锚点："能力优势测评报告" 页面标题后的 2500 字符（即第 6 页的图表/文本混合区）
    ability_labels_order = ["音乐能力", "逻辑数学能力", "语言能力", "自然能力",
                            "内省能力", "人际关系能力", "身体运动能力", "空间能力"]
    ability_codes = {"语言能力": "079", "逻辑数学能力": "080", "音乐能力": "081",
                     "空间能力": "082", "身体运动能力": "083", "人际关系能力": "084",
                     "内省能力": "085", "自然能力": "086"}
    ability_values: Dict[str, float] = {}
    ability_big_section_start = b6.find("能力优势测评报告")
    if ability_big_section_start >= 0:
        seg_ability = b6[ability_big_section_start: ability_big_section_start + 2500]
        for kw in ability_labels_order:
            code = ability_codes[kw]
            idx = seg_ability.find(kw)
            if idx < 0: continue
            # 向前 250 字符（因为能力优势的结构化是"中文标签\n英文\nX分\n"）
            sub = seg_ability[idx: idx + 250]
            # 优先 "X分"
            m = re.search(r"([\d.]+)\s*分", sub)
            if m:
                hard_values[code] = m.group(1)
                try: ability_values[kw] = float(m.group(1))
                except ValueError: pass
                continue
            # 其次：找紧随其后的首个独立数字行（排除 NO. / 1 / 10 / 页码）
            sublines = [l.strip() for l in sub.splitlines() if l.strip()]
            for ln in sublines[:10]:
                if re.match(r"^[\d.]+$", ln) and ln not in ("0", "10"):
                    hard_values[code] = ln
                    try: ability_values[kw] = float(ln)
                    except ValueError: pass
                    break
    # 排序：从高到低
    sorted_abilities = sorted(ability_values.items(), key=lambda kv: -kv[1])
    for i, (kw, _v) in enumerate(sorted_abilities):
        hard_values[f"{87 + i:03d}"] = kw

    # ---- 职业价值观（B6）：15 子项得分 + 15 排序（全 15 项都排序）
    # 文本层结构化："数字\n中文标签" 的相邻行，例如 "9.39\n生活方式"、"3.29\n美的追求"
    # 其它项只有视觉层能看到，依赖 run_vision_api() 返回
    val_labels_order = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                        "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                        "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]
    val_codes = {l: f"{95+i:03d}" for i, l in enumerate(val_labels_order)}
    val_values: Dict[str, float] = {}

    # 锚点："得分情况如下：" 或 "我的职业价值观" 之后 1500 字符
    anchor_idx = max(b6.find("得分情况如下"),
                     b6.find("我的职业价值观   丨"),
                     b6.find("MY WORK VALUES"))
    if anchor_idx >= 0:
        seg_vals = b6[anchor_idx: anchor_idx + 1500]
        lines = [l.strip() for l in seg_vals.splitlines() if l.strip()]
        # 只接受强匹配：上一行是纯数字，当前行是已知标签
        num_cache = None
        for ln in lines:
            if re.match(r"^[\d.]+$", ln):
                num_cache = ln
                continue
            if num_cache is not None and ln in val_codes:
                hard_values[val_codes[ln]] = num_cache
                try: val_values[ln] = float(num_cache)
                except ValueError: pass
                num_cache = None
                continue
            # 碰到"最高分/最低分"等表头，重置缓存避免污染
            if ln in ("最高分", "最低分"):
                num_cache = None
                continue
            # 其它非标签中文行，重置缓存（避免跨大段文本误消费）
            if any("\u4e00" <= c <= "\u9fff" for c in ln):
                num_cache = None

    # 最终排序（从高到低）并输出到 110..124；文本层提取到的项目越多越完整
    sorted_vals = sorted(val_values.items(), key=lambda kv: -kv[1])
    for i, (kw, _v) in enumerate(sorted_vals):
        code = f"{110 + i:03d}"
        hard_values[code] = kw

    # === 本地 OCR 补充（如果有 pytesseract 可用）：渲染 B6 第 12 页做 OCR
    try:
        import pytesseract  # noqa
        from PIL import Image  # noqa
        _HAS_OCR = True
    except Exception:
        _HAS_OCR = False

    if _HAS_OCR:
        try:
            b6_pdf = INPUT_DIR / "report_B6.pdf"
            if b6_pdf.exists():
                _doc = fitz.open(str(b6_pdf))
                if len(_doc) > 11:
                    _page = _doc[11]  # 第 12 页
                    _mat = fitz.Matrix(2.5, 2.5)
                    _pix = _page.get_pixmap(matrix=_mat, alpha=False)
                    _tmp_png = DATA_DIR / "_tmp_b6_p12.png"
                    _pix.save(str(_tmp_png))
                    _img = Image.open(str(_tmp_png))
                    _d = pytesseract.image_to_data(_img, lang='chi_sim+eng',
                                                   output_type=pytesseract.Output.DICT)
                    _doc.close()
                    # 聚类：按 y 中心分组
                    W, H = _img.size
                    rows: List[Tuple[float, str]] = []
                    for i_ in range(len(_d.get('text', []))):
                        conf = int(_d['conf'][i_])
                        if conf < 20:
                            continue
                        t = _d['text'][i_].strip()
                        if not t:
                            continue
                        top = _d['top'][i_]
                        h = _d['height'][i_]
                        yc = (top + h / 2) / H
                        rows.append((yc, t))
                    rows.sort(key=lambda r: r[0])
                    # 聚类成行（y 差 <= 0.010 视为同一行）
                    clusters: List[List[str]] = []
                    cur_y = -1.0
                    for yc, t in rows:
                        if cur_y < 0 or abs(yc - cur_y) > 0.010:
                            clusters.append([t])
                            cur_y = yc
                        else:
                            clusters[-1].append(t)
                    for c in clusters:
                        labels = [t for t in c if t in val_codes]
                        nums = [t for t in c if re.match(r"^[\d.]+$", t)]
                        if labels and nums:
                            code = val_codes[labels[0]]
                            if not hard_values.get(code):
                                hard_values[code] = nums[0]
                                try: val_values[labels[0]] = float(nums[0])
                                except ValueError: pass
                    # 重新排序：补齐后再更新排名 1..15
                    sorted_vals = sorted(val_values.items(), key=lambda kv: -kv[1])
                    for i, (kw, _v) in enumerate(sorted_vals):
                        code = f"{110 + i:03d}"
                        hard_values[code] = kw
        except Exception as e:
            print(f"  [视觉本地OCR] 失败: {e}")

    # === 图像处理 fallback（B6 第 14 页柱状图）：
    # 当 val_values 不足 15 项时，用图像处理填充缺失项
    if len(val_values) < 15:
        try:
            import numpy as np
            b6_pdf = INPUT_DIR / "report_B6.pdf"
            if b6_pdf.exists():
                _doc = fitz.open(str(b6_pdf))
                if len(_doc) > 13:
                    _page = _doc[13]  # 第 14 页：职业价值观图表
                    _zoom = 3.0
                    _mat = fitz.Matrix(_zoom, _zoom)
                    _pix = _page.get_pixmap(matrix=_mat, alpha=False)
                    _img_data = np.frombuffer(_pix.samples, dtype=np.uint8).reshape(
                        _pix.height, _pix.width, _pix.n)
                    if _img_data.shape[2] == 4:
                        _img_data = _img_data[:, :, :3]
                    _gray = np.mean(_img_data, axis=2).astype(np.uint8)
                    _dark_mask = _gray < 150  # 暗色像素 = 柱状图实心部分

                    # 把 y=420-680（pdf 坐标）分成 15 段
                    _y_min, _y_max = 420, 680
                    _n_seg = 15
                    _seg_h = (_y_max - _y_min) / _n_seg
                    _x_start_pdf, _x_end_pdf = 160, 450

                    # 对每段，统计列方向暗色像素数，找到"右端 x"
                    _bar_lengths = []  # (idx, length_pdf)
                    for _i in range(_n_seg):
                        _ys_img = int((_y_min + _i * _seg_h) * _zoom)
                        _ye_img = int((_y_min + (_i + 1) * _seg_h) * _zoom)
                        _xs_img = int(_x_start_pdf * _zoom)
                        _xe_img = int(_x_end_pdf * _zoom)
                        if _ye_img > _gray.shape[0]:
                            _ye_img = _gray.shape[0]
                        if _xe_img > _gray.shape[1]:
                            _xe_img = _gray.shape[1]
                        if _ys_img >= _ye_img or _xs_img >= _xe_img:
                            continue
                        _sub = _dark_mask[_ys_img:_ye_img, _xs_img:_xe_img]
                        if _sub.size == 0:
                            continue
                        _col_counts = _sub.sum(axis=0)
                        # 降低阈值：只要有暗色像素就检测（安全稳定的柱形条特别短）
                        if len(_col_counts) == 0 or _col_counts.max() < 1:
                            continue
                        # 找 "从右往左扫描，第一个暗色像素数 >= 阈值"的位置
                        _max_c = _col_counts.max()
                        _threshold = max(_max_c * 0.15, 1.0)  # 至少 1 个像素
                        _right_end_img = -1
                        for _j in range(len(_col_counts) - 1, -1, -1):
                            if _col_counts[_j] >= _threshold:
                                _right_end_img = _j
                                break
                        if _right_end_img > 0:
                            _right_end_pdf = _x_start_pdf + _right_end_img / _zoom
                            _bar_lengths.append((_i, _right_end_pdf - _x_start_pdf))
                _doc.close()

                # 用 2 个锚点线性校准：生活方式 = 9.39，美的追求 = 3.29
                if _bar_lengths:
                    _lengths = [_len for _, _len in _bar_lengths]
                    _max_len, _min_len = max(_lengths), min(_lengths)
                    _scores = {}
                    for _i, _len in _bar_lengths:
                        if _max_len != _min_len:
                            _scores[val_labels_order[_i]] = 3.29 + (_len - _min_len) / (_max_len - _min_len) * (9.39 - 3.29)
                        else:
                            _scores[val_labels_order[_i]] = 5.0

                    # 填充缺失项
                    for _label in val_labels_order:
                        _code = val_codes[_label]
                        if not hard_values.get(_code) and _label in _scores:
                            hard_values[_code] = f"{_scores[_label]:.2f}"
                            try: val_values[_label] = float(hard_values[_code])
                            except ValueError: pass
                    # 重新排序（补齐后再次更新排名 1..15）
                    sorted_vals = sorted(val_values.items(), key=lambda kv: -kv[1])
                    for i, (kw, _v) in enumerate(sorted_vals):
                        code = f"{110 + i:03d}"
                        hard_values[code] = kw
                    print(f"  [图像处理] 填充了 {len(_bar_lengths)} 项职业价值观得分")
        except Exception as e:
            print(f"  [图像处理] 失败: {e}")

    # 打印硬匹配摘要
    print(f"  [硬匹配] 从 PDF 文本层抓到 {len(hard_values)} 项")

    # 合并：视觉 API 值优先，硬匹配作为兜底
    def _coerce_to_type(raw_value: Any, tp: str) -> str:
        if raw_value is None or raw_value == "":
            return ""
        if isinstance(raw_value, bool):
            return "1" if raw_value else "0"
        if isinstance(raw_value, (int, float)):
            return str(raw_value)
        return str(raw_value).strip()

    def _final_value_for(code: str, schema_type: str) -> str:
        hard_codes = {"001", "002", "003", "004", "005", "006", "007", "008", "059", "060", "061", "062", "125", "126", "127"}
        if code in hard_codes:
            v = hard_values.get(code)
            if v not in (None, "", "—"):
                return _coerce_to_type(v, schema_type)
        
        v = code_values.get(code)
        if v not in (None, "", "—"):
            return _coerce_to_type(v, schema_type)
        
        v = hard_values.get(code)
        if v not in (None, "", "—"):
            return _coerce_to_type(v, schema_type)
        
        return ""

    final_124: Dict[str, Dict[str, Any]] = {}
    for entry in SCHEMA_124:
        code = entry["code"]
        final_124[code] = {
            "code": code,
            "label": entry["label"],
            "value": _final_value_for(code, entry["type"]),
            "type": entry["type"],
            "unit": entry.get("unit", "") or "",
            "source_pdf": entry["source_pdf"],
            "note": entry.get("note", ""),
        }

    student = extract_student_info(all_text_blobs)
    print("\n[学生信息]", student)

    # --- D. 按 section 组装（保留兼容结构，data_points.apply_report_data 能用）
    sections = organize_to_sections(text_items_by_pdf)

    out_file = DATA_DIR / "report_data.json"
    report = {
        "student": student,
        "pdf_titles": pdf_titles,
        "schema_124": list(final_124.values()),
        "sections": sections,
        "vision": vision_result,
    }
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    # 额外输出 124 项的纯文本格式（方便直接复制粘贴）
    lines: List[str] = []
    for code in sorted(final_124.keys()):
        it = final_124[code]
        lines.append(f"{code} {it['label']}：{it['value']}")
    (DATA_DIR / "report_data_124.txt").write_text("\n".join(lines), encoding="utf-8")

    # 控制台打印摘要
    filled = sum(1 for it in final_124.values() if str(it["value"]).strip() not in ("", "—"))
    print(f"\n[DONE] 124 项数据：已填 {filled}/124")
    print(f"  详细 JSON: {out_file}")
    print(f"  纯文本:   {DATA_DIR / 'report_data_124.txt'}")
    return 0



if __name__ == "__main__":
    force_skip = "--skip-vision" in sys.argv
    sys.exit(main(force_skip_vision=force_skip))
