import React from 'react'

interface StatusBadgeProps {
  status: string
  label?: string
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, label }) => {
  const normalized = status.toLowerCase()
  let className = 'badge badge-neutral'

  if (normalized === 'active' || normalized === 'verified' || normalized === 'accepted') {
    className = 'badge badge-success'
  } else if (normalized === 'suspended' || normalized === 'pending') {
    className = 'badge badge-warning'
  } else if (normalized === 'expired' || normalized === 'revoked' || normalized === 'removed') {
    className = 'badge badge-danger'
  }

  return <span className={className}>{label || status}</span>
}
