# 平台管理员引导手册 (Platform Bootstrap Runbook)

## 目标
在全新或重置的生产/演练环境中，安全初始化首位全局平台管理员（`platform_admin`）身份，并在 10 分钟内完成 TOTP 双因子认证绑定。

## 前置条件
- 已配置并连接 PostgreSQL 迁移数据库角色（`patent_evidence_migration`）；
- 已配置环境密钥 `PE_MFA_ENCRYPTION_KEY`（32字节 Fernet 密钥）；
- 严禁通过命令行位置参数直接传入明文密码。

## 操作步骤

### 1. 执行平台管理员引导脚本
```sh
export PE_MIGRATION_DATABASE_URL="postgresql://patent_evidence_migration:secret@localhost:5432/patent_evidence"
export PE_BOOTSTRAP_PLATFORM_ADMIN_EMAIL="admin@patentevidence.com"
export PE_MFA_ENCRYPTION_KEY="<base64-encoded-fernet-key>"

# 执行引导（支持安全密码提示输入或环境变量注入）
.venv/bin/python scripts/bootstrap-platform-admin.py
```

### 2. 引导输出说明
成功执行后，脚本将输出：
- 平台管理员身份 ID；
- 临时 TOTP 密钥与确认截止时间（10 分钟内）；
- **注意**：若存在已有平台管理员，脚本将拒绝再次初始化并安全退出。

### 3. 完成 TOTP 确认
在身份验证器 App（Google Authenticator / 1Password）录入密钥后，登录系统或通过 API 完成首核确认：
```sh
curl -X POST http://localhost:8000/api/v1/auth/mfa/totp/confirm \
  -H "Content-Type: application/json" \
  -d '{"credential_id": "<CREDENTIAL_ID>", "code": "<6_DIGIT_CODE>"}'
```

## 回滚与应急处置
若引导过程因意外中断导致 TOTP 未能在 10 分钟内确认，可由运维使用迁移权限清除非活动管理员记录后重新执行引导。
