# 凭据与会话轮换运维手册 (Credential and MFA Rotation Runbook)

## 目标
指导平台管理员与机构管理员进行日常密码修改、TOTP 重新绑定、会话撤销及应急全局凭据失效。

## 场景操作指引

### 1. 用户主动更新密码
- 登录后访问或直接在登出状态下通过 `/password-reset` 提交邮箱重置申请；
- 收到重置令牌后，在重置页面输入至少 12 位新密码；
- 密码更新成功后，系统自动使历史重置令牌失效。

### 2. 用户重新绑定 TOTP MFA
- 用户登录后访问 `/mfa/enroll`；
- 需近期已完成 MFA 授权（Step-Up 拦截）；
- 生成新密钥并确认后，历史 TOTP 凭证状态自动标记为 `revoked`，系统重新下发 8 组一次性恢复码。

### 3. 会话批量撤销 (Session Revocation)
- **单个用户撤销**：用户调用 `POST /api/v1/auth/sessions/revoke`，该全局身份在所有设备上的现有会话全部作废。
- **安全版本递增 (Security Version Bump)**：当检测到身份凭据泄露时，后端数据库更新 `global_identities.security_version`，强制使所有旧 Session 瞬间不可用。

### 4. 机构管理员协助重置成员 MFA
若机构成员丢失手机验证器且无恢复码：
- 机构管理员在 `/organizations/:id/members` 界面对应成员处发起 MFA 重置请求；
- 重置后目标成员降级为仅密码登录状态，并在下次登录时强制重新配置 TOTP。
