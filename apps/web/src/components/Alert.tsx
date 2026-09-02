import React from 'react'

interface AlertProps {
  type?: 'error' | 'warning' | 'info' | 'success'
  message?: string
  children?: React.ReactNode
  onClose?: () => void
}

export const Alert: React.FC<AlertProps> = ({
  type = 'info',
  message,
  children,
  onClose,
}) => {
  return (
    <div className={`alert alert-${type}`} role="alert">
      <div className="alert-content">{children || message}</div>
      {onClose && (
        <button
          type="button"
          className="alert-close-btn"
          aria-label="Close alert"
          onClick={onClose}
        >
          ×
        </button>
      )}
    </div>
  )
}
