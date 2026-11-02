"""AI 写作与事实核对的共用模块（W1）。

所有会写文字的 AI 功能共用这里的写作/准确性要求和核对工具：

* ``rules_block()``：放进提示词的两段规则（不含任何示例事实）。
* ``lint_facts`` / ``lint_style`` / ``pronoun_problem``：不用 AI 的代码检查。
* ``verify_blocks``：另一次 AI 调用，只判断，不改写。
* ``run_guard``：检查 → 重写一次 → 再检查；仍不合格的变成需要人工核对的标记。

本模块不导入 Flask 或数据库。检查失败（超时、返回格式不对）绝不能看起来像
通过：``verify_blocks`` 会抛 :class:`VerifyError`，``run_guard`` 则把相应内容
记为 ``未核对``，``status`` 为 ``partial`` 或 ``skipped``。
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional

WRITING_RULES = """写作要求：像一位细心的同事写的记录，平实、准确，不带个人色彩。
1. 先写发生了什么：在什么情境下，谁做了什么、说了什么，后来怎样。用资料里的具体细节，不用抽象概括代替。
2. 用日常书面语。不要写“展现出……能力”“体现了……意识”“具备……基础”这类空泛判断，也不要堆砌专业名词。
3. 句子长短自然，不重复同一句式，不要每句都用同一个词开头，不要套用固定模板。
4. 不抒情，不夸奖，不下人格评价，不用比喻、感叹和反问，不用第一人称。
5. 事实和推断分开写。推断单独成句，只用资料支持的程度，并用“可能”“看起来”“还需要了解”这类说法。
6. 写完整的句子。不要写成用分号连接的短语清单。"""

ACCURACY_RULES = """准确性要求（最重要，高于所有写作要求）：
1. 只写资料里有的内容。资料没有写到的，不补充时间、地点、人物、次数、频率、原因、感受和结果。
2. 不把一次经历写成长期规律。“经常”“总是”“反复”“一直”必须有资料明确支持。
3. 分清谁说的。导师的提问、解释和推测不是学生的想法；学生附和引导性提问，不算学生自己的看法；学生后来更正的，以更正后的说法为准，并保留这个变化。
4. 假设性回答不是实际行为，他人的推测不是事实。
5. 引号里只放原文，一字不改；不是原话不加引号。
6. 不根据姓名猜测性别。资料未写明性别时，不用“他”“她”指代学生。
7. 资料不足时直接说明还不清楚，不要为了写满而推测。宁可少写，不能写错。"""

FACT_CHECK_PROMPT = """你是事实核对员。只判断，不改写，不补充。
逐句检查【文字】中的每一句话。每一句都要依次回答五个问题：
1. 这件事资料里有吗？时间、地点、人物、次数、原因、感受、结果都要对得上。人物要对上：做这件事的人和对象，必须是资料里同一件事中的人；不能把两件事里的人或情节对调、合并。
2. 是谁说的？资料中标为“导师”或“老师”的话，以及学生对引导性提问的简单附和（如“可能吧”“嗯”“对”），都不能写成学生自己的想法。
3. 真的发生了吗？回答“如果……会怎样”的内容是设想，不是实际行为；别人的猜测不是事实；资料标明【设想】的内容没有发生。
4. 是一次还是经常？资料只写了一次的事，不能写成习惯、规律或“经常”。
5. 前后和起因对吗？句中写的“在……之后”“当……时”“因为……”“于是”这类连接，资料里必须有；资料没有把两件事连在一起的，不能连在一起写。
五个问题都没问题才算 supported。
- supported：资料明确写到，或是忠实的转述。
- partly：大部分有依据，但多了资料没有的细节。
- unsupported：任何一个问题不通过，或与资料矛盾。
带“可能”“还需要了解”的推断句：所依据的事实在资料中，就算 supported。
纯建议、纯提问、固定标签不是事实陈述，算 supported。
只输出 JSON：{"sentences":[{"text":"原句","verdict":"supported","problem":""}]}
【文字】
%s
【资料】
%s"""

REWRITE_PROMPT = """下面这段文字有几处没有资料依据。请只删除或改正这些地方，不增加任何新内容，其他部分尽量不动。
第一人称的内容改成第三人称转述。
改完如果信息很少也没关系，不要补充。只输出 JSON：{"text":""}
【文字】
%s
【问题】
%s
【资料】
%s"""

_VERDICTS = ("supported", "partly", "unsupported")


class VerifyError(RuntimeError):
    """事实核对没能完成（调用失败或返回格式不对）。不能当作通过。"""


def rules_block() -> str:
    """ACCURACY_RULES 在前，WRITING_RULES 在后，供放进提示词。"""
    return ACCURACY_RULES + "\n\n" + WRITING_RULES


# ---------------------------------------------------------------------------
# 文本归一化
# ---------------------------------------------------------------------------
def _nfkc(text) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _norm(text) -> str:
    """去掉空白和标点后比较。"""
    return "".join(ch for ch in _nfkc(text)
                   if not ch.isspace() and unicodedata.category(ch)[0] not in "PS")


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_CLASS = "零一二两三四五六七八九十百"


def _cn_values(numeral: str) -> List[int]:
    """中文数字 → 数值列表。“三四次”这类连写按两个数分别返回。"""
    if not numeral or any(ch not in _CN_CLASS for ch in numeral):
        return []
    if "十" not in numeral and "百" not in numeral:
        return [_CN_DIGITS[ch] for ch in numeral]
    value = 0
    current = 0
    for ch in numeral:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch == "十":
            value += (current or 1) * 10
            current = 0
        elif ch == "百":
            value += (current or 1) * 100
            current = 0
    return [value + current]


_MEASURES = "个月|分钟|小时|点|次|遍|天|周|年|岁|分|句|条|张|节|门|位|名|页|道|个|人"
_CN_MEASURE_RE = re.compile(r"([%s]+)(%s)" % (_CN_CLASS, _MEASURES))
_AR_MEASURE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%s)" % _MEASURES)
_AR_RE = re.compile(r"\d+(?:\.\d+)?")
_RCODE_RE = re.compile(r"[Rr]\d+(?:\.\d+)*")
_ID_RE = re.compile(r"(?:y4|y|src|ft|q|6am|ev)-\d+(?:-\d+)?")
_LABEL_NUM_RE = re.compile(r"(?:情境|事件|环节)\s*\d+")  # 版式里的编号，不是事实
_LIST_MARK_RE = re.compile(r"(?m)^\s*\d+\s*[.、)）]\s*")
_TIME_MARK_RE = re.compile(r"\[?\b\d{1,2}:\d{2}(?::\d{2})?\]?")  # 转录稿的时间戳，不是事实
_FIXED_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:Y4|R4|E4|M1|6\s*A\.?\s*M\.?)(?![A-Za-z0-9])")
_ISO_RE = re.compile(r"((?:19|20)\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?")
_CN_DATE_RE = re.compile(r"([零一二两三四五六七八九十]{1,3})\s*(月|日|号)")


def _arabize_dates(text: str) -> str:
    """“十月”“三号”改写成“10月”“3号”，便于和阿拉伯数字比较。"""
    def repl(match):
        values = _cn_values(match.group(1))
        return "%d%s" % (values[0], match.group(2)) if len(values) == 1 else match.group(0)
    return _CN_DATE_RE.sub(repl, text)


def _prepare(text: str) -> str:
    return _arabize_dates(_nfkc(text))


def _expand_iso(text: str) -> str:
    """把 2026-10-12 之类展开成中文写法，供时间核对使用。"""
    extra = []
    for match in _ISO_RE.finditer(text):
        year, month, day = match.group(1), int(match.group(2)), match.group(3)
        extra.append("%s年%d月" % (year, month))
        extra.append("%s年" % year)
        extra.append("%d月" % month)
        if day:
            extra.append("%d月%d日" % (month, int(day)))
            extra.append("%d日" % int(day))
    return " ".join(extra)


def _strip_ignored(text: str, ignore: Iterable[str]) -> str:
    for label in sorted({str(x) for x in ignore or () if str(x).strip()}, key=len, reverse=True):
        text = text.replace(label, " ")
    return text


# ---------------------------------------------------------------------------
# lint_facts
# ---------------------------------------------------------------------------
_PERSON_GROUPS = (
    ("妈妈", "母亲"), ("爸爸", "父亲"), ("外婆",), ("外公",), ("奶奶",), ("爷爷",),
    ("姐姐",), ("妹妹",), ("哥哥",), ("弟弟",), ("同桌",), ("班主任",), ("教练",),
    ("医生",), ("叔叔",), ("阿姨",), ("舅舅",), ("舅妈",), ("姑姑",), ("姨妈",),
    ("校长",), ("家教",), ("室友",),
)
_TIME_WORDS = ("上周", "上个月", "上学期", "去年", "今年", "昨天", "前几天",
               "期中", "期末", "寒假", "暑假", "前天", "后天", "明天", "下周",
               "下个月", "下学期", "明年")
_INTENSITY_WORDS = ("极度", "极其", "非常", "特别", "严重", "显著", "明显", "强烈",
                    "剧烈", "一直", "总是", "经常", "常常", "反复", "多次", "长期",
                    "每次", "每天", "从不", "从来", "始终", "频繁", "习惯",
                    "频率", "持续性", "毫无", "几乎", "完全", "根本")
_CONCLUSION_WORDS = ("说明", "表明", "证明", "反映", "体现", "具备", "机制")
_HEDGE_WORDS = ("可能", "看起来", "也许", "提示", "还需要", "尚不清楚")
_CONCLUSION_SKIP_WORDS = ("是否", "需确认", "需要确认", "尚不清楚", "还需要")
_WEEKDAY_RE = re.compile(r"(?:周|星期)([一二三四五六日天])")
_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*(月|日|号)")
_YEAR_RE = re.compile(r"((?:19|20)\d{2})\s*年")
_QUOTE_RE = re.compile("“([^”]+)”|\"([^\"]+)\"|「([^」]+)」|『([^』]+)』|‘([^’]+)’")


def _number_facts(text: str, source: str) -> List[str]:
    def clean(value: str) -> str:
        value = _RCODE_RE.sub(" ", _LABEL_NUM_RE.sub(" ", _LIST_MARK_RE.sub("", value)))
        return _ID_RE.sub(" ", _FIXED_TOKEN_RE.sub(" ", value))

    text_clean = clean(text)
    source_clean = clean(source)

    source_pairs = set()
    source_values = set()
    for match in _CN_MEASURE_RE.finditer(source_clean):
        for value in _cn_values(match.group(1)):
            source_pairs.add((float(value), match.group(2)))
            source_values.add(float(value))
    for match in _AR_MEASURE_RE.finditer(source_clean):
        source_pairs.add((float(match.group(1)), match.group(2)))
    for match in _AR_RE.finditer(source_clean):
        source_values.add(float(match.group(0)))
    source_norm = _norm(source)

    found: List[str] = []
    for match in _CN_MEASURE_RE.finditer(text_clean):
        numeral, measure = match.group(1), match.group(2)
        if numeral == "十" and measure == "分":
            continue  # “十分紧张”的“十分”是程度副词
        values = _cn_values(numeral)
        if not values:
            continue
        if _norm(match.group(0)) in source_norm:
            continue
        if all((float(value), measure) in source_pairs for value in values):
            continue
        found.append(match.group(0))

    # 阿拉伯数字：日期/年月交给 time 检查
    for match in _AR_RE.finditer(text_clean):
        start, end = match.span()
        tail = text_clean[end:end + 3].lstrip()
        head = text_clean[max(0, start - 1):start]
        if tail[:1] in ("月", "日", "号") or tail.startswith("年"):
            continue
        if head in ("-", "/") or text_clean[end:end + 1] in ("-", "/") and \
                re.match(r"\d", text_clean[end + 1:end + 2] or ""):
            continue  # 日期的一部分
        measure = _AR_MEASURE_RE.match(text_clean, start)
        value = float(match.group(0))
        if measure:
            if (float(measure.group(1)), measure.group(2)) in source_pairs:
                continue
            if value in source_values and _norm(measure.group(0)) in source_norm:
                continue
            found.append(measure.group(0).replace(" ", ""))
            continue
        if value in source_values:
            continue
        found.append(match.group(0))
    return found


def _time_facts(text: str, source: str) -> List[str]:
    text = _prepare(text)
    source_all = _prepare(source)
    source_all = source_all + " " + _expand_iso(source_all)
    source_norm = _norm(source_all).replace("星期", "周").replace("号", "日")
    found: List[str] = []

    def absent(value: str) -> bool:
        probe = _norm(value).replace("星期", "周").replace("号", "日")
        return probe not in source_norm

    for match in _ISO_RE.finditer(text):
        year, month, day = match.group(1), int(match.group(2)), match.group(3)
        pieces = ["%s年" % year, "%d月" % month]
        if day:
            pieces.append("%d日" % int(day))
        if any(absent(piece) for piece in pieces) and match.group(0) not in found:
            found.append(match.group(0))
    stripped = _ISO_RE.sub(" ", text)
    for match in _YEAR_RE.finditer(stripped):
        if absent(match.group(1) + "年"):
            found.append(match.group(0).replace(" ", ""))
    for match in _MONTH_DAY_RE.finditer(stripped):
        if absent(match.group(1) + match.group(2)):
            found.append(match.group(0).replace(" ", ""))
    for match in _WEEKDAY_RE.finditer(stripped):
        if absent(match.group(0)):
            found.append(match.group(0))
    for word in _TIME_WORDS:
        if word in stripped and absent(word):
            found.append(word)
    return found


def _person_facts(text: str, source: str) -> List[str]:
    source_norm = _norm(source)
    found = []
    for group in _PERSON_GROUPS:
        for word in group:
            if word in text and not any(member in source_norm for member in group):
                found.append(word)
    return found


def _intensity_facts(text: str, source: str) -> List[str]:
    """程度或频率的词：资料里没有就是夸大，或把一次写成习惯。"""
    return [word for word in _INTENSITY_WORDS if word in text and word not in source]


def _conclusion_facts(text: str) -> List[str]:
    """下了结论、却没有留出推断余地的句子。"""
    found = []
    for piece in _sentences(text):
        # “几何证明”是学科名称，不是结论
        probe = piece.replace("几何证明", "")
        if any(word in probe for word in _CONCLUSION_SKIP_WORDS):
            continue  # 开放的问题、待确认的说法，不是结论
        if any(word in probe for word in _CONCLUSION_WORDS) and \
                not any(word in probe for word in _HEDGE_WORDS):
            found.append(piece)
    return found


_MENTOR_LINE_RE = re.compile(
    r"^\W*(?:\d{1,2}:\d{2}(?::\d{2})?\W*)?(导师|老师|mentor)\s*"
    r"(?:\d{1,2}:\d{2}(?::\d{2})?\s*)?[：:]", re.IGNORECASE)
_STUDENT_LINE_RE = re.compile(
    r"^\W*(?:\d{1,2}:\d{2}(?::\d{2})?\W*)?学生\s*"
    r"(?:\d{1,2}:\d{2}(?::\d{2})?\s*)?[：:]", re.IGNORECASE)
# 导师自己的看法：导师复述学生的话不算
_MENTOR_VIEW_WORDS = ("我觉得", "我听到", "说明", "是不是")
_OBSERVER_RE = re.compile(
    r"(老师|家长|母亲|父亲|妈妈|爸爸|同学)(观察到|发现|看到|注意到|指出|反馈)")
_OBSERVER_EVIDENCE_WORDS = ("观察", "看到", "发现", "注意", "反馈", "亲眼", "补充", "填写")
_PARENT_WORDS = ("家长", "妈妈", "母亲", "爸爸", "父亲")
_Y4_SPEECH_RE = re.compile(
    r"学生(表示|认为|说|提到|承认|觉得)[^。；]{0,24}(得分|档位|评级|测评|Y4)")


def _shared_run(probe: str, lines: List[str], minimum: int = 5,
                limit: int = 60) -> str:
    """``probe`` 与 ``lines`` 中任意一行共有的最长连续片段（至少 ``minimum`` 个字）。"""
    for size in range(min(len(probe), limit), minimum - 1, -1):
        for start in range(len(probe) - size + 1):
            run = probe[start:start + size]
            if any(run in line for line in lines):
                return run
    return ""


def _speaker_facts(text: str, source: str) -> List[str]:
    """把导师的原话写成学生的想法。只在资料里有导师自己的看法时检查。"""
    lines = str(source or "").splitlines()
    # 导师常复述学生的话，只有导师自己的看法才不能写成学生的
    mentor = [_norm(line) for line in lines if _MENTOR_LINE_RE.match(line)
              and any(word in line for word in _MENTOR_VIEW_WORDS)]
    if not mentor:
        return []
    student = [_norm(line) for line in lines if _STUDENT_LINE_RE.match(line)]
    found = []
    for piece in _sentences(text):
        if "导师" in piece or "老师" in piece:
            continue
        probe = _norm(piece)
        if not probe:
            continue
        run = _shared_run(probe, mentor)
        if run and not any(run in line for line in student):
            found.append(piece)
    return found


def _observer_facts(text: str, source: str) -> List[str]:
    """资料里没有旁人观察/看到/发现，就别写成旁人说的。"""
    lines = [line for line in str(source or "").splitlines() if line.strip()]
    found = []
    for match in _OBSERVER_RE.finditer(text):
        person = match.group(1)
        people = _PARENT_WORDS if person in _PARENT_WORDS else (person,)
        if any(any(who in line for who in people) and
               any(word in line for word in _OBSERVER_EVIDENCE_WORDS)
               for line in lines):
            continue
        found.append(match.group(0))
    return found


def _y4_as_speech_facts(text: str) -> List[str]:
    """学生不会自己报告测评得分或档位。"""
    return [match.group(0) for match in _Y4_SPEECH_RE.finditer(text)]


def _first_person_facts(text: str, source: str) -> List[str]:
    """引号外出现“我”，除非这一句本身是资料里的原句。"""
    body = _outside_quotes(text)
    lines = {_norm(line) for line in str(source or "").splitlines() if line.strip()}
    found = []
    for piece in _sentences(body):
        if "我" not in piece.replace("自我", ""):
            continue
        probe = _norm(piece)
        if probe and probe in lines:
            continue  # 整句就是资料里的原句
        found.append(piece)
    return found


def _quote_facts(text: str, source: str, ignore: Iterable[str]) -> List[str]:
    source_norm = _norm(source)
    labels = {_norm(x) for x in ignore or () if str(x).strip()}
    found = []
    for match in _QUOTE_RE.finditer(text):
        inner = next(group for group in match.groups() if group is not None)
        probe = _norm(inner)
        if not probe or probe in labels:
            continue
        if probe not in source_norm:
            found.append(inner)
    return found


def lint_facts(text: str, source: str, ignore: Iterable[str] = ()) -> List[Dict[str, str]]:
    """文字里出现、资料里没有的数字、时间、人物和引文。

    ``ignore`` 是调用方列出的固定标签（来源名、档位词等），先从文字里去掉再查，
    引文检查也会跳过这些标签。宁可多报：误报只多一次重写。
    """
    text = _nfkc(text)
    # 转录稿的时间戳不能给数字、时间当依据：“12点”不能因为 [00:12:05] 就通过
    source = _TIME_MARK_RE.sub(" ", _nfkc(source))
    bare = _strip_ignored(text, ignore)
    out: List[Dict[str, str]] = []
    seen = set()

    def add(kind: str, values: Iterable[str]) -> None:
        for value in values:
            if (kind, value) not in seen:
                seen.add((kind, value))
                out.append({"kind": kind, "value": value})

    add("number", _number_facts(bare, source))
    add("time", _time_facts(bare, source))
    add("person", _person_facts(bare, source))
    add("intensity", _intensity_facts(bare, source))
    add("conclusion", _conclusion_facts(text))
    add("speaker", _speaker_facts(text, source))
    add("observer", _observer_facts(bare, source))
    add("y4_as_speech", _y4_as_speech_facts(bare))
    add("first_person", _first_person_facts(text, source))
    add("quote", _quote_facts(text, source, ignore))
    return out


# ---------------------------------------------------------------------------
# lint_style / pronoun_problem
# ---------------------------------------------------------------------------
_STYLE_PHRASES = ("展现出", "体现出", "彰显", "值得注意的是", "总体而言", "综上所述",
                  "不难看出", "由此可见", "令人欣慰", "难能可贵", "重建控制感",
                  "内在动机")
_STYLE_REGEXES = (re.compile(r"具备.{0,12}?能力"), re.compile(r"具备.{0,12}?意识"))


def lint_style(text: str) -> List[str]:
    """文字里出现的套话。只提示，不阻止任何事。"""
    text = str(text or "")
    found = [phrase for phrase in _STYLE_PHRASES if phrase in text]
    for pattern in _STYLE_REGEXES:
        match = pattern.search(text)
        if match:
            found.append(match.group(0))
    return found


_PRONOUN_RE = re.compile(r"(?<![其另])([他她])(?![人们乡处日])")
# 逗号后接着说的“他”“她”，指的是同句里提到的旁人，不是学生
_ROLE_PRONOUN_RE = re.compile(
    r"(父亲|爸爸|母亲|妈妈|同学|朋友|老师|同桌|外婆|外公|奶奶|爷爷)[^。；！？]{0,20}，(他|她)")
_MALE = {"男", "男生", "male", "m", "boy"}
_FEMALE = {"女", "女生", "female", "f", "girl"}


def _outside_quotes(text: str) -> str:
    return _QUOTE_RE.sub(" ", str(text or ""))


def pronoun_problem(text: str, gender: str) -> bool:
    """性别未填写时用了“他”“她”，或与已填写的性别相反。引号里的原话不查。"""
    body = _ROLE_PRONOUN_RE.sub(" ", _outside_quotes(text))
    pronouns = {match.group(1) for match in _PRONOUN_RE.finditer(body)}
    if not pronouns:
        return False
    value = str(gender or "").strip().lower()
    if value in _MALE:
        return "她" in pronouns
    if value in _FEMALE:
        return "他" in pronouns
    return True


# ---------------------------------------------------------------------------
# 调用 / 解析
# ---------------------------------------------------------------------------
def _default_call() -> Callable[[str], Any]:
    from growth_talk.analysis import call_model  # 延迟导入，避免循环依赖
    return call_model


def _ask(call: Callable[[str], Any], prompt: str) -> Dict[str, Any]:
    try:
        result = call(prompt)
        if isinstance(result, str):
            result = json.loads(result)
    except Exception as exc:  # 超时、网络、格式错误都算核对没完成
        raise VerifyError("核对调用失败：%s" % exc.__class__.__name__) from exc
    if not isinstance(result, dict):
        raise VerifyError("核对返回格式无效")
    return result


_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")


def _sentences(text: str) -> List[str]:
    return [piece.strip() for piece in _SPLIT_RE.split(str(text or "")) if piece.strip()]


def _bigrams(text: str) -> set:
    norm = _norm(text)
    return {norm[i:i + 2] for i in range(len(norm) - 1)} or ({norm} if norm else set())


def _covered(group: List[Dict[str, Any]], returned: List[str]) -> bool:
    """返回的逐句结果是否覆盖了每一句（防止核对员漏句后被当成通过）。"""
    pool = set()
    joined = "|".join(_norm(x) for x in returned)
    for item in returned:
        pool |= _bigrams(item)
    for block in group:
        for piece in _sentences(block["text"]):
            norm = _norm(piece)
            if len(norm) < 4 or norm in joined:
                continue
            grams = _bigrams(piece)
            if grams and len(grams & pool) / len(grams) < 0.8:
                return False
    return True


def _verify_group(call: Callable[[str], Any],
                  group: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    source = group[0]["source"]
    text = "\n".join(block["text"] for block in group)
    prompt = FACT_CHECK_PROMPT % (text, source)
    sentences: List[Dict[str, Any]] = []
    for attempt in range(2):
        answer = _ask(call, prompt)
        rows = answer.get("sentences")
        if isinstance(rows, list) and all(
                isinstance(row, dict) and isinstance(row.get("text"), str)
                and row.get("verdict") in _VERDICTS for row in rows):
            sentences = rows
            if _covered(group, [row["text"] for row in rows]):
                break
        if attempt:
            raise VerifyError("核对结果不完整")
    problems: List[Dict[str, str]] = []
    for row in sentences:
        if row["verdict"] == "supported":
            continue
        norm = _norm(row["text"])
        owners = [b for b in group if norm and norm in _norm(b["text"])] \
            or [b for b in group if norm and _norm(b["text"]) in norm] or group
        for block in owners:
            problems.append({"id": block["id"], "sentence": row["text"].strip(),
                             "verdict": row["verdict"],
                             "problem": str(row.get("problem") or "").strip()})
    return problems


def verify_blocks(blocks: List[Dict[str, Any]], call: Optional[Callable] = None) -> List[Dict[str, str]]:
    """另一次 AI 调用核对每句话。资料相同的块合并成一次调用。

    返回 ``[{"id","sentence","verdict": "partly"|"unsupported","problem"}]``。
    调用失败或返回不完整时抛 :class:`VerifyError`，不会返回“空列表”冒充通过。
    """
    call = call or _default_call()
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for block in blocks:
        if str(block.get("text") or "").strip():
            groups.setdefault(str(block.get("source") or ""), []).append(block)
    problems: List[Dict[str, str]] = []
    for source, group in groups.items():
        if not source.strip():
            raise VerifyError("缺少核对用的资料")
        problems.extend(_verify_group(call, group))
    return problems


# ---------------------------------------------------------------------------
# run_guard
# ---------------------------------------------------------------------------
_KIND_LABEL = {"number": "数字", "time": "时间", "person": "人物", "quote": "引文",
               "intensity": "程度或频率", "conclusion": "没有依据的结论",
               "speaker": "可能把导师的话当成学生的",
               "observer": "旁人没有看到的观察",
               "y4_as_speech": "学生自述测评结果",
               "first_person": "第一人称"}
_KIND_PROBLEM = {"conclusion": "这句话下了结论，资料里没有依据",
                 "speaker": "这句话可能把导师的话当成学生说的",
                 "observer": "资料里没有老师或家长看到这件事，这里像是把学生的说法写成了旁人的观察",
                 "y4_as_speech": "学生不会自己报告测评得分或档位",
                 "first_person": "出现了第一人称，应改成第三人称转述"}


def _sentence_with(text: str, value: str) -> str:
    probe = _norm(value)
    for piece in _sentences(text):
        if probe and probe in _norm(piece):
            return piece
    return _sentences(text)[0] if _sentences(text) else str(text).strip()


def _excerpt(sentence: str, source: str, limit: int = 200) -> str:
    """资料中与该句重合最多的一段，供人工核对时对照。"""
    grams = _bigrams(sentence)
    best, best_score = "", -1
    for piece in re.split(r"\n+", str(source or "")):
        piece = piece.strip()
        if not piece:
            continue
        score = len(grams & _bigrams(piece))
        if score > best_score:
            best, best_score = piece, score
    return best[:limit]


def _local_problems(block: Dict[str, Any], gender: Optional[str],
                    ignore: Iterable[str]) -> List[Dict[str, str]]:
    text = block["text"]
    out = []
    for item in lint_facts(text, block["source"], ignore=ignore):
        problem = _KIND_PROBLEM.get(item["kind"]) or \
            "%s“%s”在资料中找不到" % (_KIND_LABEL[item["kind"]], item["value"])
        out.append({"kind": item["kind"], "sentence": _sentence_with(text, item["value"]),
                    "problem": problem})
    if gender is not None and pronoun_problem(text, gender):
        match = _PRONOUN_RE.search(_outside_quotes(text))
        out.append({"kind": "pronoun",
                    "sentence": _sentence_with(text, match.group(1)) if match else text.strip(),
                    "problem": "资料未写明性别，不应用“他”“她”指代学生"
                    if not str(gender).strip() else "“他”“她”与资料中的性别不符"})
    return out


def _problem_text(problems: List[Dict[str, str]]) -> str:
    return "\n".join("- %s：%s" % (p["sentence"], p["problem"] or "资料中找不到依据")
                     for p in problems)


def run_guard(blocks: List[Dict[str, Any]], call: Optional[Callable] = None,
              budget_seconds: Optional[float] = None, gender: Optional[str] = None,
              ignore: Iterable[str] = (), workers: int = 4) -> Dict[str, Any]:
    """检查每个块；不合格的重写一次再检查；仍不合格的成为标记。

    ``blocks``: ``[{"id","text","source"}]``。返回
    ``{"blocks": {id: 最终文字}, "flags": [...], "status": "checked"|"partial"|"skipped"}``。
    绝不删除整块文字，绝不抛异常：核对没完成的内容记为未核对，
    ``status`` 为 ``partial``（部分完成或超出时间预算）或 ``skipped``（全部没完成）。
    ``gender`` 不为 None 时，同时检查“他”“她”。
    """
    final = {str(b.get("id")): str(b.get("text") or "") for b in blocks if isinstance(b, dict)}
    flags: List[Dict[str, str]] = []
    try:
        return _run_guard(blocks, call, budget_seconds, gender, ignore, workers, final, flags)
    except Exception:
        return {"blocks": final, "flags": flags, "status": "skipped"}


def _run_guard(blocks, call, budget_seconds, gender, ignore, workers, final, flags):
    deadline = time.monotonic() + float(budget_seconds) if budget_seconds is not None else None
    state = {"budget_hit": False}

    def expired() -> bool:
        if deadline is not None and time.monotonic() >= deadline:
            state["budget_hit"] = True
            return True
        return False

    try:
        call = call or _default_call()
    except Exception:
        return {"blocks": final, "flags": flags, "status": "skipped"}

    items = []
    unchecked = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        item = {"id": str(block.get("id")), "text": str(block.get("text") or "").strip(),
                "source": str(block.get("source") or "")}
        if not item["text"]:
            continue
        if not item["source"].strip():
            unchecked.add(item["id"])
            continue
        items.append(item)
    by_id = {item["id"]: item for item in items}

    def check(subset: List[Dict[str, Any]]):
        """→ (id → 问题列表, 未核对的 id 集合)"""
        problems: Dict[str, List[Dict[str, str]]] = {item["id"]: [] for item in subset}
        failed = set()
        for item in subset:
            problems[item["id"]].extend(_local_problems(item, gender, ignore))
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in subset:
            groups.setdefault(item["source"], []).append(item)

        def verify(group):
            if expired():
                return group, None
            try:
                return group, _verify_group(call, group)
            except Exception:
                return group, False

        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            results = list(pool.map(verify, groups.values()))
        for group, found in results:
            if found is None or found is False:
                failed.update(item["id"] for item in group)
                continue
            for row in found:
                problems[row["id"]].append({"kind": row["verdict"], "sentence": row["sentence"],
                                            "problem": row["problem"]})
        return problems, failed

    first, failed_first = check(items)
    unchecked |= failed_first
    need_rewrite = [by_id[i] for i, probs in first.items() if probs]

    def rewrite(item):
        if expired():
            return item["id"], None
        prompt = REWRITE_PROMPT % (item["text"], _problem_text(first[item["id"]]), item["source"])
        try:
            answer = _ask(call, prompt)
        except Exception:
            return item["id"], None
        new = answer.get("text")
        if not isinstance(new, str) or not new.strip():
            return item["id"], None
        new = new.strip()
        original = len(_norm(item["text"]))
        kept = len(_norm(new))
        # 重写不能把整段砍掉：太短说明删掉了信息，保留原文和它的标记
        if kept < 8 or kept < original * 0.5:
            return item["id"], None
        if kept > original * 1.15 + 4:
            return item["id"], None  # 重写只能删减或改正（如“她”改“学生”），明显变长说明加了内容
        return item["id"], new

    rewritten: Dict[str, str] = {}
    if need_rewrite:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            for item_id, new in pool.map(rewrite, need_rewrite):
                if new and _norm(new) != _norm(by_id[item_id]["text"]):
                    rewritten[item_id] = new

    second: Dict[str, List[Dict[str, str]]] = {}
    if rewritten:
        again = [{**by_id[i], "text": text} for i, text in rewritten.items()]
        second, failed_second = check(again)
        # 重写后没能再核对的，保留原文并沿用原来的问题
        for item_id in failed_second:
            rewritten.pop(item_id, None)
            second.pop(item_id, None)
            unchecked.add(item_id)

    for item in items:
        item_id = item["id"]
        problems = first[item_id]
        text = item["text"]
        if item_id in rewritten and len(second.get(item_id, [])) < len(problems):
            text, problems = rewritten[item_id], second[item_id]
        final[item_id] = text
        seen = set()
        for problem in problems:
            key = (problem["sentence"], problem["kind"])
            if key in seen:
                continue
            seen.add(key)
            flags.append({"id": item_id, "sentence": problem["sentence"],
                          "kind": problem["kind"], "problem": problem["problem"],
                          "source_excerpt": _excerpt(problem["sentence"], item["source"])})

    checked_ids = set(by_id) - unchecked
    if not unchecked:
        status = "checked"
    elif state["budget_hit"] or checked_ids:
        status = "partial"
    else:
        status = "skipped"
    return {"blocks": final, "flags": flags, "status": status,
            "unchecked": sorted(unchecked)}
