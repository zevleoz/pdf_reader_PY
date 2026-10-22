# First Touch 与 Yuguo 集成接口契约

> 状态：2026-10-17 当前实现契约。本文描述代码行为与部署要求；不代表生产数据库迁移或 Vercel 环境变量已经完成验证。
>
> 产品边界：本文只描述 Yuguo 适配器。Yuguo 不是 First Touch 的唯一学生来源或唯一报告消费者；深红导入和 Arkitect 报告接收尚未接入，必须使用各自独立的身份映射、契约、凭证和投递状态。

> 2026-09-24 迁移边界：本文的 Yuguo Student ID 仅是既有链路的本地/历史键。新学生由独立销售 CRM 建档并签发统一 `junctionStudentId`；旧键只能经 [`junction.identity_link.1.0.0`](../junction-2026/contract.md) 人工核验后关联，不能就地改名、按手机号推断或破坏旧报告可读性。新交接协议尚未部署，不改变本接口现有行为。

> 身份目录边界：[`junction.identity_directory.1.0.0`](../junction-2026/identity-directory.contract.md) 是由身份中心人工刷新后提供的无授权只读映射快照。Yuguo 可以读取并保留本地审查结果，但该快照不创建或修改 Yuguo 学生、老师、权限、分配、服务或报告，也不能替代 `identity_link` 的人工核验。

## 1. 系统边界

两套系统保持独立数据库，通过三条链路传输数据：

1. **老师目录**：First Touch 是老师账号主数据源，Yuguo 保存启用老师快照。
2. **学生导入与改派**：Yuguo 提供已确认分配及单调版本；First Touch 显式导入新学生，并按权威分配自动转交已导入的工作区。
3. **报告 finalize**：First Touch 保存不可变确认报告；finalize 即视为 First Touch 侧已推送。当前不自动向 Yuguo 发起报告请求。

在本 Yuguo 适配器内，跨系统学生身份使用 Yuguo Student ID（当前接口尚不传 `junctionStudentId`）。First Touch 仅通过已核验的 Yuguo 外部身份映射或相同的 Yuguo Student ID 定位本地学生；姓名、年级、学校和手机号只用于资料展示与校验，不推断历史工作区身份。不同 ID 的既有工作区须先人工核验并建立映射。该约束不适用于未来的深红或 Arkitect 适配器。

### 1.1 Yuguo 向 CRM 发送预约

Yuguo 是预约记录的权威来源，并在创建、改期和取消时通过已认证的 `POST /api/integrations/crm/deliveries` 单向向 CRM 发送最小必要预约信息。该接口只接受 Yuguo 产生的预约交付，不授权 CRM 写入 Yuguo 的学生、老师负责人、协作权限、模块、服务、报告、门户或预约，也不改变 Yuguo 内部权限。载荷、幂等、修订、回执和重试语义以 [`junction.student_delivery.1.1.0`](../junction-2026/student-delivery.schema.json) 及其正文为准。

合同方案确认、合同签署记录和 Yuguo 学生阶段更新均在 Yuguo 内完成，不依赖 CRM、First Touch、Junction 或任何其他外部系统的审核或批准。Yuguo 是其本地签署操作和记录的权威来源；CRM 可以独立维护自己的合同/权益生命周期，但其审核或状态不得成为 Yuguo 签署完成的前置条件。

## 2. 服务端配置

| 用途 | First Touch | Yuguo | 要求 |
| --- | --- | --- | --- |
| 老师目录 | `FIRST_TOUCH_DIRECTORY_TOKEN` | `FIRST_TOUCH_DIRECTORY_TOKEN` | 两边相同，至少 32 字符 |
| 学生读取与交接 | `YUGUO_STUDENT_READ_TOKEN` | `YUGUO_STUDENT_READ_TOKEN` | 两边相同，至少 32 字符 |

服务地址：

- First Touch 使用 `YUGUO_BASE_URL` 调用 Yuguo。
- Yuguo 使用 `FIRST_TOUCH_BASE_URL` 调用 First Touch 老师目录。
- Production 环境不得填写 `localhost`、`127.0.0.1` 或本机开发端口。

所有 token 只保存在服务端环境变量中，不得进入浏览器请求、前端环境变量或日志正文。

## 3. 老师目录

### 3.1 First Touch 提供启用老师

```http
GET /api/integrations/teachers
Authorization: Bearer <FIRST_TOUCH_DIRECTORY_TOKEN>
```

```json
{
  "teachers": [
    {
      "id": "first-touch-account-id",
      "name": "老师姓名",
      "email": "teacher@example.com"
    }
  ]
}
```

只返回启用的 `TEACHER` 账号。`id` 是 First Touch Account ID，也是学生分配使用的老师唯一标识。

### 3.2 First Touch 推送全量快照

First Touch 在老师注册、管理员创建老师、启停账号后执行 best-effort 推送，也保留人工同步入口：

```http
POST /api/integrations/teachers
Authorization: Bearer <FIRST_TOUCH_DIRECTORY_TOKEN>
```

First Touch 随后调用：

```http
PUT /api/integrations/first-touch/teachers
Authorization: Bearer <FIRST_TOUCH_DIRECTORY_TOKEN>
Content-Type: application/json
```

Yuguo 按老师 ID upsert，停用快照中遗漏的老师，并按规范化邮箱对账 `PENDING` 分配。推送失败不回滚 First Touch 的账号操作。

## 4. Yuguo 学生导出

```http
GET /api/integrations/first-touch/students
Authorization: Bearer <YUGUO_STUDENT_READ_TOKEN>
X-First-Touch-Teacher: <First Touch Account ID>
```

接口按学生 ID 导出已分配记录。学校和联系人手机号是可选资料，不再因为缺失或格式暂时不可用而阻断学生导入；无法满足 ID、姓名、年级或版本等结构要求的单条记录仍使用拒绝明细，其他学生继续返回：

```json
{
  "students": [
    {
      "id": "student-1",
      "name": "学生一",
      "grade": "G8",
      "school": "某某学校",
      "phone": "+8613800138000",
      "teacherId": "first-touch-account-id",
      "assignmentVersion": 1
    }
  ],
  "rejectedStudents": [
    {
      "id": "student-2",
      "name": "学生二",
      "reasonCode": "INVALID_STUDENT_FIELDS",
      "message": "学生基础字段不完整"
    }
  ],
  "summary": {
    "assigned": 2,
    "exportable": 1,
    "rejected": 1
  }
}
```

拒绝原因：

- `INVALID_STUDENT_FIELDS`

若多个学生共用同一 guardian/contact 手机号，所有学生都可以独立导出；手机号是主要家长/联系人字段，不是学生身份，也不会因共享而拒绝记录。有效手机号输出为 E.164；缺失或暂时无法规范化时输出 `null`，不阻断按学生 ID 导入。

空学生列表是正常成功响应。只有鉴权失败、接口不存在、整体响应损坏或服务不可用才使用 `401`、`404` 或 `503`。

## 5. First Touch 学生导入

浏览器只调用 First Touch 同源接口：

```http
POST /api/students/import-yuguo
Content-Type: application/json

{}
```

处理规则：

1. 使用当前登录老师的 First Touch Account ID 拉取学生。
2. 每个合法学生使用独立短事务创建、关联、刷新或识别为已存在。
3. 单条本地冲突或数据库错误不回滚其他学生。
4. 每个本地成功学生只完成本地 First Touch 导入，不创建后台交接任务。
5. Yuguo 不可用不删除或回滚 First Touch 学生。
6. 多个学生共享家长手机号时分别以学生 ID 导入；手机号不得用于自动合并或认领本地工作区。
7. 已核验 Yuguo 身份的已有工作区按当前已确认分配自动转交，不再因旧顾问归属单独报冲突；身份歧义、矛盾或过期源版本仍拒绝。

```json
{
  "localImport": {
    "status": "PARTIAL",
    "fetched": 10,
    "eligible": 8,
    "created": 3,
    "attached": 1,
    "refreshed": 2,
    "alreadyLocal": 2,
    "conflicts": 1,
    "rejected": 2
  },
  "rejectedStudents": [
    {
      "id": "student-9",
      "name": "学生九",
      "reasonCode": "MISSING_SCHOOL",
      "message": "缺少学校信息"
    },
    {
      "id": "student-10",
      "name": "学生十",
      "reasonCode": "LOCAL_CONFLICT",
      "message": "本地已有归属冲突，未覆盖现有学生"
    }
  ]
}
```

`localImport.status`：

- `COMPLETED`：所有可处理记录完成。
- `PARTIAL`：至少一条成功，同时存在上游拒绝、本地冲突或单条失败。
- `FAILED`：没有学生成功，且存在拒绝或失败。

本地成功时，页面应表达为“学生已导入 First Touch”，不能显示等待交接、自动投递或后台重试。

### 5.1 已导入工作区的自动改派（2026-10-17）

本节替代“宇果改派不改变 First Touch 本地负责人”的旧规则；仅适用于已导入、已核验 Yuguo 外部身份或历史导入标记的工作区，不适用于其他来源学生。

- First Touch 服务端使用现有学生读取 token，按启用导师 ID 读取既有导出接口。只有通过响应校验的 `teacherId` 和 `assignmentVersion` 才可作为改派依据；版本由 Yuguo 每次修改分配时单调递增。
- 已登录页面打开、恢复可见或在线期间约每 15 秒发起核对；同一服务进程合并短时间内请求。页面都关闭时无后台定时任务，下次打开再核对。未导入的新学生仍须显式导入。
- 转交在本地学生行锁下原子更新负责人、本地访问版本、会谈负责人和会谈/运行修订；保存上游分配版本与审计。过期版本或同版本不同老师不能回退已应用分配。
- 原始资料、会谈内容、分析及已确认报告原样保留，报告中的历史确认者不改写。原顾问失去普通访问，新顾问能继续原工作区；管理员既有审计权限不变。
- 原顾问下次在线核对会收到“学生访问权限已移除”弹窗；已读状态持久保存。当前浏览器对应聊天缓存清除；原有未完成请求仍须在写入前通过负责人/版本检查。
- 上游失败、未确认分配、记录缺失、身份歧义或目标导师不可用时不根据缺失结果猜测撤权，也不按姓名或手机号合并。显式学生导入复用同一改派规则。
- 复用既有 AuditLog 保存上游版本、前后负责人和通知已读事件；HTTP 导出字段不增加，无需两边数据库迁移。

## 6. First Touch 报告 finalize

确认报告时，First Touch 在同一个数据库事务中创建：

1. 不可变 `GrowthTalkReport`。
2. 确认审计记录。

事务提交后，报告状态为 `CONFIRMED`，并在 First Touch 内标记为 `FINALIZED`，语义上视为已推送。Yuguo 暂时不可用不会让报告确认失败，也不会产生待投递或失败状态。

报告仍可通过 First Touch 的 JSON/PDF 下载入口进行人工交接。历史 `first-touch.report.delivery.v1` envelope schema 保留在契约仓库中，仅用于兼容历史数据和未来显式集成设计，不代表当前会自动发送。

## 7. 历史报告投递契约（非当前自动流程）

以下内容仅保留用于读取历史数据、兼容未来明确批准的 Yuguo 报告接收实现，以及跨项目迁移设计。当前 First Touch 不创建 delivery task、不调用该接口、不配置报告 token、不运行 Cron，也不提供 outbox 重试入口。

历史投递请求格式：

```http
POST /api/integrations/first-touch/reports
Authorization: Bearer <FIRST_TOUCH_REPORT_TOKEN>
Idempotency-Key: first-touch-report:<reportId>:v<version>
Content-Type: application/json
```

```json
{
  "schema": "first-touch.report.delivery.v1",
  "deliveryId": "outbox-task-id",
  "sentAt": "2026-09-22T10:00:00.000Z",
  "report": {
    "schema": "first-touch.report.v1",
    "reportId": "report-id",
    "version": 1,
    "yuguoStudentId": "student-id",
    "status": "CONFIRMED"
  }
}
```

传输信封可以重试，内部 `first-touch.report.v1` 内容保持不可变。

## 8. Yuguo 报告接收（未来显式集成）

本节描述未来由产品明确启用的报告接收端，不属于当前 First Touch finalize 链路。当前版本不会自动产生本节请求；如果未来启用，必须单独约定接收端、凭证、幂等、授权和投递状态，并完成新的联调与部署检查。

Yuguo 接收端执行：

1. 验证独立 report token。
2. 验证 delivery schema、报告 schema、确认状态和幂等键。
3. 验证 `yuguoStudentId` 存在。
4. 计算报告内容哈希。
5. 保存原始报告到 `SourceMaterial`。
6. 创建 `FirstTouchReportInbox`，状态为 `PENDING_IMPORT`。

首次接收返回 `202`：

```json
{
  "status": "RECEIVED",
  "inboxId": "inbox-id",
  "receivedAt": "2026-09-22T10:00:01.000Z",
  "importedAt": null,
  "warnings": []
}
```

重复行为：

- 相同幂等键和相同内容：返回既有记录，`200`。
- 相同报告 ID/版本但内容不同：返回 `409`。
- 未知学生 ID：返回 `404`，不创建孤立报告。
- 姓名、年级或学校变化只产生 warning，不替代学生 ID，也不直接拒绝报告。
- 已导入的相同报告返回 `IMPORTED`，不重复覆盖。

待导入报告的 `SourceMaterial.externalStatus` 为 `PENDING_IMPORT`，不会参与当前 Profiling 来源选择。

## 9. Yuguo 待导入收件箱（未来显式集成）

本节仅适用于未来启用 Yuguo 报告接收后的待导入流程。它不是当前 First Touch 报告 finalize 的必经步骤。

```http
GET /api/students/{studentId}/first-touch-report-inbox
```

返回最近 50 条报告，包括报告版本、确认时间、摘要、接收时间、导入状态和最近错误。状态为：

- `PENDING_IMPORT`
- `IMPORTING`
- `IMPORTED`
- `REJECTED`

一键导入：

```http
POST /api/students/{studentId}/first-touch-report-inbox/{inboxId}/import
```

导入过程锁定记录，使用现有 First Touch 报告分析逻辑生成并验证结构化摘要，然后：

- 保存 `keyPointsConfirmed`。
- 更新当前学生的 `growthFocus`。
- 创建一条 `GrowthVersion`。
- 创建一条 `StrategyVersion`。
- 创建分析产物和审计记录。
- 将收件箱与来源状态标记为 `IMPORTED`。

不会自动覆盖：

- `potential`
- `interference`
- `planningFocus`
- 家庭背景与当前阻碍
- 完整 Profiling snapshot

重复点击返回已导入结果，不新增成长或策略版本。分析失败返回 `422`，恢复为 `PENDING_IMPORT`，保留最近错误并允许重试；现有画像保持不变。

原有手动 PDF/JSON 上传继续保留。

## 10. HTTP 失败分类

| 类型 | 示例 | 处理 |
| --- | --- | --- |
| `400/422` | 请求结构、schema、字段无效 | 修复数据或协议 |
| `401/403` | token 不一致或权限不足 | 修复 Production 环境变量 |
| `404` | 接口未部署或学生不存在 | 检查部署顺序和学生 ID |
| `409` | 交接未完整匹配、同版本内容冲突、重复操作冲突 | 人工检查后重试 |
| `408/429/5xx` | 超时、限流、服务暂时不可用 | 当前学生读取由用户稍后重试；未来显式报告接收由对应调用方定义重试 |

## 11. 当前上线顺序

1. 部署 First Touch 数据库迁移和学生导入更新。
2. 确认 First Touch Production 的 `YUGUO_BASE_URL` 是线上 Yuguo 域名，并配置目录与学生读取所需 token。
3. 用一个测试老师和测试学生完成真实链路：登录、学生导入、完成报告、finalize、下载 JSON/PDF。
4. 确认 finalize 在 Yuguo 不可用时仍能成功，并且页面显示“已 finalize · 视为已推送”。

迁移文件存在不等于生产数据库已迁移；本地测试通过也不等于 Vercel Production token 已生效。当前上线不需要 `FIRST_TOUCH_REPORT_TOKEN` 或 `CRON_SECRET`，也不需要 Vercel Cron。

## 12. 实现位置

First Touch：

- `app/api/students/import-yuguo/route.ts`
- `lib/reports.ts`
- `app/api/students/[id]/reports/route.ts`
- `prisma/schema.prisma`

历史兼容位置（当前代码已移除，不应作为当前上线步骤）：

- `lib/integration-outbox.ts`
- `app/api/internal/integrations/outbox/route.ts`
- `app/api/integrations/outbox/[id]/retry/route.ts`

Yuguo：

- `app/api/integrations/first-touch/students/route.ts`
- `lib/first-touch-student-dto.ts`
- `app/api/integrations/first-touch/reports/route.ts`
- `app/api/students/[id]/first-touch-report-inbox/route.ts`
- `app/api/students/[id]/first-touch-report-inbox/[inboxId]/import/route.ts`
- `lib/first-touch-report-inbox.ts`
- `lib/profiling.ts`
- `prisma/schema.prisma`
