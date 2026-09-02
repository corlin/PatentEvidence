# 机构开通与生命周期运维手册 (Organization Provisioning Runbook)

## 目标
由平台管理员人工为签约的专利代理机构开通多租户工作空间、配置配额与有效期，并交付初始管理员邀请凭证。

## 前置条件
- 操作者已登录并具备 `platform_admin` 角色；
- 操作者近期（15 分钟内）已完成 TOTP MFA 验证。

## 操作步骤

### 方式 A：通过 Web 管理台开通（推荐）
1. 访问 `/platform/organizations`；
2. 点击右上角“+ 开通新机构”；
3. 填入机构中文全称、唯一标识 Slug、首位机构管理员邮箱、每月案件配额与服务到期时间；
4. 点击“确认开通”；
5. 复制弹出的 72 小时单次有效邀请链接（包含 `invitation_token`），通过加密邮件或可信渠道发送给机构主管。

### 方式 B：通过 CLI 开通
```sh
.venv/bin/python scripts/create-organization.py \
  --slug "huazhi-ip" \
  --display-name "北京华智知识产权代理事务所" \
  --admin-email "admin@huazhi-ip.com" \
  --plan-key "standard_agency" \
  --monthly-allowance 50
```

## 生命周期维护

### 1. 机构暂停 (Suspend)
当机构存在欠费或合规争议时，平台管理员可随时暂停其服务：
- 暂停后该机构所有成员访问均立即返回安全的 404；
- 数据保留不被删除。

### 2. 机构恢复 (Reactivate)
在平台管理页点击“恢复”，机构重新进入 `active` 状态。

### 3. 到期时间调整 (Expiry)
根据合同续约情况，在平台管理页设置新的到期时间（或清空以设为长期有效）。
系统基于 ADR 0002 动态派生有效状态，无需外部定时任务。
