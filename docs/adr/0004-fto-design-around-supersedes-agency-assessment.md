# ADR 0004: FTO 与规避设计取代代理机构可专利性预评估，作为产品主线

- Status: Accepted
- Date: 2026-10-04

## Context

仓库内存在两份互相矛盾的产品定义：

- `docs/product/mvp-implementation-spec.md`：目标客户为中国大陆专利代理机构，
  交付物为《可专利性预评估报告》；其“首版不做”清单明确排除 “FTO 完整法律意见”。
- `docs/plans/2026-fto-design-around-master-plan.md`（#9 合入）：目标客户为锂电与储能
  产业链企业的知识产权部与研发团队，主线为“证据级” FTO 风险排查与规避设计
  （Design-Around），首期法域为中国 + 美国。

`AGENTS.md` 要求产品工作遵循“产品规格”，两份文档并存时每个设计决定都有两个
相互冲突的依据。2026-10-04，产品负责人决定：**FTO 与规避设计取代原产品线**。

## Decision

1. `docs/plans/2026-fto-design-around-master-plan.md` 为产品主线依据，并以本 ADR
   “核对结果”一节为准修正其中与现有代码不符的工程假设。
2. `docs/product/mvp-implementation-spec.md` 标记为已被取代（Superseded），保留作历史
   参考；其中与产品线无关、仍然成立的工程约束继续有效（见下文“保留的约束”）。
3. 现有代码不删除。可复用部分直接复用于 FTO 闭环；仅服务于可专利性预评估的部分
   冻结（不再扩展，保持测试通过），待 FTO 对应能力落地后再单独决定去留。

### 保留的约束

以下约束与产品线无关，继续有效：租户隔离（FORCE RLS）、来源可追溯（provenance）、
已审批内容不可变、CNIPR 人工交接（不对 CNIPR 做自动化抓取）、导出文件可复核
（版本号 + 校验值 + 审计记录）、上传文件服务端内容检查。

## 核对结果：总体规划中的工程假设与现状（2026-10-04 依据代码核对）

| 总体规划表述 | 核对依据 | 现状 |
|---|---|---|
| 第 1–2 周“移植 PatentQ 治理底座（RLS/MFA/Audit）” | `provenance/FILE_MAP.md` 共 17 条 PatentQ 来源记录（commit `eb63654`）；迁移 `0001_identity_tenancy` | **已完成**（P0-02）：FORCE RLS、TOTP MFA 与恢复码、会话、只追加审计日志均已实现并有集成测试 |
| §5.2 新增 `tenants` / `memberships` / `mfa_credentials` / `audit_events` 表 | 迁移 `0001` 表清单 | 租户模型为 `organizations` + `organization_memberships`；`mfa_credentials`、`audit_events` 已存在，无需新增 |
| §5.2 RLS 策略注入 `app.current_tenant_id` | 迁移与 `core/database.py` 中的设置项 | 实际为 `app.current_organization_id`（另有 actor / session / correlation 等上下文项） |
| §5.1 前端 “Next.js” | `apps/web/package.json` | React 19 + Vite 7 |
| §5.1 迁移目录 `db/alembic/` | 仓库结构 | `apps/api/migrations/`（`alembic.ini` 位于 `apps/api/`） |
| §5.1 `adapters/auth`（JWT） | `apps/api/src` 中无 JWT 实现 | 服务端会话：不透明令牌、仅存哈希、按 RLS 解析（`auth/session_authority.py`） |
| §5.1 `modules/platform`“含应急访问” | 代码检索 | 应急访问目前仅见于运维手册（`docs/operations/`），应用内无该功能 |
| §5.1 `adapters/secret_store`（BYOK） | `adapters/secret-store/` | 仅有 README 占位，BYOK 未实现 |
| §5.1 `adapters/llm` 敏感度双路由 | `adapters/llm/client.py` | 单一 OpenAI 兼容客户端，无敏感度分级路由、无零留存保证机制 |
| §5.1 `modules/retrieval`、`adapters/vector_store` | 目录内容；`compose.yaml` | `modules/retrieval` 仅 README 占位；数据库镜像为 `postgres:16-alpine`，无 pgvector、无中文分词 |
| `modules/design_around`、`adapters/tsa`、`stage_gate_passes` 等 | 代码检索 | 不存在，均为新建 |

由此，规划第 1–2 周的治理移植无需执行；该时间应转用于下文的关键路径事项。

## 可复用与冻结的现有能力

下表中不带前缀的路径相对于 `apps/api/src/patent_evidence_api/`。

| 能力 | 位置 | 在 FTO 闭环中的去向 |
|---|---|---|
| 身份、组织、RLS、MFA、审计 | `auth/`、`organization/`、`platform/`、迁移 0001–0003 | 直接复用 |
| 案件与文档上传、内容检查、解析 | `cases/`、`modules/cases/` | 复用为“技术方案（被控产品/方案）”录入 |
| 特征建模 | `features/`、`modules/features/` | 复用于方案技术特征；FTO 另需“第三方权利要求要素”模型（新建） |
| 检索适配器 | `adapters/epo`、`adapters/uspto`、`adapters/cnipr-handoff` | 复用；垂直库与混合召回为新建 |
| 逐特征比对矩阵 | `comparison/`、`modules/comparison/` | 基础设施可复用；比对方向不同（见下），需新的判定模型 |
| 证据快照封存、报告导出（DOCX/PDF） | `reports/`、`modules/reports/` | 直接复用，作为存证封存与交付基础 |
| 复核、交付门禁 | `review/`（含交付门禁与 `delivery_records`，迁移 0010） | 复用为 Stage-Gate 双角色门禁的基础 |
| 可专利性预评估（新颖性/创造性候选、版本、输入快照） | `assessment/`、迁移 0013–0016 | **冻结**：可专利性专属，FTO 不使用 |

比对方向差异（事实性说明，非法律意见）：可专利性评估以“申请方案的特征”对照“现有技术”；
FTO 以“他人有效权利要求的每一技术特征”对照“己方方案”，需要按权利要求树（独立/从属）
逐项判定，并结合权利的有效状态与法域。具体判定规则（如全面覆盖原则、等同原则在各法域
的适用）应由规则包定义并经专业人员审定，不在本 ADR 中预设。

## 待核实事项（尚无依据，不得作为既定事实引用）

下列事项在总体规划中有表述，但目前没有经过验证的依据。在取得实测数据或明确决定之前，
文档与代码中只能将其标注为“待核实”：

1. **数据可得性**：Top 15 主体近 5 年 CPC H01M / H02J 中国与美国有效专利的实际件数
   （规划写 5,000~8,000 件）；中文权利要求原文是否可从公开数据源获得；**中国专利
   法律状态（是否有效）的合规数据来源**——在 CNIPR 人工交接约束下尤其需要确认。
   → 以数据可行性探查（spike）实测回答。
2. 中文全文检索与向量检索的技术选型（pgvector、中文分词方案、向量模型）。
3. 敏感度双路由中“境内零留存模型”的具体供应方及其数据留存条款。
4. 国内司法链 / 可信时间戳与 RFC 3161 TSA 的供应方与接入条件。
5. 判例基准测试集的来源、标注方式与标注人员资质。
6. 规划中的日程（M1 8 周）在上述事项明确之前不视为承诺。

## Consequences

- 新增产品工作以总体规划 + 本 ADR 为依据；`AGENTS.md` 相应更新。
- 冻结模块保持现有测试通过，但不再新增功能。
- 关键路径是数据可得性（尤其中国法律状态）与判例基准集，二者均依赖工程以外的输入，
  应优先以实测和明确决定消除不确定性，再投入依赖它们的工程开发。
