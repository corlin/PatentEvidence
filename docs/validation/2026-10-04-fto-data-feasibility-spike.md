# FTO 数据可行性探查（2026-10-04）

回答 [ADR 0004](../adr/0004-fto-design-around-supersedes-agency-assessment.md)“待核实事项”第 1 项：
锂电与储能（CPC/IPC H01M、H02J）中国与美国授权专利的件数、中文权利要求原文的可得性、
中国专利法律状态的数据来源。本文只记录实测结果；推断与待决事项单列，并标明依据。

## 方法

- **数据源 A**：Google Patents Public Datasets，`patents-public-data.patents.publications`
  （BigQuery，Google Cloud 项目 `gen-lang-client-0824332458`）。每条查询先做 dry-run 估算扫描量，
  再在 `maximum_bytes_billed` 上限内执行。九条查询合计计费 **184.75 GB**。
- **数据源 B**：EPO Open Patent Services 3.2（OPS），使用仓库 `.env` 中的 EPO 凭据；
  调用 `published-data/.../fulltext`、`.../claims` 与 `legal`（INPADOC）三个端点。
- **时间窗**：授权日 `grant_date >= 20211004`（2026-10-04 前 5 年）。
- **领域筛选**：`cpc.code` 或 `ipc.code` 以 `H01M` 或 `H02J` 开头（见发现 3：仅用 CPC 会漏检）。
- **授权类型**：CN `B`（发明授权）、CN `U`（实用新型）、US `B1` / `B2`（发明授权）。
  类型码取自数据本身（发现 2），未作预设。

## 发现（实测）

### 1. 该表没有法律状态字段

`INFORMATION_SCHEMA.COLUMNS` 共 37 列，无法律状态、失效或到期字段（`entity_status` 是美国小/大实体标识）。
是否“有效”无法从该表得到。

### 2. 数据新鲜度与授权类型码

H01M/H02J、2019 年起公开的文献：CN 最新公开日 2026-09-08，US 最新公开日 2026-09-17。
CN 授权类型为 `B`（发明）与 `U`（实用新型），另有少量更正文本 `B8/B9/U8/U9`；US 为 `B1/B2`。

### 3. 中国实用新型大多没有 CPC 分类号，必须用 IPC 筛选

| 授权于 2021-10-04 之后，H01M/H02J | 按 CPC | 按 IPC | 合并（CPC 或 IPC） |
|---|---:|---:|---:|
| CN 发明（B） | 153,971 | 172,833 | **177,920** |
| CN 实用新型（U） | 6,429 | 236,786 | **237,461** |
| US（B1 + B2） | 53,794 | 48,743 | **54,133** |

时间窗内全部 CN 实用新型 10,395,720 件中，8,682,920 件（83.5%）没有任何 CPC 分类号。
若按总体规划决策 07 只用 CPC 筛选，将漏掉本领域 97.3% 的中国实用新型（6,429 / 237,461 被检出）。

### 4. 中国发明专利没有“规范化申请人”字段

| | 件数 | 有 `assignee_harmonized` | 有原始 `assignee` |
|---|---:|---:|---:|
| CN 发明（B） | 177,920 | **0** | 177,920 |
| CN 实用新型（U） | 237,461 | 225,602 | 237,461 |
| US（B1 + B2） | 54,133 | 53,881 | 54,133 |

按申请人统计中国专利必须使用原始 `assignee`（中文名称）。首次统计误用了规范化字段，
导致中国结果只包含实用新型；该结果已作废，下表为改用原始字段后的结果。

### 5. 本领域实际申请人分布（数据导出，非预设名单）

中国（原始申请人名称，授权于 2021-10-04 之后，前 12 名）：

| 申请人（原文） | 合计 | 发明 | 实用新型 |
|---|---:|---:|---:|
| 宁德时代新能源科技股份有限公司 | 11,666 | 3,665 | 8,001 |
| 国家电网有限公司 | 5,387 | 4,826 | 561 |
| 比亚迪股份有限公司 | 4,648 | 1,361 | 3,287 |
| 蜂巢能源科技股份有限公司 | 4,504 | 847 | 3,657 |
| 株式会社Lg新能源 | 2,623 | 2,409 | 214 |
| 湖北亿纬动力有限公司 | 2,584 | 436 | 2,148 |
| 惠州亿纬锂能股份有限公司 | 2,471 | 335 | 2,136 |
| 合肥国轩高科动力能源有限公司 | 2,230 | 683 | 1,547 |
| 中创新航科技集团股份有限公司 | 2,075 | 390 | 1,685 |
| 丰田自动车株式会社 | 1,882 | 1,666 | 216 |
| 远景动力技术(江苏)有限公司 | 1,836 | 307 | 1,529 |
| 远景睿泰动力技术(上海)有限公司 | 1,823 | 296 | 1,527 |

美国（规范化申请人，前 10 名）：LG Energy Solution 3,101；Toyota 1,839；LG Chem 1,353；
Hyundai 1,240；Honda 936；Samsung SDI 920；Samsung Electronics 887；Panasonic IP 857；Kia 785；
Contemporary Amperex Technology 762（另有 Contemporary Amperex Technology Hong Kong 675）。

需要注意：

- 同一集团以多个法律主体出现（如“中创新航科技集团股份”与“中创新航科技股份”、“蜂巢能源 股份”与“有限”、
  “远景动力”与“远景睿泰”、“正力新能 有限”与“股份”），按集团统计需要实体归并。
- H02J 带入了大量电网与高校申请人（国家电网、中国电力科学研究院、华北电力大学等）。
  储能产品范围是否需要这部分，属于产品范围决定。
- 宁德时代一家在中国 5 年内的 H01M/H02J 授权即有 11,666 件。总体规划中“Top 15 近 5 年核心有效专利
  5,000~8,000 件”远小于原始量级，只有在定义了“核心”的筛选标准之后才可能成立；该标准目前未定义。
- “Top 15”名单在规划中未列出（仅举例宁德/比亚迪/特斯拉/LGES）。特斯拉不在美国前 40 名中，
  但本次未单独核查其规范化名称变体，不能据此下结论。

### 6. Google Patents 公共数据集没有中国权利要求文本

| | 件数 | 有任何语言的权利要求 | 有中文权利要求 |
|---|---:|---:|---:|
| CN 发明（B） | 177,920 | **0** | 0 |
| CN 实用新型（U） | 237,461 | **0** | 0 |
| US（B1 + B2） | 54,133 | 54,133（英文） | 0 |

### 7. 中国专利的标题与摘要基本齐全（中英文）

IPC 筛选下：CN 发明 172,833 件，中文与英文标题 172,833 件，中文与英文摘要 172,818 件；
CN 实用新型 236,786 件，标题 236,786 件，摘要 236,767 件。
基于中文摘要做召回在该数据源上可行；逐要素比对所需的权利要求全文不可行。

### 8. EPO OPS 不提供中国与美国的权利要求文本

5 件样本（4 件宁德时代 CN：`CN-106299226-B`、`CN-106531945-B`、`CN-214411247-U`、`CN-214428674-U`；
1 件 US）：`claims` 端点全部返回 `CLIENT.InvalidCountryCode`，`fulltext` 端点全部返回 `SERVER.EntityNotFound`。

### 9. EPO OPS 的 INPADOC 法律事件覆盖中国，且包含终止与转让事件

宁德时代样本返回 `C06`（PUBLICATION）、`SE01`（ENTRY INTO FORCE OF REQUEST FOR SUBSTANTIVE EXAMINATION）、
`GR01`（PATENT GRANT），每个事件带有事件日期等字段。

为确认能否区分有效与失效，抽查 40 件 2014 年中国实用新型（`CN.203610000.U`～`CN.203610039.U`），
全部返回事件。OPS 自带的事件描述包括：

| 代码 | OPS 描述 | 出现次数 |
|---|---|---:|
| C14 | GRANT OF PATENT OR UTILITY MODEL | 40 |
| CF01 | TERMINATION OF PATENT RIGHT DUE TO NON-PAYMENT OF ANNUAL FEE | 16 |
| CX01 | EXPIRY OF PATENT TERM | 12 |
| EXPY | TERMINATION OF PATENT RIGHT OR UTILITY MODEL | 6 |
| C41 / TR01 / ASS | 专利权或申请权转让、继受 | 4 / 1 / 4 |
| C25 / RGAV | 为避免重复授权而放弃专利权 | 2 / 2 |
| CP01 / CP03 / COR / LICC | 名称或著录项目变更、许可合同备案 | 各 1 |

响应头 `x-throttling-control` 显示 `inpadoc=green:45`。

## 结论（直接由上述实测得出）

1. **中国权利要求全文没有可用来源**：本次核查的两个数据源（Google Patents 公共数据集、EPO OPS）
   都不提供。CNIPR 人工交接约束又排除了对 CNIPR 的自动获取。这是中国 FTO 逐要素比对的首要阻塞项。
2. **美国权利要求全文可得**：公共数据集中 54,133 件全部有英文权利要求。
3. **中国法律状态有候选来源**：INPADOC 法律事件覆盖中国，包含年费终止、期满、放弃与转让事件。
   但其是否足以判定“有效”尚未证实（见下）。
4. **语料筛选必须同时用 CPC 与 IPC**；中国申请人统计必须用原始 `assignee`，并做实体归并。
5. 规划中的 **5,000~8,000 件** 与实测量级不符，需要先定义“核心”专利的筛选标准。

## 未验证事项（下一步）

以下内容本次没有测，不得作为事实引用：

- **中国权利要求全文的合规来源**：例如国家知识产权局的数据服务或商业数据库，其覆盖、授权条款与价格均未核查。
- **INPADOC 中国法律事件的时效**：相对国家知识产权局公告的延迟。
- **INPADOC 是否包含无效宣告**：本次样本中未出现无效宣告类事件。
- **INPADOC 能否单独判定“有效”**：没有终止事件不等于仍然有效（可能存在延迟或漏记）。
- **`inpadoc=green:45` 的确切含义**：按 EPO 公布的限流说明理解为每分钟配额，需以 EPO 现行条款确认。
  按此估算全量查询中国 41.5 万件约需数天。另外，OPS 的商业使用条款尚未核查。
- **美国法律状态**：INPADOC 对美国样本返回了事件；USPTO 维持费与法律状态 API（仓库中已有 USPTO 凭据）尚未探查。
- **特斯拉等未进入前列的申请人**：其名称变体与实际件数未单独核查。
- **5 年时间窗本身**：FTO 关心的是“目前仍然有效”，并不限于近 5 年授权（专利权期限更长）。
  时间窗的选择需要产品决定。

## 复现

关键查询（其余查询结构相同，仅统计列不同）：

```sql
-- 发现 3：CPC 与 IPC 覆盖对比（计费 23.81 GB）
WITH base AS (
  SELECT country_code, kind_code,
    EXISTS (SELECT 1 FROM UNNEST(cpc) c WHERE STARTS_WITH(c.code,'H01M') OR STARTS_WITH(c.code,'H02J')) AS by_cpc,
    EXISTS (SELECT 1 FROM UNNEST(ipc) i WHERE STARTS_WITH(i.code,'H01M') OR STARTS_WITH(i.code,'H02J')) AS by_ipc,
    ARRAY_LENGTH(cpc) AS n_cpc
  FROM `patents-public-data.patents.publications`
  WHERE country_code IN ('CN','US') AND kind_code IN ('B','U','B1','B2') AND grant_date >= 20211004)
SELECT country_code, kind_code, COUNTIF(by_cpc) cpc_hit, COUNTIF(by_ipc) ipc_hit,
  COUNTIF(by_cpc OR by_ipc) either_hit, COUNT(*) all_grants_in_window, COUNTIF(n_cpc = 0) grants_without_any_cpc
FROM base GROUP BY 1,2;

-- 发现 6：权利要求语言（只读取 language 子字段，计费 21.68 GB；
-- 对整个 claims_localized 记录调用 ARRAY_LENGTH 会扫描全文，dry-run 为 146.6 GB）
WITH d AS (
  SELECT p.country_code, p.kind_code, ARRAY(SELECT cl.language FROM UNNEST(p.claims_localized) cl) AS langs
  FROM `patents-public-data.patents.publications` p
  WHERE p.country_code IN ('CN','US') AND p.kind_code IN ('B','U','B1','B2') AND p.grant_date >= 20211004
    AND (EXISTS (SELECT 1 FROM UNNEST(p.cpc) c WHERE STARTS_WITH(c.code,'H01M') OR STARTS_WITH(c.code,'H02J'))
      OR EXISTS (SELECT 1 FROM UNNEST(p.ipc) i WHERE STARTS_WITH(i.code,'H01M') OR STARTS_WITH(i.code,'H02J'))))
SELECT country_code, kind_code, COUNT(*) docs, COUNTIF(ARRAY_LENGTH(langs) > 0) with_any_claims,
  COUNTIF('zh' IN UNNEST(langs)) with_zh_claims, COUNTIF('en' IN UNNEST(langs)) with_en_claims
FROM d GROUP BY 1,2;
```

EPO OPS 端点：`/3.2/rest-services/published-data/publication/docdb/{CC.NUM.KIND}/claims`、`.../fulltext`、
`/3.2/rest-services/legal/publication/docdb/{CC.NUM.KIND}`。

本次查询输出未提交仓库（运行时产物）；按上述 SQL 与端点可复现。由于数据集是定期快照，
复现所得数字可能随快照更新而变化。
