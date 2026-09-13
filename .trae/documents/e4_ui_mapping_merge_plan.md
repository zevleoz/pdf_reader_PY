# E4 三项改版计划：UI 卡片网格 / 映射上线 / 数据与判断合并

## 研究结论

1. **UI 宽度浪费根因**：[internal.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/internal.html#L9-L17)
   `.lab-layout` 是两列 grid（`1fr 1.4fr`），但页面里只剩一个 `.lab-col`（AI 解读/有效评价两个 tab），
   右列 58% 完全空白。评价区 `.eval-dim-body`（L321）又是纵向 flex，卡片逐行铺满窄列。
   卡片样式 `.eval-card` 已存在，只需把容器改为响应式网格。
2. **映射现状**：本地 sqlite `data/y4_students.db` 的 `e4_mapping` 有 77 行 / 62 个编号
   （E1:33 E2:7 E3:25 E4:12，含子类：焦虑状态/学习信心/饮食/睡眠/动力引擎/大脑引擎）。
   生产是阿里云 ECS（120.55.0.127，/opt/y4_report，独立 sqlite，git pull 不覆盖 data/），
   生产映射为 0。`db.save_e4_mapping()` 按 code 删除重插，天然支持幂等 upsert。
   注意：`*.json` 被 .gitignore 排除，seed 须用 .py 文件而非 JSON。
3. **数据与判断重复/割裂**：`_assemble_e4_protocol` 里 E4_EVALUATIONS（Python 数据+verdict）
   与 E4_ANALYSIS（AI 文字）是两个独立 section；AI 输出按 `#### 问题：<原文>` 分题、
   末尾三段式，结构可解析。两个 Step2 路由都产出 `full_analysis`，已有清洗器 `_sanitize_e4_step2`。

## 已确认决策

- 判断生成：**保留一次 AI 调用**，每个问题配「写作模板」（基于 Leo 范例逐题确认后沉淀），
  Python verdict 做骨架，AI 只按模板写判断。
- UI：**指标卡片网格**——每个指标一个长方形卡片，一行放多个，整页铺满；仅改 internal.html（生产版）。
- 映射：**seed Python 文件 + 幂等脚本**，部署后在 ECS 跑一次。
- 逐题确认：按 E1→E2→E3→E4 四批在对话中确认，用 Leo 数据做范例。

---

## A. 内部下载页 UI（internal.html，纯 CSS + 少量容器类）

1. `.lab-layout`：`grid-template-columns: 1fr`（去掉空右列），`max-width` 1600→1680px，高度不变；
   ≤1000px 媒体查询保持单列。
2. `.eval-dim-body`：纵向 flex →
   `display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:8px; align-items:start;`
   Y4 四维视图与 E4 框架视图共用同一容器类，两个视图同时变网格。
3. `.eval-card`：去 margin-bottom；头部/数值/操作区在窄卡片内允许换行；
   长标签（如「情绪稳定性-无力感掌控感得分」）两行不截断；卡片等高用 align-items:start 避免拉高。
4. 维度分组标题（sticky）保持整行横跨；映射 E1-E4 色标、偏差色条不变。
5. AI 解读 tab 随面板变宽自然生效，不改其内部排版。

## B. E4 映射上线（新增 2 个文件，不改现有逻辑）

1. 新增 `e4_mapping_seed.py`：`SEED_ENTRIES = [{"code","e4_dims":[{"e4_dim","e4_sub"}]}]`，
   从本地 sqlite 全量导出 77 行生成（实施时用脚本读取 DB 写出该 .py，不手抄）。
2. 新增 `seed_e4_mapping.py`（仓库根，可 `python seed_e4_mapping.py` 执行）：
   调 `db.save_e4_mapping(SEED_ENTRIES)` 幂等 upsert，打印写入数量；只覆盖 seed 中的 code，不动其他数据。
3. 部署：git push 后在 ECS 执行
   `cd /opt/y4_report && git pull && venv/bin/python seed_e4_mapping.py && sudo systemctl restart y4_report`
   （命令在交付说明里给用户，服务器由用户操作）。

## C. 数据与判断合并为一个 section（app.py + evaluation_rules.py）

### C1. Step2 输出契约（prompt）
- 每个问题输出：`#### <问题原文>`（E2 用固定标题 `#### E2 · Energy（精力管理）`），
  下面直接写判断正文；**严禁回显**判定行/数据行（沿用现有硬规则+清洗器）。
- system prompt 注入新增的 `E4_JUDGMENT_GUIDES`（见 C2）：每题的写作模板（句式、必看点、分支、禁写）。
- 末尾三段式（显著问题/可能失真·先观察/跟进线索与切入点）契约不变。

### C2. 逐题写作模板（evaluation_rules.py 新增 `E4_JUDGMENT_GUIDES`）
- dict，key 为框架问题原文（E2 用固定 key `E2_ENERGY`），value 为该题写作指南；
- 初版 28 个单元全部据 JSN 对 Leo 的批注起草（泛化规则，不写死 Leo 数值），
  随后续四批改批直接改这个 dict 即可收敛 AI 产出。

### C3. 解析与合并拼装（app.py）
- 新增 `_parse_e4_judgments(full_analysis) -> (dict[q, 判断md], 三段式md, 未归位片段)`：
  按 `#### ` 标题切分，标题归一化（去「问题：」、空格标点）后与框架问题原文双向 contains 匹配；
  E2 固定标题映射到 E2 组；三段式用现有 `_e4_step2_tail` 取。
- `_assemble_e4_protocol` 合并为**一个** `## E4_EVALUATIONS`：
  维度 → 问题标题 → `[VERDICT]` → 数据行（Python，含 [REF]/trait/评级）→
  空行 → `判断：<对应 AI 判断正文>`；无匹配判断时该行省略（不造空判断）。
  全部问题后接 AI 三段式原文；未归位片段以「未归位判断」附录兜底，防丢失。
- 删除独立 E4_ANALYSIS section；OVERVIEW（真实优势/名单归属）、Y4 段不变。
- 一站式与 prompt-lab 两个入口同走拼装函数，同步生效；`_sanitize_e4_step2` 继续在解析前清洗。

## D. 逐题确认流程（代码落地后，对话内进行，四次）

1. C 完成后我先用 Leo 数据（从下载协议重建，零 AI 费用）产出 **E1 八个问题的判断范例** 贴在对话里；
2. 用户逐条反馈 → 我改 `E4_JUDGMENT_GUIDES`（泛化，不绑定 Leo）；
3. E1 定稿后依次 E2 → E3 → E4；全部定稿后用户在生产用 Leo 重跑做端到端确认。

## Files

- `templates/internal.html`：布局 CSS + 网格（仅样式/容器，不动 JS 数据流）
- `e4_mapping_seed.py`（新）、`seed_e4_mapping.py`（新）
- `evaluation_rules.py`：新增 E4_JUDGMENT_GUIDES
- `app.py`：Step2 prompt 注入 guides 与输出契约、`_parse_e4_judgments`、`_assemble_e4_protocol` 合并

## 验证

1. `python3 -m py_compile app.py evaluation_rules.py seed_e4_mapping.py e4_mapping_seed.py`。
2. 本地临时 sqlite 跑 `seed_e4_mapping.py` 两次：行数一致、幂等、原有学生数据不动；`get_e4_mapping()` 校验 62 code。
3. 浏览器打开 /internal（本地 Zaylin 数据）：卡片网格多列铺满、宽屏/窄屏断点正常、
   Y4 与 E4 两视图、档位/偏差/已确认操作可用。
4. 用 Leo 旧 md 中的 AI 分析段离线测 `_parse_e4_judgments`：28 个判断全部归位、三段式完整、无丢失；
   再拼完整 md 确认一个 section 内「数据→判断」顺序正确。
5. 生产部署跑 seed 后映射显示 62+/108；Leo 重跑 E4（AI）确认合并版式。

## 风险

- AI 标题不逐字 → 归一化+双向 contains 匹配；仍未命中的进附录不丢失，并在 prompt 里给精确标题契约。
- 卡片网格在超宽屏卡片过宽：minmax 上限用 1fr 自适应，必要时加 max-columns（实施时按截图微调）。
- seed 覆盖生产已有的同 code 人工修改：首次生产为空，无冲突；脚本只 upsert seed 内 code，且幂等可重跑。
- 逐题模板写作指南会让 Step2 prompt 变长：guides 每条控制在 2-3 句，超长按问题缩写。
