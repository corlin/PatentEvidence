# ADR 0006: 公开专利法律状态数据的存储方案

- Status: Accepted（产品负责人于 2026-10-04 授权工程方设计）
- Date: 2026-10-04

## Context

`modules/legal_status`（#11）可以判定美国、欧洲专利在某一分析日期的法律状态。判定结果需要持久化，
供 FTO 分析引用和封存。这些数据与现有业务数据有三点不同：

1. **公开、跨租户共享**：同一件专利的法律状态对所有机构都一样，按机构重复抓取既浪费配额，
   也会让不同机构看到的“同一事实”不一致。
2. **会随时间变化**：同一件专利今天有效、明年可能失效；数据源本身也有延迟（ODP 记录的
   `lastIngestionDateTime` 实测为数月之前）。
3. **要作为证据**：FTO 结论引用某个状态时，必须能说明“依据哪次查询、哪份原始响应、哪版规则”。

现有表都按机构隔离（FORCE RLS + `app.current_organization_id`），不能直接容纳跨租户共享的公开数据。
仓库已有不按机构隔离的全局表（如 `global_identities`），靠精确授权保护；集成测试只要求机构表启用 RLS。

## Decision

### 1. 两张全局表，只追加

公开数据放在不带 `organization_id` 的全局表中。运行时角色只授予 `SELECT` / `INSERT`，
不授予 `UPDATE` / `DELETE`（与 `source_result_snapshots`、审计表相同的只追加方式）。

**`legal_status_source_records`：每次查询数据源的记录**

| 列 | 说明 |
|---|---|
| `id` | UUID 主键 |
| `publication_number` | 规范化公开号，如 `US-7252747-B2`、`EP-1801605-B1` |
| `source` | `uspto_odp` / `epo_ops_inpadoc` |
| `request_ref` | 请求的端点与参数（不含凭据） |
| `retrieved_at` | 本平台取数时间 |
| `source_data_as_of` | 数据源自报的数据时间（ODP `lastIngestionDateTime`；OPS 无此字段时为空） |
| `outcome` | `found` / `not_found`。“查不到”也记录：它证明查过，但不代表失效 |
| `extract` | 规则实际读取的字段（与 fixtures 的裁剪口径相同），`not_found` 时为空 |
| `raw_sha256`、`raw_size_bytes`、`raw_storage_key` | 原始响应字节的哈希、大小与对象存储位置 |

**`legal_status_assessments`：规则对某次查询记录的判定**

| 列 | 说明 |
|---|---|
| `id` | UUID 主键 |
| `source_record_id` | 外键，指向所依据的查询记录 |
| `publication_number`、`jurisdiction` | `US` / `EP` |
| `as_of` | 分析日期 |
| `rules_version` | 规则版本（如 `legal-status-rules/1`）。规则改变时产生新版本的新行，旧判定保留 |
| `status` | `presumed_in_force` / `lapsed` / `expired` / `undetermined` |
| `term`、`countries`、`evidence`、`review_reasons` | 判定的完整内容（JSONB） |
| `content_sha256` | 判定内容规范化 JSON 的 SHA-256，供封存时绑定 |
| `assessed_at` | 判定时间 |

唯一约束：`(source_record_id, as_of, rules_version)`，同一输入、同一日期、同一规则只判定一次。

### 2. 原始响应存对象存储，数据库只存规则所需字段

原始响应按内容寻址存放：`public/legal-status/<source>/<sha256>.json`（相同内容只存一份）。
数据库保存其哈希，可证明判定所依据的原始字节；`extract` 只含规则读取的字段。

原始响应可能包含发明人、代理人等公开的个人信息。是否保留原始全文、保留多久，涉及个人信息处理的
合法性与最小必要原则（中国《个人信息保护法》对已公开个人信息的处理有专门规定；涉及欧洲个人时还需考虑 GDPR）。
**该保留策略须由合规人员确认**。在确认之前，实现只把原始响应存入对象存储、不复制进数据库，
并保留按前缀整体删除的能力（删除原始文件不影响 `raw_sha256` 作为事后核对依据）。

### 3. 不启用 RLS，但机构关联留在机构表里

两张全局表不含任何机构信息，所以不启用按机构的 RLS。

“哪个机构在关注哪件专利”本身是敏感信息（会暴露客户的产品方向和竞争对手）。因此：

- 全局表中**不得**出现请求方机构、案件或用户字段；
- 机构对某个判定的引用，放在将来的机构表中（FORCE RLS），只保存 `assessment_id` 与其
  `content_sha256`，并在证据快照封存时一并绑定。

### 4. 角色与权限

| 角色 | `legal_status_source_records` | `legal_status_assessments` |
|---|---|---|
| `patent_evidence_worker`（抓取与判定） | SELECT, INSERT | SELECT, INSERT |
| `patent_evidence_app`（API 读取） | SELECT | SELECT |
| `patent_evidence_platform` | 无 | 无 |
| `patent_evidence_migration` | 所有者 | 所有者 |

API 不直接写入公开数据，抓取与判定只在 worker 中进行，避免请求路径中的外部调用与配额消耗。

### 5. 刷新策略

- 每次判定绑定一条查询记录，并同时记录 `retrieved_at` 与 `source_data_as_of`。两者含义不同：
  刚取到的数据，其数据源时间可能是数月之前。
- 某件专利的最新查询记录早于可配置的刷新间隔时，重新查询；封存 FTO 证据快照前，对涉及的专利强制重新查询。
  刷新间隔的默认值在首次全量运行、测得配额消耗之后确定，本 ADR 不预设数字。
- 新查询不覆盖旧记录：历史状态可追溯，“当时依据的是什么”始终可答。

## Consequences

- 新增迁移 `0018_legal_status_store`：两张表、索引、授权；集成测试验证授权边界与只追加。
- `modules/legal_status` 增加规则版本常量与判定的规范化序列化（用于 `content_sha256`）。
- worker 增加“查询 → 存原始响应 → 记录 → 判定 → 记录”的流程；数据源失败时不写入判定（不伪造状态）。
- 尚未包含：任务队列与触发方式、机构侧引用表、API 读取接口、刷新间隔默认值、原始响应保留期限。
