import React, { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { useNavigate } from '../router/Router'
import { generateTotpCode } from '../utils/totp'

export const MfaEnrollView: React.FC = () => {
  const { session, refreshSession } = useSession()
  const navigate = useNavigate()

  const [credentialId, setCredentialId] = useState<string | null>(null)
  const [secret, setSecret] = useState<string | null>(null)
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null)
  const [copiedSecret, setCopiedSecret] = useState(false)
  const [code, setCode] = useState('')
  const [liveCode, setLiveCode] = useState<string>('')
  const [secondsRemaining, setSecondsRemaining] = useState<number>(30)
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let unmounted = false
    async function startEnroll() {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.enrollTotp()
        if (!unmounted) {
          setCredentialId(res.credential_id)
          setSecret(res.secret)

          // Calculate initial live code
          generateTotpCode(res.secret).then((c) => {
            if (!unmounted) setLiveCode(c)
          })

          // Generate QR code asynchronously
          const email = session?.email || 'user@patentevidence.com'
          const otpauthUrl = `otpauth://totp/PatentEvidence:${encodeURIComponent(email)}?secret=${res.secret}&issuer=PatentEvidence`
          QRCode.toDataURL(otpauthUrl, {
            width: 220,
            margin: 2,
            color: {
              dark: '#0f172a',
              light: '#ffffff',
            },
          })
            .then((dataUrl) => {
              if (!unmounted) setQrCodeUrl(dataUrl)
            })
            .catch(() => {})
        }
      } catch (err: any) {
        if (!unmounted) {
          if (err instanceof ApiError && err.status === 403) {
            setError('重新配置 MFA 需要近期身份授权。请先在登录界面完成一次验证。')
          } else {
            setError(err.detail || '初始化 MFA 设置失败。')
          }
        }
      } finally {
        if (!unmounted) setLoading(false)
      }
    }

    startEnroll()
    return () => {
      unmounted = true
    }
  }, [session?.email])

  // Live timer to calculate code for current clock
  useEffect(() => {
    if (!secret) return
    const interval = setInterval(async () => {
      const now = Date.now()
      const remaining = 30 - (Math.floor(now / 1000) % 30)
      setSecondsRemaining(remaining)
      const currentCode = await generateTotpCode(secret, now)
      setLiveCode(currentCode)
    }, 1000)

    return () => clearInterval(interval)
  }, [secret])

  const handleConfirm = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!credentialId || !code.trim()) return

    setLoading(true)
    setError(null)

    try {
      const res = await apiClient.confirmTotp(credentialId, code.trim())
      if (res.recovery_codes && res.recovery_codes.length > 0) {
        setRecoveryCodes(res.recovery_codes)
      } else {
        const rec = await apiClient.getRecoveryCodes()
        setRecoveryCodes(rec.recovery_codes)
      }
      await refreshSession()
    } catch (err: any) {
      if (err instanceof ApiError) {
        setError(
          err.status === 401
            ? '验证码无效。若使用物理手机 App，请注意系统当前处于 2026 仿真时钟，手机算出的动态码可能因时间差而不匹配，可直接使用下方的【一键填入】。'
            : err.detail
        )
      } else {
        setError('验证失败，请重试。')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleCopyCodes = () => {
    if (recoveryCodes) {
      navigator.clipboard.writeText(recoveryCodes.join('\n'))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleCopySecret = () => {
    if (secret) {
      navigator.clipboard.writeText(secret)
      setCopiedSecret(true)
      setTimeout(() => setCopiedSecret(false), 2000)
    }
  }

  const handleAutoFillLiveCode = () => {
    if (liveCode) {
      setCode(liveCode)
    }
  }

  if (recoveryCodes) {
    return (
      <div className="auth-card-container">
        <div className="card auth-card max-w-lg">
          <div className="card-header text-center">
            <span className="badge badge-success mb-xs">配置成功</span>
            <h1 className="card-title text-xl">保存您的一次性恢复码</h1>
            <p className="card-subtitle text-sm text-secondary">
              当您无法使用身份验证器时，恢复码是找回账号的唯一凭证。请将其保存在安全的地方。
            </p>
          </div>

          <div className="recovery-codes-box">
            <div className="grid-2-cols gap-xs font-mono text-sm">
              {recoveryCodes.map((c, i) => (
                <div key={i} className="recovery-code-item">
                  <span className="text-secondary text-xs mr-xs">{i + 1}.</span>
                  <strong>{c}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="flex-stack gap-sm mt-md">
            <button type="button" className="btn btn-secondary btn-block" onClick={handleCopyCodes}>
              {copied ? '✓ 已复制到剪贴板' : '复制全部恢复码'}
            </button>
            <button
              type="button"
              className="btn btn-primary btn-block"
              onClick={() => navigate('/')}
            >
              我已妥善保存，进入工作台
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-card-container">
      <div className="card auth-card max-w-lg">
        <div className="card-header text-center">
          <h1 className="card-title text-xl">配置两步验证 (TOTP)</h1>
          <p className="card-subtitle text-sm text-secondary">
            使用手机身份验证器扫描二维码或输入密钥绑定，保障专利资产安全
          </p>
        </div>

        {error && <Alert type="error" message={error} />}

        {secret ? (
          <div className="form-stack">
            {/* Step 1: QR Code Scan & Manual Key */}
            <div className="text-center p-sm bg-subtle border rounded flex-stack align-center gap-xs">
              <p className="text-xs font-semibold text-text mb-xs">
                第一步：打开身份验证器 App 扫描二维码
              </p>
              {qrCodeUrl ? (
                <div className="p-xs bg-white border rounded inline-block shadow-sm">
                  <img
                    alt="TOTP QR Code"
                    className="block"
                    src={qrCodeUrl}
                    style={{ width: '200px', height: '200px' }}
                  />
                </div>
              ) : (
                <div
                  style={{ width: '200px', height: '200px' }}
                  className="flex-center bg-surface border rounded text-xs text-secondary"
                >
                  正在生成二维码...
                </div>
              )}
              <p className="text-xs text-secondary mt-xs">
                支持 Google Authenticator、微软 Authenticator、微信/腾讯身份验证器、1Password 或 iOS 自带密码
              </p>

              {/* Manual Entry Key */}
              <div className="w-full text-left p-xs bg-surface border rounded mt-xs">
                <label className="form-label text-xs text-secondary mb-0">手动输入密钥（Base32）：</label>
                <div className="flex-between align-center">
                  <span className="font-mono text-xs font-bold tracking-wider select-all">{secret}</span>
                  <button
                    type="button"
                    className="btn btn-secondary btn-xs shrink-0 ml-xs"
                    onClick={handleCopySecret}
                  >
                    {copiedSecret ? '✓ 已复制' : '复制密钥'}
                  </button>
                </div>
              </div>
            </div>

            {/* Dev Clock Assist Block */}
            {liveCode && (
              <div className="p-xs bg-surface border rounded flex-between align-center text-xs">
                <div>
                  <span className="text-secondary">💡 本机时钟当前动态码: </span>
                  <strong className="font-mono text-primary text-sm tracking-wider">{liveCode}</strong>
                  <span className="text-secondary text-xs ml-xs">({secondsRemaining}s)</span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-xs shrink-0"
                  onClick={handleAutoFillLiveCode}
                >
                  一键填入
                </button>
              </div>
            )}

            {/* Step 2: Confirmation Code */}
            <form onSubmit={handleConfirm} className="form-stack mt-sm">
              <div className="form-group">
                <label htmlFor="totp-confirm-code" className="form-label text-sm font-semibold">
                  输入验证器生成的 6 位动态验证码确认：
                </label>
                <input
                  id="totp-confirm-code"
                  type="text"
                  className="input-text text-center font-mono text-xl tracking-widest font-bold"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="000000"
                  maxLength={6}
                  required
                  autoFocus
                />
              </div>

              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => navigate('/')}
                  disabled={loading}
                >
                  暂不绑定
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={loading || code.trim().length !== 6}
                >
                  {loading ? '正在验证...' : '确认并启用'}
                </button>
              </div>
            </form>
          </div>
        ) : (
          <div className="text-center py-md">
            <span className="text-secondary">{loading ? '正在生成密钥与二维码...' : '暂无密钥'}</span>
          </div>
        )}
      </div>
    </div>
  )
}
