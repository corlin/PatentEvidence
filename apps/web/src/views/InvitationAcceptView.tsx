import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { StatusBadge } from '../components/StatusBadge'
import type { InvitationInspection } from '../types/api'
import { Link, useNavigate, useRouter } from '../router/Router'

export const InvitationAcceptView: React.FC = () => {
  const { search } = useRouter()
  const { session, refreshSession, setActiveOrgId } = useSession()
  const navigate = useNavigate()

  const params = new URLSearchParams(search)
  const tokenFromUrl = params.get('token') || ''

  const [token, setToken] = useState(tokenFromUrl)
  const [inspection, setInspection] = useState<InvitationInspection | null>(null)
  const [inspectLoading, setInspectLoading] = useState(false)
  const [inspectError, setInspectError] = useState<string | null>(null)

  // Acceptance Form for new users
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [acceptLoading, setAcceptLoading] = useState(false)
  const [acceptError, setAcceptError] = useState<string | null>(null)
  const [acceptedSuccess, setAcceptedSuccess] = useState(false)

  const inspectToken = async (tokenValue: string) => {
    if (!tokenValue.trim()) return
    setInspectLoading(true)
    setInspectError(null)

    try {
      const data = await apiClient.inspectInvitation(tokenValue.trim())
      setInspection(data)
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          setInspectError('邀请链接无效、不存在或已超过 72 小时有效期。')
        } else {
          setInspectError(err.detail || '检查邀请信息失败。')
        }
      } else {
        setInspectError('网络请求失败，请稍后重试。')
      }
      setInspection(null)
    } finally {
      setInspectLoading(false)
    }
  }

  useEffect(() => {
    if (tokenFromUrl) {
      inspectToken(tokenFromUrl)
    }
  }, [tokenFromUrl])

  const handleAcceptSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token) return

    if (!inspection?.existing_identity) {
      if (!displayName.trim()) {
        setAcceptError('请输入您的真实姓名。')
        return
      }
      if (password !== confirmPassword) {
        setAcceptError('两次输入的密码不一致。')
        return
      }
      if (password.length < 12) {
        setAcceptError('密码长度需至少 12 个字符。')
        return
      }
    }

    setAcceptLoading(true)
    setAcceptError(null)

    try {
      const res = await apiClient.acceptInvitation({
        token: token.trim(),
        display_name: inspection?.existing_identity ? undefined : displayName.trim(),
        password: inspection?.existing_identity ? undefined : password,
      })

      setAcceptedSuccess(true)
      setActiveOrgId(res.membership.organization_id)
      await refreshSession()

      setTimeout(() => {
        navigate(`/organizations/${res.membership.organization_id}/members`)
      }, 2000)
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          setAcceptError('邀请已失效或已被使用。')
        } else if (err.status === 422) {
          setAcceptError('密码或注册信息不符合安全策略规范。')
        } else {
          setAcceptError(err.detail || '接受邀请失败。')
        }
      } else {
        setAcceptError('网络连接失败，请重试。')
      }
    } finally {
      setAcceptLoading(false)
    }
  }

  return (
    <div className="auth-card-container">
      <div className="card auth-card max-w-lg">
        <div className="card-header text-center">
          <h1 className="card-title text-xl font-bold">机构加入邀请</h1>
          <p className="card-subtitle text-sm text-secondary">
            您受邀加入 PatentEvidence 代理机构工作空间
          </p>
        </div>

        {inspectError && <Alert type="error" message={inspectError} />}
        {acceptError && <Alert type="error" message={acceptError} />}

        {acceptedSuccess ? (
          <div className="text-center py-md">
            <span className="badge badge-success mb-sm">加入成功</span>
            <p className="font-medium text-base mb-xs">
              已成功加入机构“{inspection?.organization.display_name}”！
            </p>
            <p className="text-sm text-secondary">正在为您跳转至机构工作台...</p>
          </div>
        ) : !inspection ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              inspectToken(token)
            }}
            className="form-stack"
          >
            <div className="form-group">
              <label htmlFor="invitation-token-input" className="form-label">
                输入 72 小时单次邀请凭证 (Token)
              </label>
              <input
                id="invitation-token-input"
                type="text"
                className="input-text font-mono text-xs"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="例如: d8f3a9e..."
                required
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={inspectLoading || !token.trim()}
            >
              {inspectLoading ? '正在校验...' : '解析邀请信息'}
            </button>
            <div className="text-center mt-sm">
              <Link to="/login" className="btn-link text-xs">
                返回登录
              </Link>
            </div>
          </form>
        ) : (
          <div className="form-stack">
            <div className="invitation-preview-card p-sm bg-neutral rounded border">
              <div className="flex-between mb-xs">
                <span className="text-xs text-secondary">受邀机构：</span>
                <strong className="text-sm font-bold">
                  {inspection.organization.display_name}
                </strong>
              </div>
              <div className="flex-between mb-xs">
                <span className="text-xs text-secondary">受邀邮箱：</span>
                <span className="text-xs font-mono">{inspection.email}</span>
              </div>
              <div className="flex-between mb-xs">
                <span className="text-xs text-secondary">分配角色：</span>
                <span className="role-tag font-mono text-xs">{inspection.role}</span>
              </div>
              <div className="flex-between">
                <span className="text-xs text-secondary">邀请状态：</span>
                <StatusBadge status={inspection.status} />
              </div>
            </div>

            {session && session.email.toLowerCase() !== inspection.email.toLowerCase() && (
              <Alert type="warning">
                提示：当前已登录账号 (<code>{session.email}</code>) 与邀请邮箱 (
                <code>{inspection.email}</code>) 不一致。接受后将把新机构加入当前身份。
              </Alert>
            )}

            <form onSubmit={handleAcceptSubmit} className="form-stack mt-sm">
              {!inspection.existing_identity && !session && (
                <>
                  <div className="form-group">
                    <label className="form-label">真实姓名</label>
                    <input
                      type="text"
                      className="input-text"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      placeholder="例如：张明"
                      required
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">设置登录密码 (至少 12 位)</label>
                    <input
                      type="password"
                      className="input-text"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••"
                      required
                      minLength={12}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">确认密码</label>
                    <input
                      type="password"
                      className="input-text"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="••••••••••••"
                      required
                      minLength={12}
                    />
                  </div>
                </>
              )}

              <button
                type="submit"
                className="btn btn-primary btn-block"
                disabled={acceptLoading}
              >
                {acceptLoading ? '正在激活账号并加入...' : '确认接受邀请并加入'}
              </button>

              <div className="text-center mt-xs">
                <button
                  type="button"
                  className="btn-link text-xs text-secondary"
                  onClick={() => setInspection(null)}
                >
                  输入其他邀请令牌
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}
