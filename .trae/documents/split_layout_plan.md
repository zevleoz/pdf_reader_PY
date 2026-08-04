# Y4 Report Generator — Split Layout & Deployment Plan (ECS Only, No Vercel)

## Why ECS 方案（推荐：最便宜最简单）

### 方案说明

| 项 | 说明 |
|----|------|
| **架构** | 全栈阿里云 ECS — Nginx + Gunicorn + Flask |
| **域名** | 用你的子域名，例如 `report.yourdomain.com` → DNS A 记录 → ECS 公网 IP |
| **费用** | 0 额外费用（ECS 已有），SSL 用 Let's Encrypt 免费 |
| **复杂度** | 最低，无跨域 CORS，无两套部署 |
| **改动** | 只需重写 `templates/index.html` 的页面布局 |
| **保留** | `extract.py` `generate.py` `app.py` 全部零改动 |

### 与 Vercel 方案的对比

| 方案 | 成本 | 复杂度 | 跨域 | 是否推荐 |
|------|------|--------|------|----------|
| **ECS 全部本地前端（本计划）** | 零新增 | 低（单部署） | 无 | ✅ **强烈推荐** |
| Vercel 前端 + ECS 后端 | Vercel 免费，但需 ECS 公网 API + CORS | 高（两部署） | 有 CORS 头 | ❌ 复杂不必要 |

---

## Part 1: UI 设计方向

### 1.1 页面布局（左 1/3 + 右 2/3）

```
┌────────────────────────────────────────────────────────────┐
│  [顶栏：报告生成器                     阿里云·Y4品牌色        │
├──────────────────────┬─────────────────────────────────────┤
│  左栏 33%           │  右栏 67%                        │
│                      │                                   │
│  ┌──────────────┐   │  ┌──────────────────────────────┐  │
│  │ 上传 4 个槽  │   │  │                             │  │
│  │  A2 (核心素养)│   │  │   PDF 预览区               │  │
│  │  B3 (学习能力)│   │  │   （iframe / <object>）     │  │
│  │  B4 (认知思维)│   │  │                             │  │
│  │  B6 (职业发展)│   │  │   未生成：显示占位提示    │  │
│  └──────────────┘   │  │   生成后：显示PDF预览+下载│  │
│                      │  │                             │  │
│  思维模式分值输入   │  └──────────────────────────────┘  │
│                      │                                   │
│  ┌──────────────┐   │  ┌──────────────────────────────┐  │
│  │  生成按钮    │   │  │ 文件信息 / 下载按钮 /      │  │
│  └──────────────┘   │  │ 生成状态 / 日志             │  │
│                      │  └──────────────────────────────┘  │
│  上传状态提示        │                                   │
└──────────────────────┴─────────────────────────────────────┘
```

### 1.2 设计语言

**主题：教育测评报告工具 — 专业、冷静、克制**

| 项 | 值 | 理由 |
|----|----|------|
| **主色** | `#1d4ed8` (深蓝) — 从 logo_red.png 的品牌色取调出来的严肃蓝 | 教育专业感，不是 AI 默认的 cream/terracotta |
| **强调色** | `#2563eb` (稍亮蓝) | 按钮 hover |
| **背景** | `#f8fafc` (极浅灰蓝) | 干净，不是 warm cream（AI 默认） |
| **卡片背景** | `#ffffff` | 卡片分隔感 |
| **正文** | `#0f172a` (深蓝灰) | 易读，不是纯黑 |
| **辅助文字** | `#64748b` (浅灰蓝) | |
| **分割线** | `#e2e8f0` | 不使用黑色细线条 |
| **圆角** | 10-12px (容器)，8px (按钮/小卡片) | 克制，不圆钝 |
| **字族** | `Inter` / `-apple-system` / `PingFang SC` (中文)，单套字体不混搭 |
| **动效** | 只有按钮 hover、状态切换、进度条；无炫技动画 | 工具属性>展示属性 |

### 1.3 签名视觉元素

**Logo 角标带**：在页面最顶部放一条 3px 高的品牌蓝 (#1d4ed8) 色块 + 左上角放 `branding/logo_color.png 或 logo 小尺寸。这与最终报告的视觉一致性，让用户感觉到"这个页面就是报告生成器"。

### 1.4 左栏：上传区（33%）

- 4 个上传槽用紧凑的卡片式（不是卡片 每个卡片
- 每个槽：标签(A2/B3/B4/B6 + 报告类型小标)
- 文件选中：左侧显示小 PDF 图标
- 思维模式分值放在上传槽下方
- 生成按钮：大蓝按钮，按钮禁用状态灰
- 状态 spinner + 文案：按钮
- 下方放简短提示："约需 1-3 分钟"
- 错误信息：红色背景卡片

### 1.5 右栏：PDF 预览区（67%）

有三种状态：

**状态 1：空状态（初始）**
- 居中大型 PDF 占位图标
- 文案：「上传 PDF 后点击「生成报告」在此预览并下载」
- 小提示：「最终报告将包含认知能力、情绪稳定性、职业兴趣等约 18 页内容」

**状态 2：生成中**
- 隐藏 PDF 占位 + 进度条（动画）
- 步骤提示：「1/3 提取数据中…」→「2/3 校验完整性…」→「3/3 生成 PDF…」
- （可选：实时读取 /preview 接口返回的状态）

**状态 3：已生成**
- 上方：文件名 + 大小 + 「重新生成 + 「下载 PDF」主按钮 + 「新窗口打开」次按钮
- 下方：`<iframe>` 或 `<object data="..." type="application/pdf">` 嵌入预览报告 PDF
- 高度填满剩余高度 100%

---

## Part 2: Technical Implementation

### 2.1 修改的文件

**只需要修改的文件：

| 文件 | 改动内容 | 风险 |
|------|----------|------|
| `templates/index.html` | **重写为分栏布局 + 右栏 PDF 预览 | 低（纯前端 UI 前端 JS 交互） |
| `app.py` | 添加 `/preview/pdf` 路由？不添加？—— 不需要，已有的 `/output/report.pdf` 已经能被访问，用它即可 | **零改动** |
| 其他文件 | `extract.py`, `generate.py`, `data_points.py`, `validate.py`, `requirements.txt`, `.gitignore`, `gunicorn_config.py`, `nginx_y4.conf`, `y4_report.service` —— 全保留 | 零改动 |

### 2.2 新 HTML 结构说明

```html
<body>
  <div class="topbar">
    <div class="brand">
      <img src="/output/branding/logo_color.png" class="logo" />
      <span class="brand-name">综合测评报告生成器</span>
    </div>
  </div>
  <div class="layout">
    <!-- 左栏 33% -->
    <aside class="left-panel">
      <h2>上传报告</h2>
      <div class="upload-slots">
        <!-- A2, B3, B4, B6 四个上传卡片 -->
      </div>
      <div class="mindset-input">
        <!-- 思维模式分值 -->
      </div>
      <button id="genBtn">🚀 生成报告</button>
      <div id="status" class="status"></div>
    </aside>

    <!-- 右栏 67% -->
    <section class="right-panel">
      <div class="pdf-toolbar">
        <div class="pdf-info">
          <span id="pdf-filename">—</span>
          <span id="pdf-size" class="muted"></span>
        </div>
        <div class="actions">
          <button id="openBtn" disabled>↗ 新窗口打开</button>
          <button id="downloadBtn" disabled class="primary">⬇ 下载 PDF</button>
        </div>
      </div>
      <div class="pdf-preview" id="pdfPreview">
        <!-- 空状态 / 生成中 / 已生成 -->
      </div>
    </section>
  </div>
</body>
```

### 2.3 CSS 响应式

- 桌面：左 33% + 右 67%（`grid-template-columns: 33% 1fr`）
- 平板/移动：上下堆叠（`grid-template-columns: 1fr`），先上传区再预览区
- PDF iframe 最小高度 600px

### 2.4 JS 交互逻辑

```
用户点击生成按钮
  ↓
setStatus("上传中…", loading)
左栏按钮禁用
  ↓
POST /api/generate (FormData, timeout=300s)
  ├─ 成功：
  │   clearTimeout
  │   showPdfPreview(blob)
  │   右栏工具按钮启用 → 下载 + 新窗口打开
  │   setStatus("完成", ok)
  │   左栏按钮恢复
  └─ 失败 / 超时：
      setStatus("失败: ...", error)
      左栏按钮恢复
      alert(错误详情)
```

关键：用 `URL.createObjectURL(blob)` 创建临时 URL，既能给 iframe 预览，又能给 `<a download>` 下载。不需要刷新页面，不需要额外路由。

### 2.5 部署：完全沿用之前的部署

所有部署文件（`gunicorn_config.py`, `nginx_y4.conf`, `y4_report.service`, `.env.production`, `deploy.sh`）**完全不变**，只需按之前的部署步骤执行即可。

域名配置：
1. 在你的域名 DNS 管理中添加 A 记录：
   ```
   子域名：report.你的域名.com
   类型：  A
   值：    阿里云 ECS 公网 IP
   TTL：   600
   ```
2. 等 DNS 生效（几分钟到几小时）
3. 服务器上执行 Let's Encrypt：
   ```bash
   sudo certbot --nginx -d report.你的域名.com
   ```

---

## Part 3: 文件改动列表

| 改动 | 说明 |
|--------|------|
| **重写** `templates/index.html` | 改为分栏 UI，左上传，右预览下载 |
| **保留** `extract.py / generate.py / data_points.py / validate.py | 零改动 |
| **保留** `app.py` | 零改动（之前已加 `import os` / config 等，足够） |
| **保留** `requirements.txt` | 零改动 |
| **保留** `gunicorn_config.py` | 零改动 |
| **保留** `nginx_y4.conf` | 只需改 `server_name` 为你的子域名 |
| **保留** `y4_report.service` | 零改动 |
| **保留** `.env.production` | 填入生产 API Key |
| **保留** `deploy.sh` | 零改动 |

---

## Part 4: 风险

| 风险 | 应对 |
|------|------|
| iframe 在某些浏览器 PDF 预览不支持内置 | 降级：空状态显示「点击下载按钮查看 PDF」，download 按钮始终可用 |
| branding/logo_color.png 路径找不到 | 用已有的 `/output/branding/` 路径（generate.py 会复制，但若从未生成过会没有，→ 改为直接从 `/static` 暴露 branding） |
| DNS 解析慢 | 先用 ECS 公网 IP:80 访问测试 |
