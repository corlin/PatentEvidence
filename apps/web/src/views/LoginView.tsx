import React, { useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Link, useNavigate } from '../router/Router'

export const LoginView: React.FC = () => {
  const { refreshSession } = useSession()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      await apiClient.login(email.trim(), password)
      const session = await refreshSession()
      if (session) {
        navigate('/')
      } else {
        navigate('/mfa/challenge')
      }
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError('邮箱或密码不正确，请重新输入。')
        } else if (err.status === 429) {
          setError('登录尝试过于频繁，请稍后重试。')
        } else if (err.status === 503) {
          setError('认证服务负载较高，请稍后重试。')
        } else {
          setError(err.detail || '登录失败，请稍后重试。')
        }
      } else {
        setError('网络请求失败，请检查连接。')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-card-container">
      <div className="card auth-card">
        <div className="card-header text-center">
          <h1 className="card-title text-xl">PatentEvidence</h1>
          <p className="card-subtitle text-sm text-secondary">
            专利检索与可专利性预评估工作台
          </p>
        </div>

        {error && <Alert type="error" message={error} />}

        <form onSubmit={handleSubmit} className="form-stack">
          <div className="form-group">
            <label htmlFor="login-email" className="form-label">
              工作邮箱
            </label>
            <input
              id="login-email"
              type="email"
              className="input-text"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="agent@example.com"
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <div className="flex-between">
              <label htmlFor="login-password" className="form-label">
                登录密码
              </label>
              <Link to="/password-reset" className="btn-link text-xs">
                忘记密码？
              </Link>
            </div>
            <input
              id="login-password"
              type="password"
              className="input-text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={loading || !email.trim() || !password}
          >
            {loading ? '正在安全登录...' : '登录'}
          </button>
        </form>

        <div className="card-footer text-center text-xs text-secondary mt-md">
          <span>受多租户强隔离与不可变审计保护</span>
        </div>
      </div>
    </div>
  )
}
