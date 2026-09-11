import React, { useEffect, useState } from 'react'
import { apiClient, ApiError, isMfaRequired } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { CreateOrganizationPayload, OrganizationSummary } from '../types/api'
import { Link } from '../router/Router'

export const PlatformOrganizationsView: React.FC = () => {
  const { requestMfaStepUp } = useSession()

  const [organizations, setOrganizations] = useState<OrganizationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Sprint 1：暂停机构的品牌确认对话框
  const [suspendTarget, setSuspendTarget] = useState<OrganizationSummary | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [isExpiryModalOpen, setIsExpiryModalOpen] = useState(false)
  const [selectedOrg, setSelectedOrg] = useState<OrganizationSummary | null>(null)
  const [expiryInput, setExpiryInput] = useState<string>('')

  // Creation State & Initial Token Result
  const [initialTokenResult, setInitialTokenResult] = useState<{
    orgName: string
    token: string
    adminEmail: string
  } | null>(null)

  const [createForm, setCreateForm] = useState<CreateOrganizationPayload>({
    slug: '',
    display_name: '',
    admin_email: '',
    plan_key: 'standard_agency',
    monthly_case_allowance: 20,
    current_period_start: new Date().toISOString(),
    current_period_end: new Date(Date.now() + 30 * 86400000).toISOString(),
    expires_at: null,
  })
  const [createLoading, setCreateLoading] = useState(false)

  const fetchOrganizations = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.listPlatformOrganizations()
      setOrganizations(res.items)
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(fetchOrganizations)
      } else {
        setError(err.detail || '获取机构列表失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchOrganizations()
  }, [])

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreateLoading(true)
    setError(null)

    try {
      const result = await apiClient.createPlatformOrganization({
        ...createForm,
        slug: createForm.slug.trim().toLowerCase(),
        admin_email: createForm.admin_email.trim().toLowerCase(),
        current_period_start: new Date(createForm.current_period_start).toISOString(),
        current_period_end: new Date(createForm.current_period_end).toISOString(),
        expires_at: createForm.expires_at ? new Date(createForm.expires_at).toISOString() : null,
      })

      setIsCreateModalOpen(false)
      setInitialTokenResult({
        orgName: result.organization.display_name,
        token: result.invitation_token,
        adminEmail: createForm.admin_email,
      })
      fetchOrganizations()
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(() => handleCreateSubmit(e))
      } else {
        setError(err.detail || '开通机构失败')
      }
    } finally {
      setCreateLoading(false)
    }
  }

  const handleSuspend = async (org: OrganizationSummary) => {
    setSuspendTarget(null)
    setError(null)
    try {
      await apiClient.suspendPlatformOrganization(org.id)
      setSuccess(`机构“${org.display_name}”已暂停。`)
      fetchOrganizations()
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(() => handleSuspend(org))
      } else {
        setError(err.detail || '暂停机构失败')
      }
    }
  }

  const handleReactivate = async (org: OrganizationSummary) => {
    setError(null)
    try {
      await apiClient.reactivatePlatformOrganization(org.id)
      setSuccess(`机构“${org.display_name}”已恢复激活。`)
      fetchOrganizations()
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(() => handleReactivate(org))
      } else {
        setError(err.detail || '恢复机构失败')
      }
    }
  }

  const handleUpdateExpiry = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedOrg) return
    setError(null)

    try {
      await apiClient.setPlatformOrganizationExpiry(
        selectedOrg.id,
        expiryInput ? new Date(expiryInput).toISOString() : null
      )
      setIsExpiryModalOpen(false)
      setSuccess(`机构“${selectedOrg.display_name}”到期时间已更新。`)
      fetchOrganizations()
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(() => handleUpdateExpiry(e))
      } else {
        setError(err.detail || '更新到期时间失败')
      }
    }
  }

  return (
    <div className="layout-container">
      <Header />

      <main id="main-content" className="main-content">
        <div className="page-header flex-between mb-md">
          <div>
            <h1 className="page-title text-2xl font-bold">平台机构管理</h1>
            <p className="text-secondary text-sm">
              管理多租户机构开通、配额策略与服务生命周期
            </p>
          </div>
          {!loading && organizations.length > 0 && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setError(null)
                setIsCreateModalOpen(true)
              }}
            >
              + 开通新机构
            </button>
          )}
        </div>

        {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
        {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

        {initialTokenResult && (
          <Alert type="warning" onClose={() => setInitialTokenResult(null)}>
            <div className="form-stack">
              <strong>机构“{initialTokenResult.orgName}”已成功开通！</strong>
              <p className="text-xs">
                初始管理员邀请凭证（一次性 Token）已生成，请复制并安全发送给{' '}
                <code>{initialTokenResult.adminEmail}</code>：
              </p>
              <div className="token-box font-mono text-xs select-all p-xs bg-dark text-white rounded">
                {window.location.origin}/invitations/accept?token={initialTokenResult.token}
              </div>
            </div>
          </Alert>
        )}

        <div className="card table-card">
          {loading ? (
            <div className="p-lg text-center text-secondary">正在安全加载机构列表...</div>
          ) : organizations.length === 0 ? (
            <div className="empty-state p-xl text-center">
              <p className="text-secondary mb-sm">暂无已开通的机构</p>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setIsCreateModalOpen(true)}
              >
                立即开通首家机构
              </button>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>机构名称</th>
                  <th>标识 (Slug)</th>
                  <th>当前状态</th>
                  <th>服务到期时间</th>
                  <th>创建时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {organizations.map((org) => (
                  <tr key={org.id}>
                    <td>
                      <Link
                        to={`/organizations/${org.id}/members`}
                        className="font-medium text-primary"
                      >
                        {org.display_name}
                      </Link>
                    </td>
                    <td>
                      <code className="text-xs">{org.slug}</code>
                    </td>
                    <td>
                      <StatusBadge status={org.effective_status} />
                    </td>
                    <td className="text-sm">
                      {org.expires_at ? new Date(org.expires_at).toLocaleDateString() : '长期有效'}
                    </td>
                    <td className="text-sm text-secondary">
                      {new Date(org.created_at).toLocaleDateString()}
                    </td>
                    <td className="text-right">
                      <div className="action-buttons-group">
                        <Link
                          to={`/organizations/${org.id}/members`}
                          className="btn btn-secondary btn-xs"
                        >
                          成员管理
                        </Link>
                        <button
                          type="button"
                          className="btn btn-secondary btn-xs"
                          onClick={() => {
                            setSelectedOrg(org)
                            setExpiryInput(
                              org.expires_at ? new Date(org.expires_at).toISOString().slice(0, 16) : ''
                            )
                            setIsExpiryModalOpen(true)
                          }}
                        >
                          设置到期
                        </button>
                        {org.persisted_status === 'active' ? (
                          <button
                            type="button"
                            className="btn btn-danger btn-xs"
                            onClick={() => setSuspendTarget(org)}
                          >
                            暂停
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-success btn-xs"
                            onClick={() => handleReactivate(org)}
                          >
                            恢复
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* Create Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        title="开通新代理机构"
        onClose={() => setIsCreateModalOpen(false)}
      >
        <form onSubmit={handleCreateSubmit} className="form-stack">
          <div className="form-group">
            <label className="form-label">机构名称</label>
            <input
              type="text"
              className="input-text"
              value={createForm.display_name}
              onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
              placeholder="例如：北京华智知识产权代理事务所"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">唯一标识 Slug (URL 路径使用，仅小写字母、数字与中划线)</label>
            <input
              type="text"
              className="input-text"
              value={createForm.slug}
              onChange={(e) => setCreateForm({ ...createForm, slug: e.target.value })}
              placeholder="例如：huazhi-ip"
              pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">首位机构管理员邮箱</label>
            <input
              type="email"
              className="input-text"
              value={createForm.admin_email}
              onChange={(e) => setCreateForm({ ...createForm, admin_email: e.target.value })}
              placeholder="admin@huazhi-ip.com"
              required
            />
          </div>

          <div className="grid-2-cols gap-sm">
            <div className="form-group">
              <label className="form-label">服务版本方案</label>
              <select
                className="input-text"
                value={createForm.plan_key}
                onChange={(e) => setCreateForm({ ...createForm, plan_key: e.target.value })}
              >
                <option value="standard_agency">标准机构版 (Standard)</option>
                <option value="professional_agency">专业高级版 (Professional)</option>
                <option value="enterprise_agency">企业旗舰版 (Enterprise)</option>
                <option value="trial_agency">试用版 (Trial)</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">每月案件配额 (件)</label>
              <input
                type="number"
                className="input-text"
                value={createForm.monthly_case_allowance}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    monthly_case_allowance: parseInt(e.target.value) || 0,
                  })
                }
                min={0}
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">到期时间 (可选，留空为长期有效)</label>
            <input
              type="datetime-local"
              className="input-text"
              value={createForm.expires_at || ''}
              onChange={(e) =>
                setCreateForm({ ...createForm, expires_at: e.target.value || null })
              }
            />
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsCreateModalOpen(false)}
              disabled={createLoading}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={createLoading}>
              {createLoading ? '正在创建...' : '确认开通'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Expiry Modal */}
      <Modal
        isOpen={isExpiryModalOpen}
        title={`设置机构到期时间 - ${selectedOrg?.display_name || ''}`}
        onClose={() => setIsExpiryModalOpen(false)}
      >
        <form onSubmit={handleUpdateExpiry} className="form-stack">
          <div className="form-group">
            <label className="form-label">服务到期时间 (清空输入并保存即为长期有效)</label>
            <input
              type="datetime-local"
              className="input-text"
              value={expiryInput}
              onChange={(e) => setExpiryInput(e.target.value)}
            />
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsExpiryModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary">
              保存到期时间
            </button>
          </div>
        </form>
      </Modal>

      {/* Sprint 1：暂停机构的品牌确认对话框 */}
      <ConfirmDialog
        isOpen={suspendTarget !== null}
        title="暂停该机构？"
        danger
        confirmLabel="确认暂停机构"
        onCancel={() => setSuspendTarget(null)}
        onConfirm={() => suspendTarget && handleSuspend(suspendTarget)}
      >
        <p>
          将暂停机构 <strong>{suspendTarget?.display_name ?? ''}</strong>，
          其成员将无法访问案件与工作台。
        </p>
        <p className="text-xs text-secondary mt-xs">
          恢复需平台管理员重新激活。历史数据与审计记录保留。
        </p>
      </ConfirmDialog>
    </div>
  )
}
