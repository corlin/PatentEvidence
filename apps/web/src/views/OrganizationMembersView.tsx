import React, { useEffect, useState } from 'react'
import { apiClient, ApiError, isMfaRequired } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { OrganizationMembership, OrganizationRole } from '../types/api'
import { Link, useRouter } from '../router/Router'

interface OrganizationMembersViewProps {
  orgId: string
}

export const OrganizationMembersView: React.FC<OrganizationMembersViewProps> = ({ orgId }) => {
  const { requestMfaStepUp } = useSession()

  const [members, setMembers] = useState<OrganizationMembership[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Modals
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false)
  const [isRoleModalOpen, setIsRoleModalOpen] = useState(false)
  const [selectedMember, setSelectedMember] = useState<OrganizationMembership | null>(null)
  const [newRole, setNewRole] = useState<OrganizationRole>('patent_agent')

  // Invite Form & Token Presentation
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<OrganizationRole>('patent_agent')
  const [inviteLoading, setInviteLoading] = useState(false)
  const [generatedInviteToken, setGeneratedInviteToken] = useState<{
    email: string
    token: string
  } | null>(null)

  // Sprint 1：破坏性成员操作改用品牌确认对话框
  const [suspendTarget, setSuspendTarget] = useState<OrganizationMembership | null>(null)
  const [removeTarget, setRemoveTarget] = useState<OrganizationMembership | null>(null)

  const fetchMembers = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.listOrganizationMembers(orgId)
      setMembers(res.items)
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (isMfaRequired(err)) {
          requestMfaStepUp(fetchMembers)
          return
        }
        if (err.status === 404) {
          setError('未找到该机构或您没有该机构的访问权限。')
          return
        }
      }
      setError(err.detail || '加载成员列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMembers()
  }, [orgId])

  const handleInviteSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setInviteLoading(true)
    setError(null)

    try {
      const res = await apiClient.createOrganizationInvitation(
        orgId,
        inviteEmail.trim().toLowerCase(),
        inviteRole
      )
      setIsInviteModalOpen(false)
      setGeneratedInviteToken({
        email: inviteEmail.trim(),
        token: res.invitation_token,
      })
      setInviteEmail('')
      fetchMembers()
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(() => handleInviteSubmit(e))
      } else {
        setError(err.detail || '发送邀请失败')
      }
    } finally {
      setInviteLoading(false)
    }
  }

  const handleRoleChangeSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedMember) return

    setError(null)
    try {
      await apiClient.updateMemberRole(orgId, selectedMember.id, newRole)
      setIsRoleModalOpen(false)
      setSuccess(`成员 ${selectedMember.email} 的角色已更新为 ${newRole}。`)
      fetchMembers()
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (isMfaRequired(err)) {
          requestMfaStepUp(() => handleRoleChangeSubmit(e))
          return
        }
        if (err.status === 400 || err.status === 409) {
          setError('操作被拒绝：机构必须至少保留一位活跃的机构管理员 (Organization Admin)。')
          return
        }
      }
      setError(err.detail || '修改角色失败')
    }
  }

  const handleSuspendMember = async (member: OrganizationMembership) => {
    setSuspendTarget(null)
    setError(null)

    try {
      await apiClient.suspendMember(orgId, member.id)
      setSuccess(`成员 ${member.email} 已暂停。`)
      fetchMembers()
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (isMfaRequired(err)) {
          requestMfaStepUp(() => handleSuspendMember(member))
          return
        }
        if (err.status === 400 || err.status === 409) {
          setError('操作被拒绝：机构必须至少保留一位活跃的机构管理员，不可暂停最后一位管理员。')
          return
        }
      }
      setError(err.detail || '暂停成员失败')
    }
  }

  const handleReactivateMember = async (member: OrganizationMembership) => {
    setError(null)
    try {
      await apiClient.reactivateMember(orgId, member.id)
      setSuccess(`成员 ${member.email} 已重新激活。`)
      fetchMembers()
    } catch (err: any) {
      if (isMfaRequired(err)) {
        requestMfaStepUp(() => handleReactivateMember(member))
      } else {
        setError(err.detail || '恢复成员失败')
      }
    }
  }

  const handleRemoveMember = async (member: OrganizationMembership) => {
    setRemoveTarget(null)
    setError(null)

    try {
      await apiClient.removeMember(orgId, member.id)
      setSuccess(`成员 ${member.email} 已被移除。`)
      fetchMembers()
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (isMfaRequired(err)) {
          requestMfaStepUp(() => handleRemoveMember(member))
          return
        }
        if (err.status === 400 || err.status === 409) {
          setError('操作被拒绝：机构必须至少保留一位活跃的机构管理员，不可移除最后一位管理员。')
          return
        }
      }
      setError(err.detail || '移除成员失败')
    }
  }

  return (
    <div className="layout-container">
      <Header />

      <main id="main-content" className="main-content">
        <div className="page-header flex-between mb-md">
          <div>
            <div className="breadcrumb text-xs text-secondary mb-xs">
              <Link to="/platform/organizations">← 平台机构管理</Link>
            </div>
            <h1 className="page-title text-2xl font-bold">机构成员与权限管理</h1>
            <p className="text-secondary text-sm">
              管理专利代理师、分析员与机构管理员，受最后管理员防移除并发保护
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setError(null)
              setIsInviteModalOpen(true)
            }}
          >
            + 邀请新成员
          </button>
        </div>

        {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
        {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

        {generatedInviteToken && (
          <Alert type="warning" onClose={() => setGeneratedInviteToken(null)}>
            <div className="form-stack">
              <strong>邀请已成功生成！</strong>
              <p className="text-xs">
                单次有效邀请链接已生成（有效期 72 小时）。请将下方链接发送给{' '}
                <code>{generatedInviteToken.email}</code>：
              </p>
              <div className="token-box font-mono text-xs select-all p-xs bg-dark text-white rounded">
                {window.location.origin}/invitations/accept?token={generatedInviteToken.token}
              </div>
            </div>
          </Alert>
        )}

        <div className="card table-card">
          {loading ? (
            <div className="p-lg text-center text-secondary">正在加载成员信息...</div>
          ) : members.length === 0 ? (
            <div className="empty-state p-xl text-center">
              <p className="text-secondary mb-sm">暂无成员记录</p>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>姓名 / 邮箱</th>
                  <th>机构角色</th>
                  <th>状态</th>
                  <th>加入时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <div className="member-name-block">
                        <strong className="text-sm">{m.display_name || '未设置姓名'}</strong>
                        <span className="text-xs text-secondary block">{m.email}</span>
                      </div>
                    </td>
                    <td>
                      <span className="role-tag font-mono text-xs">{m.role}</span>
                    </td>
                    <td>
                      <StatusBadge status={m.status} />
                    </td>
                    <td className="text-xs text-secondary">
                      {new Date(m.created_at).toLocaleDateString()}
                    </td>
                    <td className="text-right">
                      <div className="action-buttons-group">
                        <button
                          type="button"
                          className="btn btn-secondary btn-xs"
                          onClick={() => {
                            setSelectedMember(m)
                            setNewRole(m.role)
                            setIsRoleModalOpen(true)
                          }}
                        >
                          调整角色
                        </button>
                        {m.status === 'active' ? (
                          <button
                            type="button"
                            className="btn btn-secondary btn-xs"
                            onClick={() => setSuspendTarget(m)}
                          >
                            暂停
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-success btn-xs"
                            onClick={() => handleReactivateMember(m)}
                          >
                            恢复
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn-danger btn-xs"
                          onClick={() => setRemoveTarget(m)}
                        >
                          移除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* Invite Modal */}
      <Modal
        isOpen={isInviteModalOpen}
        title="邀请新成员加入机构"
        onClose={() => setIsInviteModalOpen(false)}
      >
        <form onSubmit={handleInviteSubmit} className="form-stack">
          <div className="form-group">
            <label className="form-label">成员邮箱</label>
            <input
              type="email"
              className="input-text"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="agent@agency.com"
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label">分配固定角色</label>
            <select
              className="input-select"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as OrganizationRole)}
            >
              <option value="patent_agent">patent_agent（专利代理师 / 检索员）</option>
              <option value="reviewer">reviewer（独立复核人）</option>
              <option value="organization_admin">organization_admin（机构管理员）</option>
            </select>
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsInviteModalOpen(false)}
              disabled={inviteLoading}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={inviteLoading}>
              {inviteLoading ? '正在生成邀请...' : '生成邀请链接'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Role Change Modal */}
      <Modal
        isOpen={isRoleModalOpen}
        title={`调整成员角色 - ${selectedMember?.email || ''}`}
        onClose={() => setIsRoleModalOpen(false)}
      >
        <form onSubmit={handleRoleChangeSubmit} className="form-stack">
          <div className="form-group">
            <label className="form-label">选择新角色</label>
            <select
              className="input-select"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as OrganizationRole)}
            >
              <option value="patent_agent">patent_agent（专利代理师）</option>
              <option value="reviewer">reviewer（复核人）</option>
              <option value="organization_admin">organization_admin（机构管理员）</option>
            </select>
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsRoleModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary">
              保存角色更改
            </button>
          </div>
        </form>
      </Modal>

      {/* Sprint 1：暂停成员的品牌确认对话框 */}
      <ConfirmDialog
        isOpen={suspendTarget !== null}
        title="暂停该成员的权限？"
        danger
        confirmLabel="确认暂停"
        onCancel={() => setSuspendTarget(null)}
        onConfirm={() => suspendTarget && handleSuspendMember(suspendTarget)}
      >
        <p>
          将暂停成员 <strong>{suspendTarget?.email ?? ''}</strong> 的机构访问权限，
          其会话将立即失效，但成员关系与历史审计记录保留。
        </p>
        <p className="text-xs text-secondary mt-xs">
          恢复权限需由机构管理员手动操作。
        </p>
      </ConfirmDialog>

      {/* Sprint 1：移除成员的品牌确认对话框 */}
      <ConfirmDialog
        isOpen={removeTarget !== null}
        title="从机构中移除该成员？"
        danger
        confirmLabel="确认移除"
        onCancel={() => setRemoveTarget(null)}
        onConfirm={() => removeTarget && handleRemoveMember(removeTarget)}
      >
        <p>
          将成员 <strong>{removeTarget?.email ?? ''}</strong> 从机构中移除，
          其当前权限将立即作废。
        </p>
        <p className="text-xs text-secondary mt-xs">
          此操作<b>不可撤销</b>：如需重新加入需重新发送邀请。
        </p>
      </ConfirmDialog>
    </div>
  )
}
