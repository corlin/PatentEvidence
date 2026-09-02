import React, { useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Link, useNavigate } from '../router/Router'

export const MfaChallengeView: React.FC = () => {
  const { refreshSession } = useSession()
  const navigate = useNavigate()

  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      if (useRecovery) {
        await apiClient.challengeMfa({ recovery_code: code.trim() })
      } else {
        await apiClient.challengeMfa({ code: code.trim() })
      }
      await refreshSession()
      navigate('/')
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError(useRecovery ? '恢复码无效或已被使用。' : '动态验证码错误，请重新输入。')
        } else if (err.status === 429) {
          setError('验证尝试过于频繁，请稍后再试。')
        } else {
          setError(err.detail || '验证失败。')
        }
      } else {
        setError('网络请求异常，请检查连接。')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-card-container">
      <div className="card auth-card">
        <div className="card-header text-center">
          <h1 className="card-title text-xl">两步验证 (MFA)</h1>
          <p className="card-subtitle text-sm text-secondary">
            {useRecovery
              ? '请输入您保存的 8 组一次性恢复码之一'
              : '请输入身份验证器（如 Google Authenticator）生成的 6 位动态验证码'}
          </p>
        </div>

        {error && <Alert type="error" message={error} />}

        <form onSubmit={handleSubmit} className="form-stack">
          <div className="form-group">
            <label htmlFor="mfa-code-input" className="form-label">
              {useRecovery ? '一次性恢复码' : '6 位动态验证码'}
            </label>
            <input
              id="mfa-code-input"
              type="text"
              className="input-text text-center font-mono tracking-widest text-lg"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={useRecovery ? 'abcdef123456' : '000000'}
              maxLength={useRecovery ? 32 : 8}
              required
              autoFocus
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={loading || !code.trim()}
          >
            {loading ? '正在验证...' : '确认并进入工作台'}
          </button>

          <div className="flex-between mt-sm">
            <button
              type="button"
              className="btn-link text-xs"
              onClick={() => {
                setUseRecovery(!useRecovery)
                setError(null)
                setCode('')
              }}
            >
              {useRecovery ? '← 返回使用动态验证码' : '使用一次性恢复码登录'}
            </button>
            <Link to="/login" className="btn-link text-xs text-secondary">
              返回登录
            </Link>
          </div>
        </form>
      </div>
    </div>
  )
}
