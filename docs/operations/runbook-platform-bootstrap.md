# 平台管理员引导手册 (Platform Bootstrap Runbook)

## 目标
在全新或重置的生产/演练环境中，安全初始化首位全局平台管理员（`platform_admin`）身份，并在 30 分钟交接期限内完成 TOTP 双因子认证绑定与首次特权操作。

## 前置条件
- 已配置并连接 PostgreSQL 迁移数据库角色（`patent_evidence_migration`）；
- 已配置环境密钥 `PE_MFA_ENCRYPTION_KEY`（32字节 Fernet 密钥）；
- 严禁通过命令行位置参数直接传入明文密码。

## 操作步骤

### 1. 执行平台管理员引导脚本

脚本接口（以 `scripts/bootstrap-platform-admin.py` 为准）：两个位置参数（邮箱、显示名）；
数据库地址与初始密码来自 `PATENT_EVIDENCE_*` 环境变量。未设置密码变量时，脚本以安全提示读取密码。

```sh
export PATENT_EVIDENCE_MIGRATION_DATABASE_URL="postgresql://patent_evidence_migration:<secret>@localhost:5432/patent_evidence"
export PATENT_EVIDENCE_MFA_ENCRYPTION_KEY="<base64-encoded-fernet-key>"
# 可选：不设置时脚本会提示输入
export PATENT_EVIDENCE_BOOTSTRAP_PASSWORD="<initial-password>"

.venv/bin/python scripts/bootstrap-platform-admin.py admin@patentevidence.com "Platform Administrator"
```

脚本在以下情况拒绝执行并以非零状态退出：已存在平台管理员授权；邮箱已注册；邮箱或显示名无效；
密码不符合密码策略；未设置 `PATENT_EVIDENCE_MIGRATION_DATABASE_URL`。

### 2. 引导输出说明

成功时脚本**不输出任何凭据**（不输出密码、TOTP 密钥或身份 ID），只输出：

- `Platform administrator created. No credential material was printed.`
- 运维交接截止时间（自创建起 30 分钟，即脚本中的 `MFA_HANDOFF_LIFETIME`）。

### 3. 在截止时间前完成 TOTP 与首次特权操作

脚本不创建 TOTP。管理员须在截止时间前：

1. 用邮箱和初始密码登录（`POST /api/v1/auth/login`）；
2. 注册 TOTP（`POST /api/v1/auth/mfa/totp/enroll`，返回 `credential_id` 与密钥，录入身份验证器 App）；
3. 确认 TOTP（`POST /api/v1/auth/mfa/totp/confirm`，成功返回 `"status": "confirmed"` 与一次性恢复码）；
4. 完成第一次平台特权操作。

```sh
curl -X POST http://localhost:8000/api/v1/auth/mfa/totp/confirm \
  -H "Content-Type: application/json" \
  -d '{"credential_id": "<CREDENTIAL_ID>", "code": "<6_DIGIT_CODE>"}'
```

该流程由集成测试 `apps/api/tests/integration/test_p0_02_e2e_lifecycle.py` 覆盖。

## 回滚与应急处置
若引导过程因意外中断导致 TOTP 与首次特权操作未能在 30 分钟交接期限内完成，可由运维使用迁移权限清除非活动管理员记录后重新执行引导。
