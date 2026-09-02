# 安全事件应急隔离手册 (Security Incident Containment Runbook)

## 目标
当怀疑发生跨租户越权、凭据外泄或非授权平台操作时，进行分钟级的租户隔离、权限冻结与审计日志提取。

## 应急处置流水线 (P0 响应)

### 第 1 步：秒级暂停目标机构
若怀疑某机构正在遭受攻击或存在数据异常：
1. 平台管理员在 `/platform/organizations` 找到目标机构并点击“暂停”；
2. 或通过 API 携带平台角色立即发送暂停请求：
```sh
curl -X POST http://localhost:8000/api/v1/platform/organizations/<ORG_UUID>/suspend \
  -H "Idempotency-Key: incident-suspend-<TIMESTAMP>" \
  -H "Cookie: pe_session=<PLATFORM_SESSION>"
```
> **效果**：所有发往该机构的 API 请求立即返回安全 404，完全阻断数据读取与写入。

### 第 2 步：冻结涉事全局身份
由平台管理员重置涉事用户的安全版本或注销会话：
```sql
UPDATE global_identities
SET status = 'suspended', security_version = security_version + 1, updated_at = NOW()
WHERE id = '<SUSPECTED_IDENTITY_UUID>';
```

### 第 3 步：提取不可变审计证据流
系统将所有操作尝试（包括被安全策略拦截的失败/越权尝试）记录在只增不减的审计表中：
- **平台级审计**：查询 `platform_audit_events` 表，提取关联的 `Request-Correlation-ID`、操作类型与目标摘要；
- **机构级审计**：查询 `organization_audit_events` 表，提取特定租户上下文内的变更轨迹。
> **注意**：审计日志中已做脱敏，不含密码哈希、Cookie、Token 或 TOTP 密文。
