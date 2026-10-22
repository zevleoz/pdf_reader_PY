# First Touch → Activity Hub API 画像协议

版本：`3.0.0`；协议标识：`first_touch.activity_hub_import.3.0.0`。

本协议取代顾问上传 `2.1.0` 文件的生产流程；旧文件及历史快照保留只读，不自动转为 3.0。它不属于 `first_touch.confirmed_facts.1.0.0`，也不签发 CRM `junctionStudentId`。

## 传输与身份

- Activity Hub 顾问点击拉取，服务端先向 Yuguo 实时确认该顾问绑定的活跃 `teacherId` 对该 `yuguoStudentId` 有 M5（行动力）分配，再以独立服务凭证向 First Touch 发起 `GET /api/integrations/activity-hub/students/{yuguoStudentId}/profile`。凭证和老师 ID 不交给浏览器。M3（学习力）和 M4（学术力）老师不因此获得 Activity Hub 访问权限。
- First Touch 必须按 `StudentExternalIdentity(sourceSystem=YUGUO, externalStudentId=yuguoStudentId)` 精确定位本地学生，再读取最新已确认的 `first-touch.report.v1`。报告载荷中旧字段 `yuguoStudentId` 不能作为身份映射的凭证。
- 响应按 [Schema](api-profile.schema.json) 校验，包含独立的 `yuguoStudentId` 与 `firstTouchStudentId`、不可变报告 ID/版本、学生基础资料、职业画像和兴趣象限。没有核验映射或确认报告则不返回画像；First Touch 不创建项目或返回会议正文。
- Yuguo 基础资料是 Activity Hub 的姓名、年级、学校、联系人真源；First Touch 的 `student` 仅作比对和追溯。First Touch 只更新职业画像与兴趣象限，保留 Activity Hub 的项目、会议、State 和历史快照。
- Activity Hub 预览不写入。提交时重新校验实时分配、上游版本、Schema 和跨字段规则，版本变化返回冲突；相同来源报告版本幂等，更新版本先按用户选项保存旧快照，再一次性提交。手机号不是匹配键，同胞可共享。身份冲突不得以姓名或手机号自动修复。

## 目录与权限 API

独立的服务端 Bearer 凭证分别用于 Yuguo、First Touch、Activity Hub 集成接口。所有响应 `Cache-Control: no-store`，不得记录密钥或联系人明文；网络超时和 5xx 不授予缓存权限。

| 服务 | 路由 | 语义 |
| --- | --- | --- |
| Yuguo | `GET /api/integrations/activity-hub/students?cursor=&limit=` | 分页返回所有学生的 ID、姓名、年级、学校、联系人及更新时间，仅供 Activity Hub 管理员的服务端目录读取。 |
| Yuguo | `GET /api/integrations/activity-hub/teachers` | 返回活跃 Teacher 的 ID、姓名、邮箱，供 Activity Hub 管理员建立一对一账号映射。 |
| Yuguo | `POST /api/integrations/activity-hub/access/check` | 接收 `teacherId` 和 `studentIds`，仅对活跃 Teacher、活跃 M5 分配返回 `allowedStudentIds`；每次读取、写入和附件访问实时查询。 |
| Activity Hub | `GET /api/integrations/yuguo/advisors` | 返回活跃顾问账号的 ID、姓名、邮箱及管理员核验绑定的 `yuguoTeacherId`。Yuguo 从目录选人后仍写入现有 `StudentModuleTeacherAssignment`。 |

顾问仅能访问有实时 M5 分配且已核验 Yuguo 映射的整个学生档案。M5 分配撤销、账号停用、映射冲突或权限服务不可用时一律拒绝；M3/M4-only 老师没有 Activity Hub 学生访问权。管理员可处理未核验的历史档案。服务端接口须同时进行调用方认证与授权，禁止信任客户端传入的老师 ID。

错误响应为 `{ "code": "...", "message": "...", "path": "", "correlationId": "..." }`；认证失败 `401`，权限不足 `403`，无记录 `404`，版本或身份冲突 `409`，无效结构 `422`，上游不可用 `503`。仅超时、限流及 5xx 可重试；错误信息不泄露其他学生资料。

## 后续统一 ID

本阶段 Yuguo ID、First Touch ID、Activity Hub ID 均以独立命名空间保存。只有 CRM 签发的 `junctionStudentId` 和经人工核验的 `junction.identity_link.1.0.0` 才能关联统一身份；Arkitect 导入和 CRM 生产对接不属于本协议。
