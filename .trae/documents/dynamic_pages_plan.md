# 动态页面生成方案（修订版）

## 问题描述
当前系统要求必须上传4份PDF才能生成报告，如果上传少于4份，会报错。需求是：支持上传1-4份PDF，根据可用数据动态生成页面。

**核心原则**：页面尽量显示，即使某些数据缺失；只有当某个页面完全没有核心数据时才跳过。

## 架构分析

### PDF与数据的对应关系
| PDF | 数据范围 | 主要页面 |
|-----|---------|---------|
| A2 | 001-008（认知能力） | P12（认知资源） |
| B3 | 009-014（情绪稳定性）、020-040（依恋关系）、063-072（人格） | P04（情绪稳定性）、P06（依恋关系）、P08（人格） |
| B4 | 041-050（体质健康）、051-058（自我概念）、059-062（思维模式/内驱力） | P05（自我概念）、P07（内驱力）、P10（体质健康） |
| B6 | 073-090（学习动机/执行功能）、091-096（职业兴趣）、097-103（能力优势）、104-109（职业价值观） | P13（执行功能）、P14（学习动机）、P16（职业兴趣）、P17（能力优势）、P18（职业价值观） |

### 页面结构与核心数据点
| 页面 | 核心数据点 | 是否必须有数据 |
|------|-----------|--------------|
| P01 封面 | 学生信息 | 始终显示 |
| P02 Y4介绍 | 无 | 始终显示 |
| P03 心力介绍 | 无 | 始终显示（如果有心力系统页面） |
| P04 情绪稳定性 | 009 | 有数据才显示 |
| P05 自我概念 | 051 | 有数据才显示 |
| P06 依恋关系 | 020, 021, 022 | 有数据才显示 |
| P07 内驱力 | 059, 060 | 有数据才显示 |
| P08 人格 | 063-072 | 有数据才显示 |
| P09 精力介绍 | 无 | 始终显示（如果有精力系统页面） |
| P10 体质健康 | 041, 042 | 有数据才显示 |
| P11 学习力介绍 | 无 | 始终显示（如果有学习力系统页面） |
| P12 认知资源 | 001, 002 | 有数据才显示 |
| P13 执行功能 | 073-082 | 有数据才显示 |
| P14 学习动机 | 083-090 | 有数据才显示 |
| P15 生涯力介绍 | 无 | 始终显示（如果有生涯力系统页面） |
| P16 职业兴趣 | 091-096 | 有数据才显示 |
| P17 能力优势 | 097-103 | 有数据才显示 |
| P18 职业价值观 | 104-109 | 有数据才显示 |

## 实现方案

### 1. 修改 `generate.py`

**添加页面级数据可用性检测**：
```python
def has_page_data(page_key_codes: List[str]) -> bool:
    """检查某个页面是否有有效数据"""
    for code in page_key_codes:
        val = v(code)
        if val is not None and val != "" and str(val).strip() != "0":
            return True
    return False
```

**修改 `build_view_data()`**：
```python
def build_view_data() -> Dict[str, Any]:
    # 数据加载（不变）
    ...
    
    pages: List[Dict[str, Any]] = [
        build_page_1(student),
        build_page_2(),
    ]
    
    # 心力系统：按页面逐个判断
    mind_pages = []
    if has_page_data(["009"]):
        mind_pages.append(build_page_4())
    if has_page_data(["051"]):
        mind_pages.append(build_page_5())
    if has_page_data(["020", "021", "022"]):
        mind_pages.append(build_page_6())
    if has_page_data(["059", "060"]):
        mind_pages.append(build_page_7())
    if has_page_data(["063", "064", "065", "066", "067"]):
        mind_pages.append(build_page_8())
    
    # 如果有心力系统页面，添加心力介绍页
    if mind_pages:
        pages.append(build_page_3())
        pages.extend(mind_pages)
    
    # 精力系统：按页面逐个判断
    energy_pages = []
    if has_page_data(["041", "042"]):
        energy_pages.append(build_page_10())
    
    # 如果有精力系统页面，添加精力介绍页
    if energy_pages:
        pages.append(build_page_9())
        pages.extend(energy_pages)
    
    # 学习力系统：按页面逐个判断
    learning_pages = []
    if has_page_data(["001", "002"]):
        learning_pages.append(build_page_12())
    if has_page_data(["073", "074", "075", "076", "077", "078", "079", "080", "081", "082"]):
        learning_pages.append(build_page_13())
    if has_page_data(["083", "084", "085", "086", "087", "088", "089", "090"]):
        learning_pages.append(build_page_14())
    
    # 如果有学习力系统页面，添加学习力介绍页
    if learning_pages:
        pages.append(build_page_11())
        pages.extend(learning_pages)
    
    # 生涯力系统：按页面逐个判断
    career_pages = []
    if has_page_data(["091", "092", "093", "094", "095", "096"]):
        career_pages.append(build_page_16())
    if has_page_data(["097", "098", "099", "100", "101", "102", "103"]):
        career_pages.append(build_page_17())
    if has_page_data(["104", "105", "106", "107", "108", "109"]):
        career_pages.append(build_page_18())
    
    # 如果有生涯力系统页面，添加生涯力介绍页
    if career_pages:
        pages.append(build_page_15())
        pages.extend(career_pages)
    
    ...
```

### 2. 修改 `app.py`

**修改 `/api/generate` 接口**：
```python
@app.route("/api/generate", methods=["POST"])
def api_generate():
    # 接收1-4个文件，不再强制要求4个
    files_by_key = {}
    for key in REQUIRED_KEYS:
        f = request.files.get(key)
        if f and f.filename:
            files_by_key[key] = f
    
    if not files_by_key:
        return jsonify({
            "ok": False,
            "error": "请至少上传一份PDF文件"
        }), 400
    
    # 后续逻辑不变，但只处理上传的文件
    ...
```

**修改 `extract.py`**：
- 在提取时只处理上传的PDF文件
- 未上传的PDF对应数据保持为空或默认值

### 3. 修改前端 `templates/index.html`

**修改上传区域**：
- 将4个强制上传槽改为可选
- 添加提示"请上传1-4份PDF文件"
- 实时显示已上传的文件数量

## 风险与注意事项

1. **数据部分缺失**：某个页面可能有部分数据但不是全部，此时页面仍然显示，缺失的数据显示为空或默认值
2. **页面编号**：动态生成页面后，页面编号可能不连续，但用户不关心编号，只关心内容
3. **用户体验**：用户可能不知道缺少哪些数据，建议在生成前显示"将生成X页报告"的提示

## 验证方案

1. **测试场景1**：只上传A2（认知能力）→ 应生成封面+介绍+学习力系统（P01-P02, P11-P12）
2. **测试场景2**：上传A2+B4 → 应生成封面+介绍+心力系统（部分）+精力系统+学习力系统
3. **测试场景3**：上传全部4份 → 应生成完整18页报告
4. **测试场景4**：上传B3+B6 → 应生成封面+介绍+心力系统+生涯力系统

## 实施步骤

1. 修改 `generate.py`，添加页面级数据可用性检测和条件性页面构建
2. 修改 `app.py`，允许1-4个文件上传
3. 修改 `extract.py`，只处理上传的PDF文件
4. 修改 `templates/index.html`，更新上传UI
5. 测试所有场景