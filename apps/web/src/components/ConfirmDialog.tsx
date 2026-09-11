import React from 'react'
import { Modal } from './Modal'

interface ConfirmDialogProps {
  isOpen: boolean
  title: string
  /** 说明正文：必须清晰描述操作的后果（尤其"不可变/不可撤销"类）。 */
  children: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** 危险操作（删除、锁定、交付等）使用强调样式。 */
  danger?: boolean
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * 统一确认对话框：接入所有不可逆/高风险操作。
 * 与产品"不可变证据链"承诺对齐：任何将产生不可变记录的动作，
 * 都必须在执行前显式说明后果并取得确认。
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  children,
  confirmLabel = '确认执行',
  cancelLabel = '取消',
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}) => {
  return (
    <Modal isOpen={isOpen} title={title} onClose={onCancel}>
      <div className="form-stack">
        <div
          className="p-md border rounded text-sm"
          style={
            danger
              ? { background: 'var(--color-danger-bg)', borderColor: 'var(--color-danger-border)' }
              : { background: 'var(--color-bg)', borderColor: 'var(--color-border)' }
          }
        >
          {children}
        </div>
        <div className="modal-actions mt-md">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            disabled={loading}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn btn-sm ${danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? '执行中...' : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
