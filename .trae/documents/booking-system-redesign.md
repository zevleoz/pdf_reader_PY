# 预约系统重构方案（Calendly 风格 + 管理员密码 + 自动建档）

## Context

当前预约系统存在四个问题：

1. **管理员可用性管理无密码保护** — `/admin/bookings` 任何人都能访问并修改 availability
2. **`admin_bookings.html`** **的 availability 加载是坏的** — `loadAvailability()` 调用 `/api/availability` 不带 `date` 参数，后端返回 400
3. **预约要填 email/phone** — 用户不需要这两个字段
4. **预约和档案脱节** — 当前流程是「预约 → 管理员手动点完成 → 才建 Student 档案」，用户希望预约时就自动建档，Y4 报告生成后能在档案页直接看到状态

目标：把预约流程改成 Calendly 风格、加管理员密码、预约即建档、档案页显示 Y4 状态。

***

## 改动清单

### 1. 数据库层 [db.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/db.py)

**模型变更（带迁移）：**

* `Student` 表新增 `advisor_name`、`school`、`single_parent` 字段（复用现有 `_migrate_schema()` 机制，加 ALTER TABLE）

* `Booking` 表新增 `student_id` 外键字段（`ForeignKey("students.id")`，nullable=True 兼容旧数据）

**CRUD 变更：**

* `find_or_create_student()` 扩展：接受 `advisor_name`、`school`、`single_parent` 参数；找到已有学生时也更新这些字段

* `add_booking()` 修改：接受 `student_id` 参数；去掉 `student_email`、`student_phone` 的必填性（保留字段兼容旧数据）

* 新增 `create_booking_with_student()`：事务内同时创建 Student + Booking，把 `student_id` 写回 Booking

* `get_bookings()` 修改：JOIN Student 表，返回 `student_id` 和 `report_count`（该学生的报告数）

* `complete_booking()` 简化：不再创建 Student（预约时已建），只更新 status='completed'

* 新增 `get_availability_range(start_date, end_date)`：返回日期范围内的所有 availability 记录（修复 admin 页面加载一周数据的需求）

### 2. 后端路由 [app.py](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py)

**管理员认证（新增）：**

* 读取 `ADMIN_PASSWORD` 环境变量，默认值 `y4admin2026`

* 新增 `admin_required` 装饰器：检查 `session.get('is_admin')`，非管理员返回 403

* 新增 `POST /api/admin/login`：接收 `{password}`，验证正确则 `session['is_admin']=True`，返回 `{ok:true}`

* 新增 `POST /api/admin/logout`：清除 session

**可用性管理（修复 + 加权限）：**

* `POST /api/availability` 加 `@admin_required` 装饰器 — 学生不能改可用性

* `GET /api/availability` 保持公开（学生预约时需要查）— 但去掉「默认全部可用」的逻辑，改为「无记录=不可用」（Calendly 行为：管理员不设置则无时段）

* 新增 `GET /api/availability/week`：返回从今天起 14 天内所有 availability 记录，供管理员页面一次性加载

**预约接口（简化）：**

* `POST /api/booking` 修改：不再接收 `student_email`、`student_phone`；调用 `create_booking_with_student()` 自动建档案

* `GET /api/bookings` 修改：返回每个 booking 的 `student_id` 和 `report_count`

* `POST /api/booking/<id>/complete` 简化：只更新状态，不创建 Student

**学生接口（补充信息）：**

* `GET /api/students` 修改：返回每个学生的 `advisor_name`、`school`、`latest_report_date`（最近一次报告日期，用于判断 Y4 是否已做）

### 3. 前端 — 预约页面 [booking.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/booking.html)

**Calendly 风格重写：**

* 去掉 email、phone 字段

* 左右两栏布局：

  * 左栏：日期选择器（原生 `<input type="date">` 或简易日历组件，限制只能选未来 14 天）

  * 右栏：选中日期后显示该日可用时间段（从 `/api/availability?date=` 拉取），无时段时显示「该日暂无可预约时间」

* 选完时间后，底部展开表单卡片：学生姓名\*、顾问名字、学校、单亲家庭复选框、备注

* 提交后显示成功页：预约详情 + 「可在学生档案页查看 Y4 进度」提示

* 保留 sessionStorage 持久化（日期、时间、表单数据）

### 4. 前端 — 管理员页面 [admin\_bookings.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/admin_bookings.html)

**密码登录：**

* 页面初始只显示密码输入框 + 登录按钮

* 调用 `POST /api/admin/login` 验证，成功后才显示管理界面

* 登录状态存 sessionStorage（避免刷新就退出）

**修复 availability 管理：**

* 用新的 `GET /api/availability/week` 一次性加载 14 天数据

* 按天分组显示，每个时间段可点击切换可用/不可用

* 保存按钮调用 `POST /api/availability`（现在带 session cookie）

**预约列表增强：**

* 每个 booking 显示「Y4 状态」列：`report_count > 0` 显示「✓ 已完成」绿色徽章，否则显示「未测评」灰色

### 5. 前端 — 学生档案页 [students.html](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/students.html)

**新增列：**

* 「Y4 状态」列：`latest_report_date` 存在显示「✓ 已完成（日期）」，否则「未测评」

* 「顾问」列：显示 `advisor_name`

* 「学校」列：显示 `school`

***

## 关键实现细节

### `create_booking_with_student()` 事务逻辑

```python
def create_booking_with_student(student_name, appointment_time, advisor_name="",
                                school="", single_parent="false", notes="") -> tuple[int, int]:
    """创建学生 + 预约，返回 (student_id, booking_id)。"""
    with Session(engine) as sess:
        # 1. 查找或创建学生
        existing = sess.execute(select(Student).where(Student.name == student_name)).first()
        if existing:
            student = existing[0]
            # 更新顾问/学校等信息
            sess.execute(update(Student).where(Student.id == student.id).values(
                advisor_name=advisor_name, school=school, single_parent=single_parent))
        else:
            result = sess.execute(insert(Student).values(
                name=student_name, advisor_name=advisor_name,
                school=school, single_parent=single_parent))
            student_id = result.lastrowid
        sess.flush()
        student_id = student.id if existing else student_id
        
        # 2. 创建预约并关联 student_id
        result = sess.execute(insert(Booking).values(
            student_name=student_name, student_id=student_id,
            appointment_time=appointment_time, status="pending",
            notes=notes, advisor_name=advisor_name,
            school=school, single_parent=single_parent))
        booking_id = result.lastrowid
        sess.commit()
        return student_id, booking_id
```

### `admin_required` 装饰器

```python
from functools import wraps
from flask import session, jsonify

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'y4admin2026')

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({"ok": False, "error": "需要管理员权限"}), 403
        return f(*args, **kwargs)
    return wrapper
```

### 可用性默认行为变更

当前 `GET /api/availability` 的逻辑是「无记录=可用」（`is_av = available_map.get(ts, True)`）。这不符合 Calendly 行为。改为：

```python
is_av = available_map.get(ts, False)  # 无记录=不可用
```

这样管理员不设置某天，学生就看不到任何时段。管理员必须主动开放时段才能被预约。

***

## 不改动的部分

* **PDF 生成逻辑**（`extract.py`、`validate.py`、`generate.py`、`data_points.py`）— 完全不碰

* **报告生成时的建档逻辑**（[app.py L262-281](file:///Users/jefflau/projects/pdf_report_converter/PDF_converter/app.py#L262-L281)）— 已有的 `find_or_create_student` + `add_report` 保持不变，会自动复用预约时创建的 Student 记录

* **会议纪要 DOCX 功能** — 不碰

* **`style.css`** **设计系统** — 复用现有样式，不新增 CSS 文件

***

## 验证方法

1. **管理员密码**：访问 `/admin/bookings`，未登录时只看到密码框；输入错误密码提示失败；输入正确密码后看到管理界面
2. **可用性管理**：管理员登录后设置某天几个时段为可用 → 退出登录 → 访问 `/booking` 选同一天 → 应该只看到管理员开放的时段
3. **预约流程**：填姓名+顾问+学校+选时间 → 提交 → 检查 `/students` 页面应该立刻看到这个学生（Y4 状态=未测评）
4. **Y4 状态联动**：对刚预约的学生去 `/generate` 上传 PDF 生成报告 → 回到 `/students` → 该学生的 Y4 状态应变成「已完成」
5. **权限隔离**：学生访问 `/admin/bookings` 被密码拦截；直接 POST `/api/availability` 返回 403

