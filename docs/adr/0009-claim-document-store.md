# ADR 0009: 权利要求文本的获取与存储

- Status: Accepted（产品负责人于 2026-10-04 要求继续）
- Date: 2026-10-04

## Context

ADR 0008 的比对模型需要权利要求全文。本 ADR 规定如何获取并存储它，沿用 ADR 0006 的全局只追加模式。

## 实测输入（2026-10-04）

- **美国**：先按专利号查询 ODP，得到 `grantDocumentMetaData.fileLocationURI`，再用同一密钥下载该专利的授权全文 XML。
  全文 XML 含发明人姓名等个人信息；权利要求位于 `<claims>` 元素内。
  `fileCreateDateTime` 是文件生成时间，不是数据日期（2007 年授权的专利，其值为 2024-09-29）。
- **欧洲**：OPS `claims` 端点；没有权利要求文本时返回 404 `SERVER.EntityNotFound`（A1 公开与不存在的号码均如此）。

## Decision

### 1. 存储

新表 `patent_claim_documents`，全局、只追加（worker SELECT/INSERT，app SELECT，无 UPDATE/DELETE，无机构字段）。每次获取一行：

| 列 | 说明 |
|---|---|
| `publication_number`、`source` | `uspto_grant_xml` / `epo_ops_claims` |
| `request_ref` | 请求地址与参数（不含凭据）；美国为两步请求的两个地址 |
| `retrieved_at`、`source_file_created_at` | 取数时间；美国 XML 的文件生成时间（不是数据日期） |
| `outcome` | `found` / `not_found` |
| `claims_text` | 解析器读取的内容：美国为 `<claims>` 元素；欧洲为 OPS 权利要求 JSON |
| `text_represents` | 文本代表什么（见第 3 条） |
| `raw_sha256`、`raw_size_bytes`、`raw_storage_key` | 原始响应字节的哈希、大小与对象存储位置 |

美国全文 XML 原样存入对象存储（含个人信息，保留期限沿用 ADR 0006 的待合规确认事项）；数据库只存 `<claims>` 部分。
欧洲 OPS 权利要求响应不含个人信息，原样存入对象存储，同时存入 `claims_text`。

解析结果（权利要求树、特征）不入库：由 `claims_text` 确定性地重新解析得到。

### 2. 获取安全

美国 XML 地址来自外部数据。获取前校验地址必须以 `https://api.uspto.gov/api/v1/datasets/products/files/` 开头，
否则拒绝，防止被诱导请求任意地址（SSRF）。获取失败时不写入任何内容。

### 3. 文本代表的是授权时的权利要求

- 美国授权 XML 是**授权时**的权利要求。授权后的复审证书、IPR 证书、更正证书可能修改或删除权利要求，
  这些变化**不在**该文件中。记录 `text_represents = "as_granted"`，并在使用时提示。
- 欧洲：`B1` 是授权文本；异议后修改的 `B2`、限制后的 `B3` 取代 `B1` 的权利要求。按具体公开号获取并记录，
  比对时应使用同一申请的最新公开文本（ADR 0007 第 4 条）。
- 授权后变化的获取（美国 PTAB / 复审，欧洲 B2/B3 的自动选择）是后续工作，在此之前比对结果须带上述提示。

## Consequences

- 新增迁移 `0020_claim_documents`、客户端方法（美国授权 XML、欧洲权利要求）、worker 获取流程与测试。
- 用覆盖集中的专利做一次实时获取，确认存储内容能被 ADR 0008 的解析器解析。
