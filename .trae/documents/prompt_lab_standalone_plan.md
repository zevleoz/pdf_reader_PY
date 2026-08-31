# Prompt Lab — Standalone 测试台 → Web 集成（修订方案）

## 用户诉求（澄清后）

> 我需要它是一个**全新的、独立的测试台**，用来测试 prompt、AI 响应、以及响应质量。做完之后，再把这套能力**迁移到最新版的 web 里**。

当前 `/prompt-lab` 路由嵌在 `app.py` 里、需要管理员登录、并且**直接覆盖生产 prompt**（`prompts/ai_interpreter.md`）—— 这三点都不符合"独立测试台"的要求。

## 两阶段方案

### Phase 1 — 独立测试台（Standalone）

**目标**：一个完全独立、本地运行、零依赖（不需要登录、不影响生产）的 prompt 迭代工作台。可以一边跑生产 web、一边在测试台上改 prompt，互不干扰。

#### 新建文件（全部独立，不修改 app.py）

| 文件 | 作用 |
|---|---|
| `prompt_lab_app.py` | 独立 Flask 应用，端口 `5555`，自包含所有路由 |
| `templates/prompt_lab_standalone.html` | 独立测试台 UI（不共用主 web 的 `style.css`，内联样式） |
| `prompts/ai_interpreter_lab.md` | **工作副本**，初始内容从生产 prompt 复制而来；所有迭代只动这个文件 |
| `prompts/lab_versions/` | 测试台版本历史（和生产 `prompts/versions/` 隔离） |
| `data/lab_test_cases/` | 多组测试数据目录，初始包含 `cici.json`（从现有 `data/report_data.json` 复制） |

#### 关键设计：和生产解耦

| 维度 | 生产 web | 独立测试台 |
|---|---|---|
| Prompt 文件 | `prompts/ai_interpreter.md` | `prompts/ai_interpreter_lab.md` |
| 版本目录 | `prompts/versions/` | `prompts/lab_versions/` |
| 测试数据 | `data/report_data.json`（OCR 流程产出） | `data/lab_test_cases/*.json`（手动管理，可多组） |
| 登录 | `@page_login_required` | 无（本地 dev 工具） |
| 端口 | 生产端口 | `5555` |
| 进程 | gunicorn / systemctl | `python prompt_lab_app.py`（前台运行） |

#### 独立测试台功能

1. **测试数据切换**：顶部下拉菜单，可在多组测试数据间切换（cici / 其他学生 / 极端 case）
2. **Prompt 编辑**：左栏 textarea，可手动编辑、保存
3. **运行解读**：中栏点按钮 → 调 DashScope → 渲染 markdown 输出
4. **历史输出**：v1/v2/v3 标签页，可在不同版本输出间切换对比
5. **评分**：1-5 星
6. **反馈意见**：文本框，越具体越好
7. **自动迭代**：点按钮 → AI 根据反馈修改 lab prompt → 显示 diff → 自动重跑
8. **Diff 查看器**：高亮显示 prompt 改动区域
9. **重置**：把 lab prompt 恢复成生产 prompt（放弃当前迭代）
10. **晋升到生产**（关键）：一键把 `ai_interpreter_lab.md` 复制到 `ai_interpreter.md`，并自动备份旧生产版本到 `prompts/versions/`
11. **上传新测试数据**：支持上传新的 `report_data.json` 到 `data/lab_test_cases/`

#### 启动方式

```bash
cd /Users/jefflau/projects/pdf_report_converter/PDF_converter
python prompt_lab_app.py
# 浏览器打开 http://localhost:5555
```

#### 验证清单（Phase 1 完成标志）

- [ ] `python prompt_lab_app.py` 能独立启动，不依赖主 web
- [ ] 打开 `http://localhost:5555`，三栏布局正常
- [ ] 默认加载 Cici 测试数据
- [ ] 点「运行解读」→ AI 输出解读（说明 DashScope 调用正常）
- [ ] 打 3 星 + 写反馈 → 点「自动迭代」→ lab prompt 被修改 + diff 显示 + 自动重跑
- [ ] 手动编辑 prompt → 保存 → 运行
- [ ] 切换历史输出 v1/v2/v3
- [ ] 点「重置」→ lab prompt 恢复成生产版本
- [ ] 点「晋升到生产」→ `prompts/ai_interpreter.md` 被更新，旧版本进 `prompts/versions/`
- [ ] 生产 web 的 `/api/chat` 仍然读 `prompts/ai_interpreter.md`，自动用上新 prompt

---

### Phase 2 — 迁移到 Web（Phase 1 验证通过后）

**目标**：把独立测试台的 UI 和后端能力整合进主 web app，作为 `/prompt-lab` 路由的升级版，让用户不离开 web 也能继续迭代。

#### 改动

1. **替换** `app.py` 里现有的 `/prompt-lab` 和 4 个 `/api/prompt-lab/*` 路由
   - 改成读 `prompts/ai_interpreter_lab.md`（而不是直接读生产 prompt）
   - 新增 `/api/prompt-lab/promote` 路由（晋升到生产）
   - 新增 `/api/prompt-lab/test-cases` 路由（列出可选测试数据）
2. **替换** `templates/prompt_lab.html`
   - 用独立测试台的 UI（保持三栏布局，但加上 `style.css` 的 token 适配）
   - 加上测试数据切换下拉
   - 加上「晋升到生产」按钮
3. 保留 `@page_login_required`（web 里的测试台需要管理员权限）

#### 验证清单（Phase 2 完成标志）

- [ ] 登录主 web 后访问 `/prompt-lab`，UI 和独立版一致
- [ ] 所有独立测试台的功能都在 web 版里可用
- [ ] 迭代只动 `ai_interpreter_lab.md`，不影响生产
- [ ] 「晋升到生产」按钮工作正常

---

## 当前状态 vs 目标状态

| 项目 | 当前 | Phase 1 后 | Phase 2 后 |
|---|---|---|---|
| 独立测试台 | ❌ 嵌在 app.py | ✅ `prompt_lab_app.py` 独立运行 | ✅ 保留 |
| 生产 prompt 安全 | ❌ 迭代直接覆盖 | ✅ 迭代只动 lab 副本 | ✅ 同左 |
| 多测试数据 | ❌ 只有 cici | ✅ `data/lab_test_cases/` | ✅ 同左 |
| Web 内测试台 | ⚠️ 已有但不安全 | 不动 | ✅ 升级版 |
| 晋升机制 | ❌ 无 | ✅ 一键晋升 + 备份 | ✅ 同左 |

## 不做的事

- 不修改 `app.py` 里和生产相关的逻辑（generate / extract / validate / chat）
- 不修改 `prompts/ai_interpreter.md` 的内容（除非用户点「晋升到生产」）
- 不删除现有 `templates/prompt_lab.html`（Phase 2 才替换）
- 不引入新依赖（继续用 Flask + DashScope）
