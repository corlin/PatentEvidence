# PatentEvidence MVP 实施规格（草案）

状态：待最终确认  
目标市场：中国大陆专利代理机构  
商业模式：面向机构的多租户 SaaS，平台管理员人工开通  
首个付费闭环：专利检索与可专利性预评估  

## 1. 产品结论

PatentEvidence 不定位为“自动写专利”，而定位为代理师的检索、证据整理和预评估工作台。

首版输入一份技术交底书或专利申请稿，输出一份经过人工复核、可追溯到原始文献证据的《可专利性预评估报告》。系统负责减少机械工作，最终专业结论仍由代理师确认。

### 1.1 目标客户

- 购买者：5–50 人规模的专利代理机构负责人或业务主管。
- 主要用户：专利代理师、检索分析员、机构管理员。
- 平台运营者：一人创业公司的平台管理员。
- 首批销售方式：人工获客、人工演示、人工开通、按件或按月线下签约收款。

### 1.2 MVP 成功标准

一个匿名化真实案件能够完成：

1. 机构和用户由平台管理员创建。
2. 代理师上传 DOCX、PDF 或粘贴文本。
3. 系统提取技术问题、必要技术特征和候选检索词。
4. 代理师确认或修改检索策略。
5. 系统通过 EPO 和 USPTO 连接器获得文献；CNIPR 通过人工交接补证。
6. 系统生成逐特征证据矩阵及新颖性/创造性风险提示。
7. 独立复核人完成批准或退回修改。
8. 系统生成带证据定位、免责声明、版本号和校验值的 PDF/DOCX 报告。

首版业务指标：

- 单案人工时间不超过 4 小时。
- 试点阶段至少 3 家机构、每家至少 3 个真实案件。
- 有效文献引用必须 100% 能追溯到来源记录；禁止生成不存在的专利号或引文。
- 跨机构数据访问测试必须 100% 被拒绝。
- 报告只能在人工复核通过后标记为“已批准”。

## 2. 明确的 MVP 范围

### 2.1 必须交付

- 平台管理员创建、暂停和到期处理机构。
- 机构管理员邀请用户、分配角色、查看配额。
- 机构、项目、案件级权限隔离。
- 案件创建、文档上传、解析文本预览和敏感信息提示。
- 技术特征提取及人工编辑、版本确认。
- 检索策略生成、人工确认、可恢复的检索任务。
- EPO 自动检索适配器。
- USPTO 自动检索适配器，但 API Key 必须按用户或获授权主体分别配置。
- CNIPR 单条记录人工交接流程，不做后台爬取。
- 文献去重、同族归并、基础法律状态信息。
- 原文证据、定位信息、AI 判断、代理师判断分层保存。
- 新颖性风险、创造性组合风险和证据不足提示。
- 独立复核、退回修改、批准和交付。
- PDF/DOCX 报告、版本快照、审计日志。
- 机构级模型供应商配置和密钥隔离。

### 2.2 明确不做

- 公开注册、手机号自助注册和在线支付。
- 自动撰写完整说明书或权利要求。
- 审查意见答复和期限管理。
- 直接向 CNIPA 提交文件。
- CNIPR 批量、无头浏览器或未公开接口采集。
- 专利年费、商标、诉讼、无效或 FTO 完整法律意见。
- 开放式 Agent Hub、插件市场和复杂计费系统。
- 首版移动端 App。
- 首版向量数据库；案件量和召回需求得到验证后再评估 Qdrant。

## 3. 建议的最终仓库

建议仓库名：`PatentEvidence`  
建议本地路径：`/Users/corlin/2026/PatentEvidence`  
建议远端：新建独立私有商业仓库，初期不公开源代码。

不合并任何源项目的 Git 历史，不使用 Git submodule 作为生产运行依赖。所有复用均通过固定提交、来源清单、派生文件记录和测试夹具实现。

### 3.1 顶层目录

```text
PatentEvidence/
├── README.md
├── AGENTS.md
├── LICENSE                  # 商业仓库许可证，不覆盖第三方组件
├── pyproject.toml
├── package.json
├── pnpm-workspace.yaml
├── compose.yaml
├── .env.example
│
├── apps/
│   ├── api/                 # FastAPI：认证、领域 API、管理 API
│   ├── worker/              # 检索、分析、报告后台任务
│   └── web/                 # React + Vite 管理台和业务工作台
│
├── packages/
│   ├── contracts/           # OpenAPI 派生类型、枚举、JSON Schema
│   ├── ui/                  # 共享设计系统和权限感知组件
│   ├── report-kit/          # PDF/DOCX 模板、渲染和校验
│   └── provenance/          # 哈希、来源定位、快照工具
│
├── modules/
│   ├── platform/            # 机构、身份、角色、配额、供应商、审计
│   ├── cases/               # 案件、文档、版本、对象存储
│   ├── feature-modeling/    # 技术特征提取、编辑、确认
│   ├── retrieval/           # 检索策略、任务、结果、同族与法律状态
│   ├── evidence/            # 特征×文献证据矩阵
│   ├── assessment/          # 新颖性/创造性预评估和不确定性
│   ├── review/              # 提交、指派、批准、退回与修订
│   └── delivery/            # 报告任务、工件、下载授权
│
├── adapters/
│   ├── llm/                 # OpenAI 兼容接口；不暴露供应商密钥
│   ├── epo/                 # epo-cli 固定版本调用与结果归一化
│   ├── uspto/               # uspto-cli 固定版本调用与用户密钥绑定
│   ├── cnipr-handoff/       # 人工浏览器交接契约和单条补证导入
│   ├── object-storage/      # S3 兼容对象存储
│   └── secret-store/        # 开发、本地和生产密钥存储实现
│
├── db/
│   ├── migrations/
│   ├── seeds/
│   └── policies/            # RLS、数据库角色和权限验证
│
├── prompts/
│   ├── feature-extraction/
│   ├── search-strategy/
│   ├── evidence-analysis/
│   └── assessment/
│
├── templates/
│   └── reports/
│       ├── zh-CN-default/
│       └── agency-custom/
│
├── provenance/
│   ├── sources.lock.json
│   ├── DERIVATION_POLICY.md
│   ├── FILE_MAP.md
│   └── THIRD_PARTY_NOTICES.md
│
├── fixtures/
│   ├── anonymized-cases/
│   ├── connector-responses/
│   └── golden-evidence/
│
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── security/
│   ├── e2e/
│   └── release-gates/
│
├── ops/
│   ├── docker/
│   ├── nginx/
│   ├── backup/
│   ├── monitoring/
│   └── runbooks/
│
├── scripts/
│   ├── bootstrap-platform-admin.py
│   ├── create-organization.py
│   ├── import-source-fixtures.py
│   ├── verify-source-lock.py
│   └── verify-release.py
│
└── docs/
    ├── architecture/
    ├── api/
    ├── compliance/
    ├── operations/
    ├── sales/
    └── validation/
```

## 4. 技术架构

### 4.1 技术栈

- Web：React 19、TypeScript、Vite。
- API：Python 3.12+、FastAPI、SQLAlchemy async、Alembic。
- Worker：与 API 共用 Python 领域包，独立进程运行任务；首版使用 PostgreSQL 持久任务表，不急于引入 Kafka。
- 数据库：PostgreSQL，强制 Row Level Security。
- 文件：S3 兼容对象存储；开发环境可用 MinIO。
- 报告：服务端生成 DOCX 和 PDF，并对最终文件计算 SHA-256。
- 部署：Docker Compose 起步，单台中国大陆云服务器即可；数据库和对象存储优先使用托管服务。
- 密钥：生产环境接入经过验证的云密钥服务；未配置时必须 fail closed。

### 4.2 进程边界

```text
Browser
  │ authenticated HTTPS
  ▼
Web ─────► API ─────► PostgreSQL/RLS
             │              │
             ├──────► Object Storage
             │
             └──────► Worker
                         ├── LLM adapter
                         ├── EPO adapter
                         ├── USPTO adapter
                         └── Report renderer

CNIPR：API 创建 handoff 任务 → 用户在可见浏览器操作 → 导入单条证据
```

API 是权限和业务状态的唯一入口。Worker 不接受浏览器传入的机构 ID 作为信任依据，而从持久任务记录恢复机构上下文。所有后台写入都必须设置数据库租户上下文并通过 RLS。

## 5. 领域模型

每张业务表必须包含 `organization_id`；项目内实体同时包含 `case_id`。核心实体如下：

| 领域 | 核心实体 | 关键约束 |
|---|---|---|
| 平台 | Organization、Membership、RoleGrant、PlanQuota、ProviderConfig | 仅平台管理员能开通机构；密钥正文不进数据库 |
| 案件 | Case、SourceDocument、DocumentVersion、ParseRun | 原文件与解析文本都有哈希和版本 |
| 特征 | FeatureSetVersion、TechnicalFeature、FeatureEdit | 检索只能绑定已确认的特征版本 |
| 检索 | SearchStrategyVersion、SearchExecution、SourceResult、Literature、FamilyFact、LegalStatusFact | 任务可恢复；原始结果不可被 AI 覆盖 |
| 证据 | EvidenceBatch、EvidenceMapping、EvidenceCitation、AISnapshot、AnalystValue | 原文、AI、人工值分层且追加式保存 |
| 评估 | AssessmentVersion、NoveltyFinding、CombinationFinding、Uncertainty | 结论必须引用证据映射版本 |
| 复核 | ReviewSubmission、ReviewAssignment、ReviewDecision、Correction | 提交者不能批准自己的版本 |
| 交付 | DeliveryJob、DeliveryArtifact、DownloadGrant | 只有已批准版本可以生成正式交付物 |
| 审计 | AuditEvent、PlatformAuditEvent | 安全摘要，不保存密钥和全文敏感信息 |

### 5.1 角色

- `platform_admin`：开通机构、暂停机构、设置配额和到期日。
- `organization_admin`：管理本机构用户、案件权限和供应商配置。
- `patent_agent`：创建案件、编辑特征、确认策略、完成分析。
- `reviewer`：复核并批准或退回。

MVP 不设置复杂自定义角色。一个用户可以有多个角色，但正式报告必须由不同于提交人的用户批准。

### 5.2 关键状态机

```text
case:
draft → document_ready → features_confirmed → retrieval_ready
→ evidence_ready → assessment_ready → in_review
→ changes_requested → in_review
→ approved → delivered

analysis run:
queued → running → partial_success | completed | failed | cancelled

review:
draft → submitted → assigned → approved | changes_requested

delivery:
queued → rendering → validating → complete | failed
```

任何状态推进都由后端根据持久事实计算。前端不能只修改本地状态来伪造“完成”。

## 6. MVP 业务流程

### 6.1 平台管理员开通机构

1. 运行平台管理命令或内部管理页。
2. 创建机构、首位机构管理员、到期时间和月度案件配额。
3. 发送一次性邀请链接；首次登录必须改密码并启用 MFA。
4. 写入平台审计事件，不把临时密码写入日志。

首版不实现订单表。合同号和线下收款备注可作为机构管理字段，但不影响授权逻辑。

### 6.2 案件建立与文档导入

1. 用户创建案件并输入内部案号、标题、技术领域和目标法域。
2. 上传 DOCX/PDF，服务端执行 MIME、扩展名、大小和恶意文件检查。
3. 原文件存入 `org/{organization_id}/case/{case_id}/source/`。
4. Worker 解析正文、表格和图片引用，保存解析版本及 SHA-256。
5. 用户在预览页确认解析结果；解析错误可修订但不能覆盖原版本。
6. 脱敏为可选明确步骤，系统显示替换清单后由用户确认。

### 6.3 技术特征建模

1. LLM 提取技术问题、技术方案、必要技术特征、可选特征和效果。
2. 每个特征记录来源段落定位、AI 置信度和不确定性。
3. 代理师编辑、拆分、合并或删除特征。
4. 点击“确认特征版本”后生成不可变 `FeatureSetVersion`。
5. 后续修改必须生成新版本，并使旧检索策略标记为过期。

### 6.4 检索策略与执行

1. 系统根据确认的特征版本生成中英文关键词、同义词、CPC/IPC 候选和组合策略。
2. 代理师必须人工确认策略后才能执行。
3. Worker 并行调用 EPO 和 USPTO 适配器，但每个适配器独立记录状态。
4. 所有命令固定超时、退出码、版本和输入摘要；原始 JSON 作为不可变对象保存。
5. 单一数据源失败时任务进入 `partial_success`，不丢弃成功结果。
6. 文献按公开/申请号、同族关系和优先权归并；不把模型相似度作为权威同族判断。
7. 用户可创建 CNIPR handoff，从可见浏览器中核验并导入一条记录。

### 6.5 证据矩阵

矩阵行为：行是已确认技术特征，列是候选文献。

每个单元格分四层：

1. `source`：原文引文、页码/段落/权利要求定位、来源 URL。
2. `ai`：披露/部分披露/未披露判断、理由和不确定性。
3. `analyst`：代理师覆盖值、说明和操作者。
4. `review`：复核人最终确认。

系统不得把摘要或模型生成内容冒充原文。没有可验证原文时必须显示“证据不足”。

### 6.6 可专利性预评估

首版输出三类结果：

- 新颖性风险：是否存在单篇文献覆盖全部必要特征。
- 创造性组合风险：由代理师指定或系统建议的文献组合是否覆盖特征，以及组合动机是否需要人工确认。
- 证据完备度：来源覆盖率、未核验引用、数据源失败和法律状态时点。

AI 只能产生候选判断。每项结论必须带证据引用、假设、替代解释、不确定性和建议核验动作。

### 6.7 复核与交付

1. 代理师提交特征版本、文献集合版本、证据矩阵版本和评估版本。
2. 后端指派另一名复核人。
3. 复核人批准或退回；批准记录不可修改。
4. 修改必须创建后继版本并重新提交。
5. 正式报告只绑定已批准版本；报告包含版本 ID、生成时间和 SHA-256。
6. 下载 URL 短期有效并记录审计事件。

## 7. API 最小集合

```text
POST   /api/v1/platform/organizations
PATCH  /api/v1/platform/organizations/{orgId}
POST   /api/v1/organizations/{orgId}/invitations
GET    /api/v1/organizations/{orgId}/usage

POST   /api/v1/cases
GET    /api/v1/cases
GET    /api/v1/cases/{caseId}
POST   /api/v1/cases/{caseId}/documents
POST   /api/v1/cases/{caseId}/parse-runs

POST   /api/v1/cases/{caseId}/feature-runs
PUT    /api/v1/cases/{caseId}/feature-drafts/{draftId}
POST   /api/v1/cases/{caseId}/feature-versions/{versionId}/confirm

POST   /api/v1/cases/{caseId}/search-strategies
POST   /api/v1/cases/{caseId}/search-strategies/{id}/confirm
POST   /api/v1/cases/{caseId}/search-executions
GET    /api/v1/cases/{caseId}/search-executions/{id}

POST   /api/v1/cases/{caseId}/cnipr-handoffs
POST   /api/v1/cases/{caseId}/cnipr-handoffs/{id}/evidence

POST   /api/v1/cases/{caseId}/evidence-batches
GET    /api/v1/cases/{caseId}/evidence-matrix
POST   /api/v1/cases/{caseId}/analyst-values
POST   /api/v1/cases/{caseId}/assessments

POST   /api/v1/cases/{caseId}/review-submissions
POST   /api/v1/cases/{caseId}/review-submissions/{id}/decisions
POST   /api/v1/cases/{caseId}/deliveries
GET    /api/v1/cases/{caseId}/deliveries/{id}

GET    /api/v1/cases/{caseId}/workflow-state
GET    /api/v1/organizations/{orgId}/audit-events
```

所有写接口支持 `Idempotency-Key`。异步任务返回 `202` 和任务 ID；前端通过轮询恢复，SSE 仅作为体验增强。

## 8. 源项目复用与引用矩阵

| 源项目与固定提交 | 采用内容 | 集成方式 | 不直接采用的内容 |
|---|---|---|---|
| PatentQ `eb63654464e5` | 多机构身份、默认拒绝授权、RLS、审计、供应商治理、工作流数据模型 | 选择性移植并重构到新命名空间；补齐生产密钥存储 | 未验证完成的全产品业务面、Python 3.14 强绑定 |
| PatentForge `7b6067a9a570` | 文档解析、preflight run/evidence/finding/eval/confirmation、QA、Trace、DOCX 导出 | 依据接口重写/移植领域逻辑；SQLite 改 PostgreSQL | Next.js 业务壳、全量 Agent Hub、SQLite 存储、CNIPA 自动检索假设 |
| PatentScope `323ed05b6a14` | 阶段模型、ReviewDecision、离线检查和回归思路 | 作为契约、黄金夹具和测试参考，不作为生产依赖 | 本地 SQLite/静态前端整体运行时 |
| PatentDraw `6a0801f43be9` | 不可变候选、哈希指纹、陈旧版本冲突、双人审批、受保护导出 | 借鉴设计并重写为报告审批通用模型 | SVG 编辑、制图规则引擎及其前端工作台 |
| epo-cli `07491e42e6db` | EPO OPS/EPS 查询、同族、法律状态、图像/PDF、稳定 JSON | 固定版本二进制或受控 sidecar；解析稳定 JSON | 把 CLI 源码复制进 Python 服务 |
| uspto-cli `be955e3ce0cb` | USPTO 搜索、dossier、family、legal/prosecution 数据、稳定 JSON | 固定版本二进制或受控 sidecar；按用户绑定密钥 | 机构共用单一 API Key |
| cnipr-cli `46d4fbc2b129` | 单记录、可见浏览器、单次登录、人工交接和 PDF 验证契约 | 仅复用交接契约与校验思路 | 后台服务、批量抓取、Cookie 重放或持久化会话 |

### 8.1 来源引用规则

1. `provenance/sources.lock.json` 记录 URL、完整 commit、许可证、集成类型和允许范围。
2. 每个派生文件在 `provenance/FILE_MAP.md` 登记源文件、源提交、修改摘要和责任人。
3. 对实质复制的文件，在文件头增加 `Derived from <repo>/<path>@<commit>`，但不要在每个普通参考实现中滥加版权头。
4. EPO/USPTO CLI 的 MIT 许可证全文和版权声明进入 `THIRD_PARTY_NOTICES.md`，发布物中保留。
5. 其余当前没有 LICENSE 文件的自有项目，在商业复用前增加一份仓库所有者授权记录；不能把“GitHub 可见”当成自动获得商业再许可。
6. `.env`、数据库、运行工件、密钥、Cookie、真实案件和客户文件绝不复制。
7. 每次升级来源提交必须单独提交：更新 lock → 查看差异 → 更新适配器 → 跑契约测试 → 更新 FILE_MAP。
8. 生产环境不使用浮动的 `main`、`latest` 或未经校验的下载 URL。

## 9. 数据与安全边界

- 所有业务表启用并强制 PostgreSQL RLS。
- API 从服务端会话解析组织身份；拒绝客户端通过 Header 自报组织。
- 跨租户资源统一返回安全的 404，避免资源存在性泄漏。
- 对象存储键包含组织和案件前缀，但授权不能只依赖路径字符串。
- 下载通过短期签名链接或 API 流式代理，并校验案件权限。
- 供应商密钥数据库只保存 opaque reference、指纹和状态，不保存明文。
- 生产 Secret Store 未验证时系统必须拒绝启用供应商。
- LLM 请求默认只发送完成任务所需的最小文本；完整原文件不得自动发往模型。
- 日志禁止记录文档正文、原始 Prompt、API Key、密码、Cookie 和签名 URL。
- 审计事件保存 actor、action、target、result、timestamp 和安全摘要。
- 数据删除采用机构停用、保留期和后台清理任务；审计保留策略单独配置。
- 上线前完成隐私政策、数据处理约定、第三方模型清单和数据出境路径核验。

## 10. 报告结构

正式《可专利性预评估报告》至少包括：

1. 封面：机构、案号、标题、版本、日期、报告校验值。
2. 范围与免责声明：非正式法律意见、数据源和检索截止时间。
3. 技术方案摘要。
4. 已确认的必要技术特征表。
5. 检索策略与覆盖的数据源。
6. 相关文献清单、同族和法律状态时点。
7. 逐特征证据矩阵，包含原文定位。
8. 新颖性风险判断。
9. 创造性组合风险与组合假设。
10. 证据不足、未完成检索和待人工核验项。
11. 建议的后续动作。
12. 复核人、批准时间和版本链。

PDF 和 DOCX 必须来源于同一结构化报告快照，避免两种格式结论不一致。

## 11. 六周实施计划

### 第 0 周：建仓和来源治理（2–3 天）

- 创建独立私有仓库和上述目录。
- 写入 sources.lock、DERIVATION_POLICY、FILE_MAP、第三方声明。
- 确定 Python 3.12、Node LTS、PostgreSQL 和对象存储基线。
- 建立 CI：lint、typecheck、unit、contract、security。

退出标准：空业务骨架可在本地 Compose 启动，来源锁校验通过。

### 第 1 周：多租户和管理员开通

- 移植 PatentQ 的身份、机构、邀请、角色、会话和 RLS 模式。
- 实现平台管理员开通机构、配额和到期时间。
- 接入本地 Secret Store；生产实现保持 fail closed。
- 完成跨租户安全测试。

退出标准：两个机构用户不能发现或访问对方案件；管理员能人工开通机构。

### 第 2 周：案件、文档和特征版本

- 建立案件与对象存储。
- 移植 PatentForge 文档解析契约并加入安全校验。
- 实现特征提取、人工编辑和确认版本。
- 建立分析任务、步骤、失败恢复和审计。

退出标准：真实匿名 DOCX/PDF 可生成并确认特征版本，刷新浏览器后状态不丢失。

### 第 3 周：EPO/USPTO 检索

- 封装 CLI runner：固定路径、版本、超时、退出码、JSON schema 和输出大小。
- 实现 EPO 和 USPTO 适配器、原始结果存档、归一化与去重。
- 实现每数据源独立状态、重试和 partial success。
- 加入 USPTO 用户密钥绑定与限速。

退出标准：使用固定夹具和至少一个授权真实查询完成策略到候选文献流程。

### 第 4 周：证据矩阵与评估

- 移植 PatentQ 证据分层模型。
- 移植 PatentForge evidence/finding/eval/confirmation 思路。
- 建立原文引用定位、AI 分析和人工覆盖。
- 实现新颖性、组合风险、不确定性和证据完备度。
- 实现 CNIPR handoff 及单条证据导入。

退出标准：黄金案件能生成可核验矩阵；删除或修改来源会使相关评估过期。

### 第 5 周：复核和报告交付

- 实现提交、独立复核、退回、批准和后继修订。
- 按 PatentDraw 模式加入输入指纹、陈旧冲突和不可变批准。
- 实现结构化报告快照、DOCX/PDF、哈希和授权下载。
- 完成机构品牌模板的最小定制能力。

退出标准：未批准版本无法生成正式报告；批准版本可以稳定重现交付物。

### 第 6 周：试点和收费准备

- 跑 10 个匿名黄金案件和 3 个完整 E2E 案件。
- 检查跨租户、密钥、日志、备份恢复和失败任务。
- 准备机构演示环境、报价单、服务边界、试点协议和人工运维手册。
- 邀请首批 3 家机构，每家交付 1 个有人工复核的试点报告。

退出标准：至少一位外部代理师认可报告能节省时间并愿意付费试用。

## 12. 验收门禁

### 12.1 功能门禁

- 支持 DOCX、文本型 PDF 和粘贴文本；扫描 PDF 可明确提示暂不支持或进入 OCR 人工流程。
- 任一异步步骤失败后可以从安全检查点重试，不重复创建结果。
- 浏览器刷新、API 重启和 Worker 重启后任务状态可恢复。
- 每份结论能定位到特征版本、文献版本、证据版本和 Prompt/模型版本。
- EPO/USPTO 某一源失败时保留成功结果并展示不完整状态。
- CNIPR CAPTCHA、支付、权限变化立即停止并交给用户。

### 12.2 安全门禁

- 覆盖 Organization A/B 的跨租户矩阵测试。
- 直接修改 URL、请求体 organization_id 或对象键均无法越权。
- 日志和审计记录中搜索不到测试密钥、密码和文档正文。
- 供应商密钥读取接口永不返回明文。
- 提交人不能批准自己的报告。
- 已批准版本和报告工件不能原地覆盖。

### 12.3 证据质量门禁

- 任何专利号都必须来自连接器结果或人工导入记录。
- 任何原文引用都有来源 ID 和定位；无法定位则不得标为已核验。
- AI 判断和人工判断在 UI 与报告中视觉区分。
- 黄金集验证覆盖：单篇完全披露、部分披露、多文献组合、无结果、数据源失败和同族重复。
- 抽检报告中的引文、编号和链接正确率达到 100%；达不到则阻断交付。

### 12.4 商业门禁

- 平台管理员可在 10 分钟内开通一家机构。
- 新用户无需培训即可在 30 分钟内完成首个案件的导入和特征确认。
- 一名熟练代理师能在 4 小时内完成从导入到批准报告。
- 首批收费采用线下合同/收款；系统只记录配额和到期日。

## 13. 初始定价与交付方式

建议不要先卖纯订阅，而是用“试点服务 + 软件”取得现金流：

- 试点包：¥4,999–¥9,999，含 3–5 个案件、模板配置和一次培训。
- 单案服务：¥999–¥2,999，根据是否包含人工深度复核分档。
- 稳定后月度机构版：¥3,999–¥9,999/月，包含案件额度和超额单价。

第一阶段甚至可以由创业者在后台协助完成检索和报告。客户购买的是更快、更一致、可追溯的交付结果，不必等全部流程完全自动化后才销售。

## 14. 建仓后的首批任务顺序

```text
P0-01  初始化仓库、CI、Compose 和 sources.lock
P0-02  建立数据库角色、RLS 和跨租户测试
P0-03  实现平台管理员人工开通机构
P0-04  实现会话、邀请、MFA 和四个固定角色
P0-05  实现案件、文档对象存储和解析任务
P0-06  实现特征草稿、编辑和不可变确认版本
P0-07  实现检索策略和可恢复执行
P0-08  接入 EPO 固定版本适配器
P0-09  接入 USPTO 固定版本适配器和用户密钥
P0-10  实现文献归一化、同族和法律状态快照
P0-11  实现证据矩阵四层值
P0-12  实现预评估、发现、不确定性和核验动作
P0-13  实现 CNIPR 人工交接与单条证据导入
P0-14  实现独立复核、退回和不可变批准
P0-15  实现 DOCX/PDF 报告、哈希和受保护下载
P0-16  完成黄金集、E2E、安全和恢复门禁
P0-17  准备试点合同、报价、演示机构和运维手册
```

这些任务必须按顺序实现。不能为了更快看到 UI 而跳过租户隔离、证据版本和人工批准，因为这三项是机构客户愿意付款的基础。

## 15. 最终架构判断

新项目的本质不是七个仓库的大合并，而是一次有边界的产品化：

- 以 PatentQ 作为安全、租户和持久工作流参考骨架。
- 以 PatentForge 作为分析运行和证据 QA 的主要能力来源。
- 以 PatentScope 作为离线验证和黄金集参考。
- 以 PatentDraw 作为不可变审批与受保护导出的设计参考。
- 以 epo-cli 和 uspto-cli 作为固定版本的检索执行器。
- 将 cnipr-cli 限定为合规的人工交接流程。

首版只优化一个可收费指标：在不牺牲证据真实性和租户安全的前提下，让代理机构更快交付一份可复核的专利检索与可专利性预评估报告。
