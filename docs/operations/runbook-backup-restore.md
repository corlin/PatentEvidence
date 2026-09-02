# 数据库备份还原与权限属主手册 (Backup and Restore Runbook)

## 目标
指导运维团队进行 PostgreSQL 数据库的快照备份、容灾还原，并确保受限数据库角色与 Row Level Security (RLS) 策略在还原后完整生效。

## 角色安全基线
PatentEvidence 遵循严格的受限数据库角色最小特权划分：
- `patent_evidence_migration`: 迁移属主（建表、建索引、定义 RLS 策略）；
- `patent_evidence_app`: 应用程序业务角色（受 RLS 限制，禁止直接访问未授权租户数据）；
- `patent_evidence_platform`: 平台治理特权角色（开通机构、平台审计，严禁读取用户密码哈希）；
- `patent_evidence_worker`: 后台工作池角色。

## 备份流程

### 1. 物理/逻辑备份导出
使用 `pg_dump` 导出包含对象属主和策略定义的完整 SQL/自定义转储：
```sh
pg_dump -U postgres -d patent_evidence --format=custom --file=patent_evidence_backup_$(date +%Y%m%d_%H%M%S).dump
```

## 还原与属主校验流程

### 1. 数据库对象还原
```sh
pg_restore -U postgres -d patent_evidence --clean --if-exists patent_evidence_backup.dump
```

### 2. 检查并强制启用 RLS
还原后必须运行以下 SQL 检查所有组织级业务表均启用了 `FORCE ROW LEVEL SECURITY`：
```sql
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class
WHERE relname IN (
  'organization_memberships',
  'organization_invitations',
  'organization_plan_quotas',
  'organization_audit_events'
);
```
> **断言标准**：`relrowsecurity` 与 `relforcerowsecurity` 必须全部为 `true`。

### 3. 执行自动化验证脚本
还原完成后，立即执行 `./scripts/test-postgres.sh` 确保所有角色权限与租户隔离逻辑 100% 正常。
