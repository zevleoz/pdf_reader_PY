# Y4 预约交付契约（外部系统 → Y4）

状态：已实现。实现以 `blueprints/integrations.py` 的 `POST /api/integrations/crm/deliveries`
为准；协议族为 `junction.student_delivery.1.1.0`（见
[`junction-2026/contract.md`](junction-2026/contract.md) 与
[`student-delivery.schema.json`](junction-2026/student-delivery.schema.json)）。

首个业务接入方是 Yuguo：Yuguo 产生预约事件，经 CRM 统一为
`junction.student_delivery.1.1.0` 后投递到本端点。Y4 不接受外部系统直接创建、
修改或取消本地预约；Y4 只保存预约镜像供顾问查看。

## 端点与鉴权

| 项 | 值 |
|---|---|
| 方法与路径 | `POST /api/integrations/crm/deliveries` |
| 认证 | `Authorization: Bearer <CRM_INTEGRATION_TOKEN>` |
| 令牌要求 | 至少 32 字符的独立共享服务令牌，与导师目录令牌分开 |
| 未配置令牌 | 返回 `401 {"message": "Unauthorized"}`（不暴露配置状态） |
| 缓存 | 所有响应禁用缓存 |
| 请求体 | JSON；`Content-Type: application/json` |

## 信封字段

必填：`schema`（固定 `junction.student_delivery.1.1.0`）、`recipient`
（固定 `first_touch`）、`kind`（`student` / `appointment`）、`messageId`、
`junctionStudentId`、`teacherId`、`revision`（≥1 的整数）、`issuedAt`、
`expiresAt`、`authorization`。

`authorization` 必填 `grantId`、`purpose`（固定 `service_delivery`）、
`grantedAt`，可选 `expiresAt`。载荷中的授权声明不是独立凭证，接收端仍按
真实授权记录判断。

`kind=appointment` 时，订单字段位于 `appointment`：`taskId`、`startAt`、
`endAt`（ISO 8601，且 `endAt > startAt`），`status` 为 `scheduled` 或
`cancelled`。1.1.0 Schema 将 appointment 的 `recipient` 固定为 `sales_crm`；
Y4 实现按本系统语义接受 `recipient: "first_touch"`，仅在 Schema 校验时做归一，
业务语义仍是 Y4 预约交付。

`kind=student` 时，`status` 为 `active` 或 `revoked`；`active` 必填
`student.name`，可选 `grade`、`school`、`contactPhone`、`guardianName`。

## 定位与匹配

- 只按 `junctionStudentId`（`external_identities(source_system="junction")`）定位本地学生。
- 绝不按姓名、学校、年级或电话自动匹配，避免双胞胎/兄弟姐妹误合并。
- 首次 `active` 投递会建档并写映射；`revoked` 要求映射已存在。
- `teacherId` 必须是本平台启用中的 advisor；找不到返回 `422`，不落库。

## 幂等与版本

- 幂等键：`messageId`。相同 `messageId` + 相同规范化载荷（SHA-256，JSON 键排序、
  无多余空白）返回原回执，不重复写库。
- 相同 `messageId` + 不同载荷返回 `409 {"message": "Message ID conflict"}`。
- 预约 `revision` 必须严格递增；不大于当前值返回
  `409 {"message": "Stale appointment revision"}`。
- 学生交付 `revision` 必须严格递增；不大于当前值返回
  `409 {"message": "Stale CRM student revision"}`。
- 取消未知预约返回 `409 {"message": "Unknown appointment to cancel"}`。
- 过期交付（`expiresAt` 或授权 `expiresAt` 已过）返回
  `400 {"message": "Expired CRM delivery"}`；预约已开始后不能再 `scheduled`，
  返回 `400 {"message": "Appointment has already started"}`。

## 成功回执

```json
{
  "messageId": "msg-20261022-001",
  "junctionStudentId": "junc-stu-001",
  "recipient": "first_touch",
  "status": "accepted",
  "revision": 3,
  "studentId": 128
}
```

`studentId` 是 Y4 本地学生主键，仅用于回执关联；外部系统不得据此反推其他接口。

## 失败分类与重试

| 状态码 | 含义 | 是否可原消息重试 |
|---|---|---|
| `400` | Schema/语义校验失败、授权或交付过期、预约时间非法 | 否，修正载荷 |
| `401` | Bearer 令牌缺失或不匹配 | 否，先修凭证 |
| `409` | `messageId` 冲突、revision 过期、未知预约/学生、身份不可用 | 否，人工核对 |
| `422` | 指定 `teacherId` 不是启用中的 advisor | 否，先同步导师目录 |
| `429` | 协议保留的限流响应；当前投递端点未启用限流 | 如遇上游网关返回，可退避后原 `messageId` 重试 |
| `500` | 未识别异常（不泄露内部细节） | 可重试 |
| `503` | 事务无法完成（锁冲突重试 3 次仍失败） | 是，原 `messageId` 重试 |

超时按 `5xx` 处理，使用原 `messageId` 重试；`400/401/409/422` 不得盲目重试。

## 与导师目录的关系

Yuguo 同步导师目录使用独立端点 `GET /api/integrations/teachers`
（Bearer `FIRST_TOUCH_DIRECTORY_TOKEN`），仅返回启用中的 advisor
（`id`、`name`、`email`），同样禁用缓存。预约投递中的 `teacherId`
必须是该目录中存在的 `id`。

## 最小载荷原则

交付只携带接收方处理预约所需的最少字段，不包含合同权益、签署状态、
会议原文或测评原始数据。收到预约不代表签约、权益激活或服务结果确认。
