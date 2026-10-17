# 会议纪要 DOCX 机器解析规范（minutes-v1）

本规范面向**下游系统**。交付物是 Word 文件本身（`.docx`），下游使用 `python-docx`
定点解析即可提取信息，**无需 AI 阅读**。结构化 JSON 仅为内部中间层，不对外交付。

本模板由 `minutes_docx.py` 渲染，章节标题与表格结构均为固定常量。

---

## 1. 文件识别

用 `python-docx` 打开后读取 core properties：

- `doc.core_properties.subject == "meeting-minutes"`
- `doc.core_properties.keywords` 中包含 `minutes-v1`

两者同时满足即为本模板，可进入解析；否则按其他文档处理。

---

## 2. 七个固定章节标题（H1 锚点）

以下文本**逐字固定**，不随会议内容变化。解析时按标题文本定位章节，不依赖顺序之外的信息：

| 序号 | H1 标题文本 |
| --- | --- |
| 1 | 执行摘要 |
| 2 | 心力 |
| 3 | 精力 |
| 4 | 学习力 |
| 5 | 生涯力 |
| 6 | 后续行动项 |
| 7 | 会议总体判断 |

- 这些标题在文档中为 **16pt** 段落（品牌行「凭远教育 · Y4 解读会会议纪要」同为 16pt，需按文本排除）。
- 某章节会议未讨论时，其**正文为空，但 H1 标题仍保留**。
- 四力章节内的小标题为 H3（12pt），标题文本固定：
  - 心力：情绪与自我概念 / 同伴关系 / 家庭与依恋 / 内驱力 / 人格
  - 学习力：认知资源优势 / 执行能力与认知灵活性 / 学习动机 / 学习方法与策略 / 学习力整体判断
  - 生涯力：职业兴趣 / 能力优势与专业方向 / 职业价值观 / 生涯力整体判断
  - 精力：无小标题，正文直接置于「精力」之下

---

## 3. 固定表格

### 表 #1：会议信息表（`doc.tables[0]`）

2 列，固定行序（`单元格[0]` 为标签，`单元格[1]` 为值；空值显示为 `—`）：

| 行序 | 标签 |
| --- | --- |
| 0 | 学生 |
| 1 | 年级 |
| 2 | 性别 |
| 3 | 会议日期 |
| 4 | 解读老师 |
| 5 | 参会人 |
| 6 | 生成日期 |

### 表 #2：行动项表（`doc.tables[-1]`）

- 表头行固定为：`优先级 | 行动 | 原因 | 方式 | 时间`（红色底、白字）。
- 数据行从第 1 行起，每行 5 列，与表头一一对应。
- `优先级` 为从 1 开始的连续整数。
- 会议未形成行动项时，仅有一行**合并单元格**，文本为 `本次会议未形成明确行动项`（表头不变）。

> 说明：表 #1 与表 #2 之间还包含「执行摘要」的单格底纹框（`doc.tables[1]`）。
> 因此**务必用 `doc.tables[0]` 取会议信息表、`doc.tables[-1]` 取行动项表**，不要假设只有两张表。

---

## 4. 解析示例（python-docx）

```python
from docx import Document

def parse_minutes(path):
    doc = Document(path)
    cp = doc.core_properties
    assert cp.subject == "meeting-minutes" and "minutes-v1" in (cp.keywords or "")

    h1 = [p.text for p in doc.paragraphs
          if p.runs and p.runs[0].font.size and p.runs[0].font.size.pt == 16
          and p.text != "凭远教育 · Y4 解读会会议纪要"]

    info = doc.tables[0]
    meta = {info.rows[i].cells[0].text: info.rows[i].cells[1].text for i in range(len(info.rows))}

    summary = [p.text for p in doc.tables[1].rows[0].cells[0].paragraphs
               if p.text.strip() and p.text.strip() != "—"]

    fields = ["priority", "what", "why", "how", "timeline"]
    actions = [dict(zip(fields, [c.text for c in row.cells]))
               for row in doc.tables[-1].rows[1:]
               if row.cells[0].text != "本次会议未形成明确行动项"]

    return {"student_name": meta.get("学生", ""), "meeting_date": meta.get("会议日期", ""),
            "sections": h1, "executive_summary": summary, "action_items": actions}
```

调用示例：

```python
data = parse_minutes("凭远Y4解读会纪要_张三.docx")
print(data["student_name"], data["meeting_date"])
print(data["executive_summary"])
for a in data["action_items"]:
    print(a["priority"], a["what"], a["timeline"])
```

---

## 5. 兼容性承诺

- 模板版本写在 core properties `keywords` 中（当前为 `minutes-v1`）。
- 后续模板演进时，`keywords` 会升级为 `minutes-v2`，下游按 `keywords` 分流：
  - 先读取 `keywords`，命中 `minutes-v1` 用本规范解析；
  - 命中其他版本时切换到对应版本的解析逻辑。
- 同一版本内，**七个 H1 标题文本、两张锚点表格的行序/表头均不变**，属于稳定契约。