# Junction 2026-09-24 跨项目数据交换

状态：`1.0.0` 历史业务契约保留为兼容基线。身份中心映射另见 `junction.identity_directory.1.0.0`。唯一真源为本目录的正文、Schema 和示例。历史 `junctionStudentId` 继续原样传递；身份中心新规则见 [identity-directory.contract.md](identity-directory.contract.md)。

架构演进说明（2026-09-24）：本轮业务讨论确认了服务任务与合同权益的分离。各系统的本地签署事实由该系统自身负责；Yuguo 的合同方案确认及签署全过程在 Yuguo 内完成，不依赖 CRM、First Touch、Junction 或其他系统的审核。CRM 仍可管理其自身合同/权益生命周期。现有 `1.0.0` 保留为当前兼容基线；在真实实现其他规划能力前，应发布下一版契约，不能把下述规划字段直接写入 `1.0.0` Schema。

| 协议 | 生产者 | 消费者 | 载荷 |
| --- | --- | --- | --- |
| `junction.identity_directory.1.0.0` | Junction Identity Center | 人工刷新后的业务系统 | [正文](identity-directory.contract.md)、[Schema](identity-directory.schema.json)、[示例](identity-directory.example.json) |
| `junction.crm_student_handoff.1.0.0` | 独立销售 CRM | Yuguo、First Touch、Activity Hub、Arkitect | [Schema](crm-student-handoff.schema.json)、[示例](crm-student-handoff.example.json) |
| `junction.identity_link.1.0.0` | CRM 身份管理 | 同上 | [Schema](identity-link.schema.json)、[示例](identity-link.example.json) |
| `first_touch.confirmed_facts.1.0.0` | First Touch | 授权的 Yuguo、Activity Hub、Arkitect | [Schema](first-touch-confirmed-facts.schema.json)、[示例](first-touch-confirmed-facts.example.json) |
| `activity_hub.service_result.1.0.0` | Activity Hub | 授权的 Arkitect、Yuguo | [Schema](activity-hub-service-result.schema.json)、[示例](activity-hub-service-result.example.json) |
| `activity_hub.admissions_support_materials.1.0.0` | Activity Hub | 授权的 Arkitect | [正文](activity-hub-admissions-support-materials/contract.md)、[Schema](activity-hub-admissions-support-materials.schema.json)、[示例](activity-hub-admissions-support-materials.example.json) |

## 共同约束

- 接收前验证精确协议标识、Schema、调用方服务身份、`authorization` 的 CRM/授权服务真实记录及当前有效性、接收者与目的，再校验 `junctionStudentId` 存在且未停用。`recipient`、`service` 和 `purpose` 是可扩展的不透明标识；Schema 不按系统名称静态推导组合。授权可用可选的 `capabilities.scope` 与 `capabilities.actions` 表达数据范围和动作，接收端仍必须依据真实授权、服务分配、合同权益和任务上下文判断组合是否获准。载荷中的授权声明不是独立凭证；鉴权仅服务端进行，最小权限，不在日志写联系人、原始证据或密钥。授权撤销后停止新交接；已保存历史依保留政策限制访问。
- 每个事件以 `source.system + source.recordId + revision` 标识不可变来源版本；`idempotencyKey` 在生产者命名空间内稳定。相同键、相同规范化载荷哈希返回原接收结果，不新建版本；同键异内容或同来源版本异内容返回冲突。规范化哈希实现须由对接双方明确约定，不能把空白差异当成新内容。更高 `revision` 保留旧快照，不覆盖已确认判断；过期版本可读取但不得回退当前版本。跨字段唯一性、哈希与授权由接收端验证，JSON Schema 不能代替。
- `sourceRef` 为可追溯引用，不要求消费者解析内部数据库格式。原始会议、隐私日记、测评原始数据、完整项目工作库不通过本协议传输。`confirmedAt`、`confirmedBy` 是生产者业务确认，不等于 Arkitect 策略确认。
- 传输可用授权的 API 或受控文件交接，具体路由和凭证由双方实施时另定，不从文档示例推断已接通。成功首次接收可返回 `202`，同内容重复返回 `200`；结构/不支持版本 `400/422`，认证失败 `401`，授权不足/撤销 `403`，未知学生/来源 `404`，身份映射或内容冲突 `409`，限流/暂时失败 `429/5xx`。仅超时、限流和 `5xx` 可原键重试；其他错误须修正或人工核验。错误响应至少包含稳定 `code`、`message`、`path`（JSON Pointer，可为空）和 `correlationId`，不泄露敏感载荷。
- 以 `junctionStudentId` 匹配；姓名、学校、年级、联系人手机号仅为资料或人工核验线索，绝不可自动合并兄弟姐妹/双胞胎。各项目保留自己的本地主键。未核验映射不得因其他字段相似而自动升级为已核验。

## 1.1.0 必须补齐的服务生命周期语义（规划）

### 学生与预约传输（1.1.0 增量）

`junction.student_delivery.1.1.0` 是最小交付信封，独立于仍保持兼容的 `crm_student_handoff.1.0.0`。Yuguo 是预约事件生产者，向 CRM 单向发送创建、改期和取消事件；CRM 是预约事件接收方，不得借此写入 Yuguo。预约使用 `recipient: "sales_crm"`、稳定 `taskId`、严格递增的修订号，创建/改期为 `scheduled`，取消为 `cancelled`。预约消息必须携带 `nativeStudentId`；若 Yuguo 尚未保存经核验的统一 ID，`junctionStudentId` 为 `null`，不得伪造统一 ID。CRM 只能使用预先核验的本地映射或统一 ID 定位学生，不得按姓名或电话匹配。 同一 `messageId` 与相同规范化载荷返回原回执；相同 ID 不同内容返回 409。超时、429、5xx 可使用原幂等键重试；400、401、403、404、409 不得盲目重试。回执至少包含 `{messageId, junctionStudentId, recipient, status: "accepted", studentId, revision}`。预约交付仅包含接收方处理预约所需的最少字段，不代表合同权益或签署批准。

该协议中的 CRM → 服务系统 `student` 交付仍由 CRM 作为生产者，兼容既有 `active/revoked` 语义；Yuguo → CRM 的预约交付是单向的独立方向。认证使用专用服务凭证，所有响应禁用缓存。Yuguo 不开放由 CRM 创建、修改或取消本地预约的能力。

HTTP 接口为 `GET /api/integrations/crm/teachers` 和 `POST /api/integrations/crm/deliveries`，使用至少 32 字符的独立共享服务令牌。400/401/403/409 均不可盲目重试，超时及 5xx 可用原消息重试；每次发送前 CRM 应再次确认授权、有效期和当前老师。接收端不能仅凭姓名、电话或学校匹配本地学生。

### 服务任务不是合同权益

`assignment` 在下一版中应明确表示一个可独立接收、执行、确认和关闭的服务任务实例，而不是某个系统的永久开关。至少需要增加或重新定义：

- `assignmentId`：服务任务实例的稳定 ID；同一学生可以有多个同类实例。
- `service`：执行系统或服务提供方的不透明标识。已有 `yuguo`、`first_touch`、`activity_hub`、`arkitect` 值继续有效；实现不得把它们当成封闭列表，Y4 或其他并列服务可使用新的稳定标识。
- `taskCode`：系统内可识别的任务类型，例如 `profiling`、`growth_talk`、`assessment` 或 `ongoing_support`。
- `phase`：下一版服务任务字段中的可扩展阶段标识；建议使用 `pre_contract` 或 `post_contract`，但同一个服务可以出现在多个阶段。1.0.0 未携带该字段。
- `status`：至少区分 `pending`、`accepted`、`in_progress`、`completed`、`rejected`、`revoked`。
- `assigneeRef`：负责人或外部目录引用，不复制业务系统的完整人员目录。
- `contractEntitlementId`：仅对签约后任务引用已激活的合同权益；签约前任务不得伪造该字段。

因此，接收端不能再按 `(junctionStudentId, service)` 覆盖唯一任务，也不能因“服务已分配”推断学生已签约。`Y4`、`First Touch` 和 `Yuguo` 均可由 CRM 分配签约前任务，也可在合同激活后分配签约后任务。

### CRM 自身合同状态与权益激活

下一版可增加 CRM 作为生产者的 CRM 侧合同生命周期协议，至少表达：

```text
draft → pending_signature → signed / declined / expired / cancelled
```

合同项目应引用将要激活的服务权益，但“签约前服务结果”本身不自动成为合同权益。CRM 可以依据其自己的 `signed` 和 `activated` 状态发送 CRM 侧签约后服务开通事件；该状态只约束 CRM 管理的权益，不是 Yuguo 合同方案确认或签署的前置审核、批准，也不撤销 Yuguo 内部签署记录。

各系统可以使用外部电子签名服务作为自己的实现适配器，但任何外部签名/审核服务都不是 Yuguo 完成签署操作的审批门槛。Yuguo 在自身系统内记录签署操作；其他系统是否接收 CRM 签署/权益激活结果，不改变该本地事实。

### 结果必须可追溯到服务任务

`first_touch.confirmed_facts`、`activity_hub.service_result` 以及未来的 Y4 结果协议，在下一版应增加 `assignmentId`（必要时增加 `taskCode` 和 `phase`），使接收方能够区分：

- 同一系统对同一学生的签约前任务和签约后任务；
- 同一模块的不同服务周期或不同负责人；
- 哪个结果参与了当前合同方案，哪个结果属于已激活权益后的交付。

结果协议仍只传递确认后的最小必要事实，不把各系统的原始工作库变成 CRM 的数据库。

### 授权目的不能永久绑定接收方

现行 `1.0.0` 保留 `recipient`、`purpose` 两个必填字段及既有值，且继续兼容既有示例；本修订移除 Arkitect/其他接收方之间的静态组合限制，并允许新的小写标识。授权目的按服务任务/合同用途声明，而不是永久按系统名称推导；能力范围和动作可通过可选 `capabilities` 扩展。接收端仍须对用途、阶段、合同权益和当前授权逐项校验。`phase` 仍属于下一版服务任务语义，未加入 1.0.0 载荷。

## CRM 建档、分配与基本信息

CRM 为所有**新学生**创建主档并签发统一 ID。`student` 是 CRM 所知的最小基础资料，`assignments` 表示服务分配和生效状态，不等于消费端账户已创建、已签约或自动授权全部数据。`assignmentVersion` 对单个服务分配单调递增，`revision` 对 CRM 主档事件单调递增；撤销/重派必须发新版本，接收端不能从缺席项推断删除。接收方校验授权接收者和服务分配，幂等 upsert 本地映射后再开放服务。可空信息不得虚构。任何服务的开案都应由对应稳定的 `service` 分配和真实授权共同驱动；一个服务不能因另一个服务开案而自动开通。

`identityLinkIds` 仅引用已核验映射，不承载本地 ID 细节。历史 Yuguo/First Touch/Activity Hub/Arkitect ID 通过独立 `identity_link` 事件提供；CRM ID 不从任一旧 ID 计算。每条链接包含命名空间、本地学生 ID、审核人/时间/证据引用和状态。一个 `(external.system, external.studentId)` 只能指向一个统一 ID；一个统一 ID 在同一命名空间若有多个旧记录，需要逐条人工审查并记录理由。冲突不得自动改绑。撤销链接用同一 `linkId` 更高版本，旧映射可读但不再用于新事件路由。CRM 不存在时，历史业务仍可沿旧链路读取，但新协议的生产者不能临时自造统一 ID。

## First Touch 确认事实

只发送已确认报告的不可变事实版本。每条事实有类型、原文/简述、证据引用及确认状态；兴趣和学术观察是事实而非申请方向。禁止 Pathway 枚举、P1–P7 评分、申请专业或最终策略字段；接收端发现此类扩展字段按 Schema 拒收。报告修订发更高版本，不原地改写历史 `first-touch.report.v1`。First Touch → Activity Hub `first_touch.activity_hub_import.2.1.0` 的文件导入继续按其原有 First Touch ID/人工绑定规则运行；迁移期只有经 `identity_link` 核验后才把旧记录关联统一 ID，不直接替换旧文件的 `student.studentId`。

First Touch 内部用于顾问工作流的辅助标记（例如 `specialFocus`）不属于 `first_touch.confirmed_facts.1.0.0` 的公共确认事实。除非未来明确设计兼容字段并发布新版本契约，否则不得把它作为跨项目输入读取、解释或据此触发 Pathway/服务决策。First Touch → Activity Hub 的 `first_touch.activity_hub_import.3.0.0` API 也属于独立的项目间协议，不是 `junction-2026` 的替代版本；其字段和生命周期以自身 canonical contract 为准。

## Activity Hub 服务进程与项目结果

Activity Hub 只保留学术力和行动力的工作过程；学习力由不属于 Activity Hub 维护范围的外部 E4 系统负责。`module` 指明 Activity Hub 的学术力或行动力服务线；`progress` 仅含已确认周期目标、状态和观察；`projectResults` 是已确认项目结果和证据引用，可为空。Activity Hub 输出不自行下申请竞争力结论。内部咨询原文、任务草稿、未确认项目、未经授权的敏感资料不交换。一个来源报告的更高版本触发消费者复核，不能静默改写 Arkitect 的策略版本。

### 升学优势支持素材包

`activity_hub.admissions_support_materials.1.0.0` 是 Activity Hub 将已确认项目事实、项目级定性评价、来源记录和 provenance 汇总给 Arkitect 的学生级不可变快照。它不包含项目 Stage、Pathway、School Leverage、申请评分或最终策略。当前协议已定义但尚未部署；Activity Hub 现有本地支持素材包只能作为内部快照能力，不能伪造 CRM 签发的 `junctionStudentId`、授权信封或 Arkitect 生产接收记录。

## Arkitect 接收边界

各接收方只接收已分配且经真实授权记录允许的载荷，保存来源协议、来源 ID、版本、确认人、接收时间、哈希与历史快照。Arkitect 当前申请策略场景可使用 `application_strategy`，但不能仅由接收方名称推断；Yuguo、Y4、First Touch、Activity Hub 和其他并列服务同理。新来源版本进入待复核状态；来源撤销/冲突须阻止新的自动摄入并标示已有决策所依赖的旧来源，不删除历史审计。

Arkitect 自己维护的策略会议记录、可选阶段性体验卡、校内成绩和标化成绩属于 Arkitect 服务进程的本地业务数据；它们当前不是 `junction-2026` 的公共交换载荷，也不应被伪装成 First Touch、Activity Hub 或 CRM 的结果。若未来需要让其他项目消费这些数据，应另行定义生产者、授权目的、最小字段和版本化协议。Arkitect 可以使用本契约接收 CRM 主档、First Touch 确认事实和 Activity Hub 已确认结果，但接收这些结果不改变其对申请策略、Pathway 和本地策略记录的责任边界。

Y4、家长 Profiling 和情报类输入本轮仅能以 `Mock` 明示来源供界面/测试，不得使用本协议的真实生产者名、伪造确认人与授权，也不得声称已经接通真实系统。本轮不定义这些来源的真实接口。

## 兼容与迁移顺序

1. 发布本仓库 1.0.0 Schema、示例、registry 和同步清单，消费者同步只读快照并先实现双读；不要把契约发布误报为已部署。
2. CRM 上线真实建档与统一 ID；盘点旧系统主键，经人工核验逐条建 `identity_link`，保留原主键/原报告。完成冲突审查前旧档仍走旧服务流程。
3. 各消费端实现授权校验、幂等与版本快照，然后启用 CRM 分配；只有端到端成功后才将**新学生**入口切换到 CRM。Yuguo 的现有服务不拆。
4. First Touch 输出确认事实，Activity Hub 输出确认进程/项目结果；Arkitect 最后接收并复核策略。检查旧 `yuguo.first_touch.integration`、`first-touch.report.v1`、`first_touch.activity_hub_import.2.1.0` 持续可读。旧格式不自动升级为新载荷，需经明确适配、映射与授权。

本仓库无业务数据库/生产部署能力。上线状态、迁移应用、跨项目联调应由各业务项目分别报告。
