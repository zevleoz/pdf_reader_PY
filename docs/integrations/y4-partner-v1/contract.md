# Y4 合作平台 API

本契约用于合作平台联调。示例中的平台、学生、预约和指标均为虚构。正式启用前，研究院与合作方需确认接收平台、对外共享授权方式及获准共享的 Y4 字段。[OpenAPI 契约及完整报文示例](openapi.yaml)

## 接入

合作方负责自己的用户登录。合作方后端通过 HTTPS 调用 `/api/partners/v1/y4`，请求携带 `Authorization: Bearer <服务令牌>`。查询时段和创建预约需要 `booking`。核对预约接受 `booking` 或 `results`。取结果需要 `results`。权限受合作方权限与令牌权限共同约束。API 响应禁用缓存。

运维通过 `Y4_PARTNERS_JSON` 或 `Y4_PARTNERS_FILE` 提供配置，二者择一。每条记录包含 `id`、`enabled`、`scopes`、`credentials`，可选 `name`。每个 `credentials` 项包含令牌的 SHA-256 小写十六进制摘要 `sha256` 与权限 `scopes`。可用 `secrets.token_urlsafe(32)` 生成服务令牌。启用结果通知时，为该合作方登记经审批的 HTTPS `callback_url` 和独立的 `webhook_secret`（32 至 256 字符）。配置文件应限制访问，可原子替换。轮换时可以同时启用新旧凭证，切换后移除旧凭证。停用合作方可撤销该方的服务访问。

| HTTP | 响应错误码 | 处理 |
| --- | --- | --- |
| 400 | `https_required` | 改用 HTTPS。 |
| 401 | `partner_auth_required` | 核对服务令牌或联系研究院确认凭证状态。 |
| 403 | `partner_scope_required` | 改用获授该操作权限的令牌。 |
| 503 | `partner_api_unavailable` | 退避后重试。持续出现时，由研究院核对配置。 |

## 预约

1. 用 `GET /availability?location_id=1&date=2026-12-08` 查询办公室及日期。日期窗口以北京时间为准，从明天至今天加 29 天。每个时段返回预约时间与可选状态。
2. 用 `POST /reservations` 提交。外部预约号和外部学生 ID 在合作方内独立，同名学生使用各自的外部学生 ID。预约时间使用带偏移量的时段。示例日期需替换为实际查询窗口内的日期。
3. 首次成功返回 `201`。请求超时后，用相同的外部预约号及内容重试，成功重放返回 `200`。若返回 `409 reservation_conflict`，先核对原请求。若返回 `409 slot_unavailable`，重新查询并选择时段。
4. 用 `GET /reservations/{id}` 核对研究院预约状态与时间。合作方只能读取自己创建的预约。时段容量与研究院站内预约共用。

```http
POST /api/partners/v1/y4/reservations
Host: institute.example
Authorization: Bearer example-only
Content-Type: application/json

{
  "external_reservation_id": "orchard-demo-001",
  "external_student_id": "orchard-student-001",
  "student_name": "Demo Student",
  "location_id": 1,
  "appointment_time": "2026-12-08T10:00:00+08:00"
}
```

```http
HTTP/1.1 201 Created
Content-Type: application/json

{
  "id": "5702e7e5-ccee-464f-8f4a-4361f99a7823",
  "external_reservation_id": "orchard-demo-001",
  "location_id": 1,
  "appointment_time": "2026-12-08T10:00:00+08:00",
  "confirmed_at": "2026-11-25T01:15:00+00:00",
  "status": "pending"
}
```

## 结果交付

研究院批准该轮测评向指定合作方共享后，合作方可以读取获准字段。通知发送至合作方预登记的 HTTPS 回调。通知携带事件 ID、双方预约标识和结果版本。

回调接收端按 `X-Y4-Event-Timestamp`（Unix 秒）、一个 ASCII 句点和请求体原始字节顺序拼接，用共享密钥计算 HMAC-SHA256。用恒定时间比较 `X-Y4-Event-Signature`（`sha256=<小写十六进制>`）。验证时间戳的新鲜度，并按 `event_id` 去重。重复投递可返回 `2xx` 确认。回调使用标准 HTTPS 端口，校验证书及公网地址。超时和非 `2xx` 响应触发重试，间隔从 30 秒指数增长，最大 3600 秒。同一事件重试沿用事件 ID。

通知体示例

```json
{
  "type": "y4.result.ready",
  "event_id": "4bfcc1d2807849009f4ab2e4d010ce30",
  "reservation_id": "5702e7e5-ccee-464f-8f4a-4361f99a7823",
  "external_reservation_id": "orchard-demo-001",
  "version": "d6494063e9784d838ccd3b44dd62624c"
}
```

收到通知后，取数后端用有 `results` 权限的令牌调用 `GET /reservations/{id}/results/{version}`。若漏收通知，可用有 `results` 权限的令牌查询预约中的 `current_result_version`。若当前无可共享版本，该字段为 `null`。取数时重新检查归属、就绪状态和当前授权。归属不符、未知版本、未就绪或授权撤回均返回 `404`。结果包括经批准的指标代码及值、单位或等级，可选测评日期。

```http
GET /api/partners/v1/y4/reservations/5702e7e5-ccee-464f-8f4a-4361f99a7823/results/d6494063e9784d838ccd3b44dd62624c
Host: institute.example
Authorization: Bearer example-results-only
```

```json
{
  "ok": true,
  "result": {
    "version": "d6494063e9784d838ccd3b44dd62624c",
    "assessment_date": "2026-12-08",
    "indicators": [{"code": "DEMO_INDICATOR", "value": 42, "unit": "points"}]
  }
}
```

## 研究院操作

管理员通过受登录及 CSRF 保护的 `POST /api/internal/partners/v1/y4/reservations/{id}/releases`，绑定合作方、预约、测评轮次和报告。请求携带管理员会话及对应的 `X-CSRF-Token`，合作方需要已登记有效回调。传入 `partner_id`、`round_id`、`report_id`、`approval_reference` 及按指标代码列出的 `fields`，按授权情况传 `include_assessment_date`。新批准返回 `201` 和版本。示例批准请求体如下，实际值以授权记录和该轮报告为准。

放行需要该轮已有未过期的正式成品记录，并有同一报告的解读会纪要。签约及对外共享仍由管理员按现行流程核对。批准引用应指向记录了接收方及字段范围的授权，服务在取数或发通知时复核当前状态。

```json
{
  "partner_id": "orchard-demo",
  "round_id": 104,
  "report_id": 205,
  "approval_reference": "demo-approval-01",
  "fields": {"DEMO_INDICATOR": ["value", "unit"]},
  "include_assessment_date": true
}
```

使用同一未撤回的批准引用及相同内容重试返回 `200`。每条预约首次批准后关联至该测评轮次，后续版本沿用该轮次。撤回使用 `DELETE /api/internal/partners/v1/y4/reservations/{id}/releases/{version}`，请求体包含 `partner_id`。

由运维周期执行 `flask --app app partner-y4-deliver` 发送待发事件。每次默认最多处理 25 个事件，可用 `--limit` 在 1 至 1000 范围内调整，命令输出处理总数。正式接入获批后再启用调度。发送前再次复核当前授权。已开始发送的通知无法召回，授权撤回后取数接口随即拒绝读取。

## 联调记录

使用隔离 SQLite 和两个虚构合作方联调。两名同名学生分别预约并分配测评师，管理员按预约和测评轮次批准字段，合作方读取各自的版本。检查了同一请求重放、同号不同内容冲突、站内与合作方抢最后一个名额、跨平台读取、缺解读纪要、同生多轮隔离、同轮历史版本、回调超时重试及授权撤回。回调通过模拟接收端验证，签名、地址限制和重定向拒绝有单独测试。

Chromium 走查确认合作来源在工作台及档案可见，点击分配后保存到同一学生，刷新可复查。F 基线的 SQLite 副本经初始化后，学生、预约和 Y4 既有记录保持一致。新旧代码下载同一只读测试件，默认版和显式旧版字节一致。

在 G 工作树中复跑接口联调和基础回归。仓库的 pytest 配置使用临时数据库。

```sh
env -u DATABASE_URL TZ=Asia/Shanghai python -m pytest -q -rs \
  test_partner_auth.py test_partner_reservations.py test_partner_results.py test_partner_y4_integration.py \
  test_y4_upload.py test_render_v2_slots.py test_profiling_workbench_api.py test_profiling_profile_api.py \
  test_six_am_v06_api.py test_s5_booking.py test_s5_booking_handoff.py test_student_questionnaire_ui.py \
  test_profiling_api.py test_questionnaire_scoring.py test_nav_flow.py test_reliability.py \
  test_m1_boot.py test_m1_pages.py test_login_platforms.py
npm --prefix frontend run build
```

回归结果为 274 项通过、15 个子测试通过。四项题库用例因当前检出缺少种子数据而跳过。前端构建通过。

正式接收方、授权方式和字段清单待确认。真实合作方回调及 PostgreSQL 尚未联调。
