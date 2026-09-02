import React, { useState } from 'react'
import { apiClient } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from './Alert'
import { Modal } from './Modal'

export const MfaStepUpModal: React.FC = () => {
  const { isMfaModalOpen, closeMfaModal, handleMfaSuccess } = useSession()
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
      setCode('')
      handleMfaSuccess()
    } catch (err: any) {
      setError(err.detail || err.message || 'MFA verification failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal isOpen={isMfaModalOpen} title="需要身份安全验证 (MFA)" onClose={closeMfaModal}>
      <form onSubmit={handleSubmit} className="form-stack">
        <p className="text-secondary text-sm">
          {useRecovery
            ? '请输入一次性恢复码以验证您的管理员权限：'
            : '此操作需要近期两步验证授权。请输入身份验证器中的 6 位动态验证码：'}
        </p>

        {error && <Alert type="error" message={error} />}

        <div className="form-group">
          <label htmlFor="mfa-step-up-code" className="form-label">
            {useRecovery ? '恢复码' : '6 位动态验证码'}
          </label>
          <input
            id="mfa-step-up-code"
            type="text"
            className="input-text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={useRecovery ? '例如: abc123def456' : '000000'}
            maxLength={useRecovery ? 32 : 8}
            autoFocus
            required
          />
        </div>

        <div className="form-actions">
          <button
            type="button"
            className="btn btn-secondary text-sm"
            onClick={() => {
              setUseRecovery(!useRecovery)
              setError(null)
              setCode('')
            }}
          >
            {useRecovery ? '使用动态验证码' : '使用恢复码'}
          </button>
          <div className="flex-row gap-sm">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeMfaModal}
              disabled={loading}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading || !code.trim()}>
              {loading ? '验证中...' : '确认授权'}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  )
}
