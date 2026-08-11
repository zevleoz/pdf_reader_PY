# Phase 2: AI 解读聊天框 — 实施计划

## 摘要

在 Phase 1 部署成功的基础上，将右侧 PDF 预览面板改为 AI 聊天框。PDF 生成完成后自动触发 AI 解读报告，用户可继续追问。AI 遵循用户自定义的 prompt/guideline（先留占位文件）。后端新增 `/api/chat` 路由，复用已有 DashScope API Key，使用文本模型 `qwen-plus`。

---

## 现状分析

### 数据流（不变）
```
用户上传 PDF → /api/generate → extract.py → data/report_data.json → generate.py → output/report.pdf
```

### 关键文件
| 文件 | 作用 | 改动 |
|------|------|------|
| [app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py) | Flask 入口 | 新增 `/api/chat` 路由 |
| [templates/index.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/index.html) | 前端 UI | 右栏改为聊天框 |
| `prompts/ai_interpreter.md` | AI 解读指南 | **新建**（占位，用户后填） |

### 可复用资源
- **DashScope API Key**：已硬编码在 [extract.py#L71](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/extract.py#L71)，环境变量 `DASHSCOPE_API_KEY` 也已配置
- **report_data.json**：133 项结构化数据 + 学生信息，是 AI 解读的数据源
- **DashScope OpenAI 兼容接口**：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，用 `urllib` 调用

---

## 拟定改动

### A. 新建 `prompts/ai_interpreter.md`（占位文件）

用户之后填入自己的解读指南。默认占位内容：

```markdown
# AI 解读师系统提示词

你是一位资深的青少年综合测评解读师。请基于学生的测评数据，按照以下要求进行解读：

（请在此处填写你的解读 prompt / guideline）

## 解读要求
- 基于数据说话，不编造
- 关注优势与待提升项
- 语言温和专业，面向家长可读

## 数据说明
- 编号 001-008：认知能力（百分位）
- 编号 009-014：情绪稳定性
- 编号 015-019：人格（大五）
- 编号 020-040：依恋关系
- 编号 041-050：体质健康
- 编号 051-058：自我概念
- 编号 059-062：思维模式与自驱力
- 编号 063-071：执行功能与学习策略
- 编号 072-094：职业兴趣与能力优势
- 编号 095-124：职业价值观
- 编号 125-133：常模平均数
```

### B. 修改 [app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py) — 新增 `/api/chat` 路由

在 `/api/generate` 路由之后、`/output/<filename>` 路由之前新增：

```python
@app.route("/api/chat", methods=["POST"])
def api_chat():
    """AI 聊天接口：接收用户消息 + 历史对话 → 调 DashScope 文本 LLM → 返回回复"""
    data = request.get_json(force=True)
    user_message = data.get("message", "").strip()
    history = data.get("history", [])  # [{"role":"user","content":"..."},{"role":"assistant","content":"..."}]

    if not user_message and not history:
        return jsonify({"ok": False, "error": "消息不能为空"}), 400

    # 1) 读取 AI prompt
    prompt_path = BASE_DIR / "prompts" / "ai_interpreter.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "你是测评解读助手。"

    # 2) 读取 report_data.json 作为上下文
    report_path = DATA_DIR / "report_data.json"
    if report_path.exists():
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        # 把 schema_124 精简为 "编号 标签：值" 的文本
        schema_items = report_data.get("schema_124", [])
        data_text = "\n".join(
            f"{it['code']} {it['label']}：{it.get('value', '—')}"
            for it in schema_items if it.get("value")
        )
        student = report_data.get("student", {})
        student_text = f"学生：{student.get('name','—')}，{student.get('gender','—')}，{student.get('grade','—')}"
        context = f"{student_text}\n\n测评数据：\n{data_text}"
    else:
        context = "（暂无测评数据）"

    # 3) 组装 messages
    messages = [
        {"role": "system", "content": system_prompt + "\n\n以下是学生测评数据：\n" + context},
    ]
    messages.extend(history[-10:])  # 最多带最近 10 条历史
    if user_message:
        messages.append({"role": "user", "content": user_message})

    # 4) 调用 DashScope OpenAI 兼容接口
    import urllib.request, urllib.error
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", extract.DEFAULT_DASHSCOPE_KEY).strip()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    payload = json.dumps({
        "model": "qwen-plus",
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {dashscope_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        reply = result["choices"][0]["message"]["content"]
        return jsonify({"ok": True, "reply": reply})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"AI 调用失败: {exc}"}), 500
```

**关键设计**：
- **无状态**：每次请求读 `data/report_data.json`，不存对话状态（前端管 history）
- **上下文窗口**：system prompt + report_data 全量 + 最近 10 条历史
- **模型**：`qwen-plus`（文本模型，非视觉），温度 0.4
- **不碰现有路由**：`/api/generate`、`/`、`/output/<filename>` 全部不变

### C. 修改 [templates/index.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/index.html) — 右栏改为聊天框

#### 布局变化
```
┌─────────────────┬──────────────────────────────────┐
│  左栏 (33%)      │  右栏 (67%) — AI 聊天框           │
│                 │                                  │
│  上传 PDF 槽     │  ┌─ 工具条 ──────────────────┐   │
│  A2/B3/B4/B6    │  │ ⬇ 下载报告.pdf    AI 就绪  │   │
│                 │  └────────────────────────────┘   │
│  思维模式分值    │  ┌─ 消息区 ──────────────────┐   │
│                 │  │ 🤖 AI: 解读中...            │   │
│  [生成报告]      │  │ 👤 你: ...                 │   │
│                 │  │ 🤖 AI: ...                 │   │
│  状态提示        │  │                           │   │
│                 │  └────────────────────────────┘   │
│                 │  ┌─ 输入区 ──────────────────┐   │
│                 │  │ [输入消息...]    [发送]    │   │
│                 │  └────────────────────────────┘   │
└─────────────────┴──────────────────────────────────┘
```

#### 具体改动

**1. 右栏 HTML 结构**（替换现有 `.right-panel` 内容）：
```html
<section class="right-panel">
  <!-- 工具条：PDF 下载 + AI 状态 -->
  <div class="chat-toolbar">
    <button class="btn primary" id="downloadBtn" onclick="downloadPdf()" disabled>
      ⬇ 下载报告
    </button>
    <span class="chat-status" id="chatStatus">AI 解读师待命</span>
  </div>
  
  <!-- 消息区 -->
  <div class="chat-messages" id="chatMessages">
    <div class="chat-empty">
      <div class="empty-icon">🤖</div>
      <div class="empty-title">AI 解读师</div>
      <div class="empty-sub">上传 PDF 并生成报告后，<br/>AI 将自动解读测评结果。</div>
    </div>
  </div>
  
  <!-- 输入区 -->
  <div class="chat-input-area">
    <input type="text" id="chatInput" placeholder="输入问题..." 
           onkeypress="if(event.key==='Enter')sendMessage()" disabled />
    <button class="btn primary" id="sendBtn" onclick="sendMessage()" disabled>发送</button>
  </div>
</section>
```

**2. `generate()` 函数改动**：
- PDF 生成成功后，不再显示 PDF 预览
- 保存 blob URL 到 `lastBlobUrl`（用于下载）
- 启用下载按钮
- **自动触发 AI 解读**：发送一条空消息（或 "请解读这份报告"）到 `/api/chat`

```javascript
// generate() 成功后的逻辑改为：
async function generate() {
  // ... 现有上传逻辑不变 ...
  
  const resp = await fetch('/api/generate', { method: 'POST', body: fd });
  
  if (!resp.ok) { /* 错误处理不变 */ return; }
  
  // 保存 PDF blob 供下载
  const blob = await resp.blob();
  lastBlobUrl = URL.createObjectURL(blob);
  
  // 启用下载按钮
  document.getElementById('downloadBtn').disabled = false;
  setStatus('✅ 报告已生成，AI 正在解读...', 'ok');
  
  // 自动触发 AI 解读
  await autoStartAIInterpretation();
}

async function autoStartAIInterpretation() {
  // 添加 AI 消息占位
  addMessage('assistant', '正在解读报告，请稍候...');
  document.getElementById('chatStatus').textContent = 'AI 解读中...';
  
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      message: '请根据这份综合测评数据，生成一份完整的解读报告。',
      history: []
    })
  });
  
  const data = await resp.json();
  if (data.ok) {
    // 更新最后一条 AI 消息
    updateLastMessage('assistant', data.reply);
    document.getElementById('chatStatus').textContent = 'AI 解读师就绪';
    // 启用输入
    document.getElementById('chatInput').disabled = false;
    document.getElementById('sendBtn').disabled = false;
  } else {
    updateLastMessage('assistant', '❌ 解读失败: ' + data.error);
  }
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  
  addMessage('user', text);
  input.value = '';
  
  // AI 占位
  addMessage('assistant', '思考中...');
  document.getElementById('chatStatus').textContent = 'AI 回复中...';
  
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      message: text,
      history: chatHistory
    })
  });
  
  const data = await resp.json();
  if (data.ok) {
    updateLastMessage('assistant', data.reply);
  } else {
    updateLastMessage('assistant', '❌ ' + data.error);
  }
  document.getElementById('chatStatus').textContent = 'AI 解读师就绪';
}
```

**3. 聊天消息渲染**：
- `addMessage(role, content)` — 创建消息气泡，AI 消息左侧蓝色，用户消息右侧灰色
- `updateLastMessage(role, content)` — 更新最后一条消息内容
- 极简 Markdown 渲染：标题/列表/加粗/段落（纯 JS，无外部库）
- `chatHistory` 数组维护对话历史，发送时传给后端

**4. CSS 新增**：
- `.chat-toolbar` — 顶部工具条
- `.chat-messages` — 消息滚动区（flex:1, overflow-y:auto）
- `.chat-message` — 消息气泡
- `.chat-message.assistant` — 左对齐蓝色背景
- `.chat-message.user` — 右对齐灰色背景
- `.chat-input-area` — 底部输入栏
- `.chat-empty` — 空状态

**5. 移除的代码**：
- `showPdfObject()` — 不再需要 PDF 预览
- `showGenerating()` 改为在聊天区显示加载状态
- `openInNewTab()` — 移除
- PDF object/iframe 相关 CSS

---

## 假设与决策

1. **不碰核心管道**：extract.py / generate.py / data_points.py / validate.py 零改动
2. **模型选择**：`qwen-plus`（文本模型，速度快、中文好、成本低），环境变量 `AI_TEXT_MODEL` 可覆盖
3. **无状态后端**：对话历史由前端管理，后端每次接收 history 数组
4. **上下文**：system prompt（用户 guideline）+ report_data.json 全量 + 最近 10 条历史
5. **占位 prompt**：先创建 `prompts/ai_interpreter.md`，用户之后替换为自己的内容
6. **下载方式**：PDF 生成后保存为 blob URL，下载按钮直接触发 `<a download>`
7. **不流式**：先实现非流式 JSON 响应（简单可靠），后续可升级为 SSE 流式
8. **本地兼容**：localhost `python app.py` 不受影响，AI 聊天功能同样可用

---

## 验证步骤

1. **不破坏现有管道**：
   - `python app.py run` 仍能从 PDF 生成 `output/report.pdf`
   - 网页上传 PDF → 点击生成 → PDF 下载按钮出现

2. **AI 聊天框**：
   - 生成 PDF 后，右栏自动出现 AI 解读消息
   - 输入框启用，可输入追问
   - AI 回复正常显示

3. **AI 无报告数据时**：
   - 未生成报告时直接发消息 → AI 回复"暂无测评数据"

4. **Prompt 自定义**：
   - 编辑 `prompts/ai_interpreter.md` → 重启服务 → AI 解读风格变化

5. **部署到 ECS**：
   - `git push` → ECS `git pull` → `systemctl restart y4_report`
   - 浏览器访问 `http://120.55.0.127` 测试完整流程
