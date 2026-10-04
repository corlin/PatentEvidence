# 锂电与储能领域“证据级” FTO 与竞品规避平台设计与实施蓝图
## PatentEvidence · Enterprise Evidence-Grade IP & Design-Around Platform

> **实施勘误（2026-10-04）**：本规划已被采纳为产品主线（[ADR 0004](../adr/0004-fto-design-around-supersedes-agency-assessment.md)）。
> 经与代码核对，§5 / §6 中部分工程假设与现状不符（例如第 1–2 周的 PatentQ 治理移植已在 P0-02 完成；
> RLS 设置项为 `app.current_organization_id`；前端为 React + Vite）。以 ADR 0004“核对结果”为准。
> ADR 0004“待核实事项”所列内容（数据件数与来源、中国法律状态来源、各类供应方、判例基准集、M1 日程）
> 在取得实测数据或明确决定前不视为既定事实。
> **范围修订（2026-10-04）**：首期法域改为美国与欧洲，中国数据评估后再定；时间范围采用“当前可能有效”而非
> “近 5 年授权”；“核心专利”是预标注优先级而非检索范围，“Top 15 / 5,000~8,000 件”以实测为准。见
> [ADR 0005](../adr/0005-fto-corpus-time-scope-and-core-definition.md)。

---

## 1. 战略定位与四重竞争壁垒

本项目以 **PatentEvidence** 为核心代码底座，整合 **PatentQ** 的多组织与审计治理体系以及 **PatentForge** 的智能撰写能力，专注于打造国内首个面向**锂电与储能产业链（结构件 + 材料化工）**、服务于**企业知识产权部与研发团队**的“证据级”高保证 SaaS 平台。

```mermaid
graph TD
    A["四重竞争壁垒体系"]
    A --> B["1. 数据壁垒: 垂直特征级标注库<br/>Top 15 巨头近 5 年核心专利精细化解构"]
    A --> C["2. 算法壁垒: 闭环反向验真引擎<br/>生成规避建议后自动反向比对权利要求树与同族池"]
    A --> D["3. 信任与合规壁垒: 司法双轨可信锚定<br/>中国天平链/可信时间戳 + 国际 RFC 3161 TSA/公链哈希"]
    A --> E["4. 工作流壁垒: 研发Stage-Gate门禁<br/>双角色协同流，将 FTO 报告沉淀为研发不可逆通行凭证"]
```

---

## 2. 22 项系统决策共识矩阵

| # | 决策维度 | 选定方案 | 核心价值 / 设计边界 |
|---|---|---|---|
| **01** | 主线定位 | **证据级合规 + 竞品规避设计 (Design-Around)** | 不做泛化查新，深挖 FTO 与可经受法庭质证的规避闭环 |
| **02** | 核心客户 | **企业知识产权部 (IP) + 研发团队 (R&D)** | 直击高预算、高频立项出海场景 |
| **03** | 技术领域 | **新能源智能硬件 + 新材料化工** | 兼顾结构构件与化学组分/数值范围 |
| **04** | 首发切口 | **锂电与储能产业链** | 一条链打通结构件（电芯/模组/热管理）与化工（正负极/电解液/隔膜） |
| **05** | 部署形态 | **纯 SaaS** | 聚焦中腰部电池与储能出海企业，复用多租户隔离底座 |
| **06** | 信任机制 | **等保三级/ISO + BYOK 客户自管密钥 + 零数据留存** | 方案内容服务端加密，模型推理不保留数据 |
| **07** | 数据方案 | **公开源自建垂直库 + 客户自有结果导入** | 聚焦 CPC H01M / H02J，积累特征级专利资产 |
| **08** | 代码主干 | **以 PatentEvidence 为主干，融合 PatentQ** | 移植 PatentQ 治理底座，接入 PatentForge 撰写模块，归档其余库 |
| **09** | MVP 闭环 | **FTO 风险排查 + 规避设计** | 录入方案 → 初筛召回 → 逐特征比对 → 规避建议 → 证据封存 |
| **10** | 适用法域 | **中国 + 美国 + 欧洲** | 覆盖出海诉讼最密集的三个核心市场 |
| **11** | 欧洲规则 | **统一专利法院 (UPC) + 德国规则包先行** | 覆盖欧洲绝大部分诉讼风险，英国后续扩展 |
| **12** | 产出属性 | **双层机制（AI 报告自查 + 平台内持证律师复核）** | 平台不直接接案出意见，合规避险，支持律师入驻签署 |
| **13** | 模型路由 | **敏感度分级双路由** | 公开数据批处理用顶级模型；客户保密方案走境内零留存模型 |
| **14** | 准确率基线 | **真实公开判例标准答案集 + 专家抽检校准** | 以法院判例为锚点，公布客观准确率/召回率指标并按版本留档 |
| **15** | 商业模式 | **年度订阅（按 FTO 项目配额分档）+ 律师按次服务费** | 匹配企业年度预算，辅以竞品监控增值包 |
| **16** | 交付节奏 | **三阶段里程碑独立交付** | M1(中/美/结构类) → M2(化工/数值范围) → M3(欧洲/律师签署) |
| **17** | 规避机制 | **闭环反向验真机制** | 建议方案反向自动比对从属权项与同族池，防范二次落入 |
| **18** | 法律锚定 | **国内司法链 + 国际 RFC 3161 TSA / 公链双轨存证** | 确保证据在海内外法庭及 337 调查中的法定证明力 |
| **19** | 协作机制 | **研发/IP 双角色门禁流 (Stage-Gate)** | 研发提交与规避，IP 复核与终审，输出立项开模绿灯凭证 |
| **20** | 冷启动规模 | **Top 15 头部巨头近 5 年核心有效专利 (5,000~8,000 件)** | 宁德/比亚迪/特斯拉/LGES 等核心主体，高信噪比 |
| **21** | 初筛召回 | **混合检索 (Dense + BM25 + 分类过滤) + Cross-Encoder 重排** | 解决研发白话输入问题，严格防范 FTO 漏检 |
| **22** | 工程整合 | **PatentEvidence 增量平滑追加** | 保留原生 Alembic 迁移链与模块边界，追加 RLS 与审计中间件 |

---

## 3. 业务全景与双角色 Stage-Gate 流程

```mermaid
sequenceDiagram
    autonumber
    actor RD as 研发工程师 (R&D)
    participant Platform as PatentEvidence 平台
    participant Engine as 比对与规避引擎
    actor IP as 专利工程师/法务 (IP Counsel)
    participant TSA as 双轨司法/RFC3161 存证中心

    Note over RD,IP: 阶段一：方案录入与智能初筛
    RD->>Platform: 提交新产品结构技术方案 (白话/交底书)
    Platform->>Platform: BYOK 加密入库，触发脱敏解析
    Platform->>Engine: 混合检索 (Dense + BM25 + 分类过滤)
    Engine-->>Platform: 召回 Top 20~30 件竞品高危专利

    Note over RD,IP: 阶段二：逐特征比对 (Claim Chart)
    Platform->>Engine: 针对涉案权项执行特征拆解与相似度比对
    Engine-->>Platform: 生成结构化 Claim Chart 初稿 (标记红/黄/绿风险)
    IP->>Platform: 登录工作台，复核 Claim Chart 判定值，调整等同侵权评级

    alt 存在字面侵权或等同侵权高危 (Red / Yellow)
        Note over RD,IP: 阶段三：规避设计与闭环反向验真
        IP->>Platform: 标记特征断点，请求规避方案
        Platform->>Engine: 生成 2~3 个结构化规避改动方案
        Engine->>Engine: 【核心】反向比对竞品从属权项与同族专利池
        Engine-->>Platform: 过滤出“二次零落入”的纯净规避建议
        Platform-->>RD: 推送规避建议指引
        RD->>Platform: 采纳建议，修改结构设计，提交 V2 方案版本
        Platform->>Engine: V2 方案增量复验
        Engine-->>Platform: 确认特征覆盖已阻断 (变为 Green)
    end

    Note over RD,IP: 阶段四：终审封存与 Stage-Gate 凭证
    IP->>Platform: 终审批准 (Approve) 并发起证据封存
    Platform->>Platform: 计算 Merkle Root SHA-256，打包快照包
    Platform->>TSA: 请求国家司法链凭据 + 国际 RFC 3161 时间戳
    TSA-->>Platform: 返回双轨法定时间戳与可信摘要
    Platform-->>RD: 签发《FTO 清障通行凭证》(用于 PLM/ERP 研发放行)
    Platform-->>IP: 归档不可篡改证据包 (随时可唤起外部律师复核签署)
```

---

## 4. 系统技术架构与模型双路由

```mermaid
graph TB
    subgraph ClientLayer["客户端与协同界面 (Next.js / TypeScript)"]
        UI1["研发方案工作台<br/>(白话输入 / 规避指引)"]
        UI2["IP 证据工作台<br/>(Claim Chart / 决策评审)"]
        UI3["平台治理控制台<br/>(MFA / BYOK / 审计流)"]
    end

    subgraph GatewayLayer["安全网关与平台治理 (FastAPI / Tenant Context)"]
        GW1["Tenant RLS 拦截器"]
        GW2["BYOK 字段加解密中间件"]
        GW3["不可篡改 Audit Outbox 记录器"]
    end

    subgraph ServiceModules["核心业务模块 (Python / modules/)"]
        M_Cases["cases & features<br/>案卷与特征建模"]
        M_Retrieval["retrieval<br/>混合检索与重排"]
        M_Comparison["comparison<br/>特征比对与等同分析"]
        M_DesignAround["design-around (新增)<br/>反向验真规避引擎"]
        M_Review["review<br/>双角色门禁审批流"]
        M_Evidence["evidence & delivery<br/>Merkle 封存与交付网关"]
    end

    subgraph DualRouting["模型敏感度双路由 (LLM Router)"]
        Route1["公开专利离线解构: 全球顶级模型 (Claude 3.5 / GPT-4o)"]
        Route2["客户保密方案计算: 境内零留存模型 (通义千问 / DeepSeek 企业版)"]
    end

    subgraph StorageLayer["持久化与存证层"]
        DB[(PostgreSQL + pgvector<br/>Tenant RLS 隔离)]
        S3[(MinIO / S3<br/>加密证据快照包)]
        Anchoring["双轨时间戳存证<br/>司法链 + RFC 3161 TSA"]
    end

    ClientLayer --> GatewayLayer
    GatewayLayer --> ServiceModules
    ServiceModules --> DualRouting
    ServiceModules --> StorageLayer
```

---

## 5. PatentEvidence 与 PatentQ 代码库整合方案

### 5.1 目录组织演进
保持 `PatentEvidence` 的 pnpm workspace + Python backend monorepo 结构：
```text
PatentEvidence/
├── apps/
│   ├── web/                     # 前端应用 (Next.js, 承载研发与 IP 双工作台)
│   └── docs/                    # 规范与说明文档
├── modules/
│   ├── platform/                # 【从 PatentQ 移植】多租户、MFA、应急访问、组织管理
│   ├── cases/                   # 案卷与方案元数据
│   ├── features/                # 权利要求与方案技术特征模型
│   ├── retrieval/               # 混合检索、BM25与向量召回
│   ├── comparison/              # 逐特征 Claim Chart 比对引擎与规则包
│   ├── design_around/           # 【新模块】规避建议生成与闭环反向验真
│   ├── review/                  # 双角色审批、Stage-Gate 门禁流
│   ├── evidence/                # Merkle Tree、存证快照打包
│   └── delivery/                # 客户交付网关与在线验证页
├── adapters/
│   ├── auth/                    # 【从 PatentQ 移植】JWT, MFA, RLS 上下文适配器
│   ├── secret_store/            # BYOK 客户密钥解密适配器
│   ├── llm/                     # 敏感度双路由 LLM 客户端
│   ├── tsa/                     # 【新增】司法链与 RFC 3161 时间戳客户端
│   └── vector_store/            # pgvector / 检索适配器
├── db/
│   └── alembic/                 # 统一迁移脚本（在原迁移上平滑追加 RLS 与审计）
```

### 5.2 数据库迁移平滑演进路径
1. **0001~000X（现存迁移）**：保留 PatentEvidence 现有的 cases, features, comparisons, evidence 表。
2. **新增迁移 000X+1**：移植 PatentQ 的 `tenants`, `memberships`, `mfa_credentials`, `audit_events` 表。
3. **新增迁移 000X+2**：在核心业务表上启用 PostgreSQL `ENABLE ROW LEVEL SECURITY`，注入 `app.current_tenant_id` 策略。
4. **新增迁移 000X+3**：增加 `design_around_candidates`, `stage_gate_passes`, `tsa_certificates` 表。

---

## 6. M1（里程碑一）8 周落地实施规划

**目标**：8 周内打通中国 + 美国结构类专利的“方案录入 → 混合检索 → Claim Chart 判定 → 规避反向验真 → 双轨存证封存”完整闭环，达到可向 2~3 家锂电出海企业进行付费 Pilot 演示与交付的标准。

```mermaid
gantt
    title M1 (8 周) 迭代冲刺计划
    dateFormat  YYYY-MM-DD
    section Week 1-2 基础设施与治理融合
    PatentQ 治理移植 (RLS/MFA/Audit)      :w1, 2026-10-05, 10d
    Alembic 平滑迁移与 CI/CD 贯通           :w2, after w1, 4d
    section Week 3-4 垂直库与混合召回
    Top 15 锂电结构专利数据入库 (5k~8k)     :w3, 2026-10-15, 8d
    特征解构离线批处理与 pgvector 建立     :w4, after w3, 6d
    混合检索 (Dense + BM25 + 重排) 调优     :w5, after w4, 4d
    section Week 5-6 比对引擎与规避反向验真
    中美结构类侵权比对规则包适配           :w6, 2026-10-25, 7d
    规避建议生成与从属权项二次闭环验真     :w7, after w6, 7d
    真实判例基准测试集 (Eval Benchmark)     :w8, after w7, 4d
    section Week 7-8 双角色协同与存证封存
    双角色 Stage-Gate 交互界面适配         :w9, 2026-11-08, 7d
    国内时间戳 + RFC 3161 双轨集成         :w10, after w9, 5d
    首单 Pilot 端到端联调与种子客户演示包  :w11, after w10, 4d
```

---

## 7. 下一步实施准备确认

此规划已固化前述全部 22 项决策，形成了闭环的产品架构与技术路线。请确认本方案是否完整符合您的预期。确认后，我们将正式进入代码与工程执行阶段。
