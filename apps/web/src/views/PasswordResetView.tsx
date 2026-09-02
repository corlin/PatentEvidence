import React, { useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { Alert } from '../components/Alert'
import { Link, useNavigate, useRouter } from '../router/Router'

export const PasswordResetView: React.FC = () => {
  const { search } = useRouter()
  const navigate = useNavigate()

  const params = new URLSearchParams(search)
  const tokenFromUrl = params.get('token') || ''

  const [email, setEmail] = useState('')
  const [token, setToken] = useState(tokenFromUrl)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const handleRequestSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setLoading(true)

    try {
      await apiClient.requestPasswordReset(email.trim())
      setSuccessMessage('若该邮箱匹配有效的机构账户，重置指令已发出，请按提示操作。')
    } catch (err: any) {
      if (err instanceof ApiError) {
        setError(err.detail || '重置申请失败。')
      } else {
        setError('网络请求失败。')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPassword !== confirmPassword) {
      setError('两次输入的密码不一致。')
      return
    }
    if (newPassword.length < 12) {
      setError('密码长度需至少 12 个字符。')
      return
    }

    setError(null)
    setLoading(true)

    try {
      await apiClient.confirmPasswordReset(token.trim(), newPassword)
      setSuccessMessage('密码重置成功！即将为您跳转到登录页面...')
      setTimeout(() => {
        navigate('/login')
      }, 2000)
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 400 || err.status === 404) {
          setError('重置链接无效或已过期，请重新申请。')
        } else if (err.status === 422) {
          setError('密码不符合安全策略要求（需至少 12 位）。')
        } else {
          setError(err.detail || '密码重置失败。')
        }
      } else {
        setError('重置失败，请检查网络连接。')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-card-container">
      <div className="card auth-card">
        <div className="card-header text-center">
          <h1 className="card-title text-xl">重置登录密码</h1>
          <p className="card-subtitle text-sm text-secondary">
            {token ? '请设置您的新密码' : '输入您的注册邮箱以申请密码重置'}
          </p>
        </div>

        {error && <Alert type="error" message={error} />}
        {successMessage && <Alert type="success" message={successMessage} />}

        {token ? (
          <form onSubmit={handleConfirmSubmit} className="form-stack">
            <div className="form-group">
              <label htmlFor="reset-token-input" className="form-label">
                重置令牌 (Token)
              </label>
              <input
                id="reset-token-input"
                type="text"
                className="input-text font-mono text-xs"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="reset-new-password" className="form-label">
                新密码 (至少 12 位)
              </label>
              <input
                id="reset-new-password"
                type="password"
                className="input-text"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="••••••••••••"
                required
                minLength={12}
                autoFocus
              />
            </div>

            <div className="form-group">
              <label htmlFor="reset-confirm-password" className="form-label">
                确认新密码
              </label>
              <input
                id="reset-confirm-password"
                type="password"
                className="input-text"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••••••"
                required
                minLength={12}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={loading || !newPassword || !confirmPassword}
            >
              {loading ? '正在更新密码...' : '确认重置密码'}
            </button>

            <div className="text-center mt-sm">
              <Link to="/login" className="btn-link text-xs">
                返回登录
              </Link>
            </div>
          </form>
        ) : (
          <form onSubmit={handleRequestSubmit} className="form-stack">
            <div className="form-group">
              <label htmlFor="reset-email" className="form-label">
                注册邮箱
              </label>
              <input
                id="reset-email"
                type="email"
                className="input-text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                required
                autoFocus
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={loading || !email.trim()}
            >
              {loading ? '正在提交...' : '发送重置请求'}
            </button>

            <div className="flex-between mt-sm">
              <button
                type="button"
                className="btn-link text-xs"
                onClick={() => setToken('manual-token')}
              >
                已有重置令牌？直接输入
              </button>
              <Link to="/login" className="btn-link text-xs">
                返回登录
              </Link>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
