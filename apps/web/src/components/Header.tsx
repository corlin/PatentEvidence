import React from 'react'
import { useSession } from '../context/SessionContext'
import { Link, useNavigate } from '../router/Router'

interface HeaderProps {
  currentOrgName?: string
}

export const Header: React.FC<HeaderProps> = ({ currentOrgName }) => {
  const { session, logout, activeOrgId } = useSession()
  const navigate = useNavigate()

  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="header-brand">
          <Link to="/" className="brand-logo">
            <span className="brand-icon">⚖️</span>
            <strong>PatentEvidence</strong>
          </Link>
          <span className="badge badge-neutral text-xs">P0 Baseline</span>
        </div>

        {session && (
          <div className="header-nav">
            {currentOrgName && (
              <div className="org-indicator">
                <span className="text-secondary text-xs">当前机构:</span>
                <span className="org-name font-medium">{currentOrgName}</span>
                <button
                  type="button"
                  className="btn-link text-xs"
                  onClick={() => navigate('/select-organization')}
                >
                  切换
                </button>
              </div>
            )}

            <div className="user-profile">
              <span className="user-email text-sm text-secondary" title={session.email}>
                {session.email}
              </span>
              {session.mfa_recent && (
                <span className="badge badge-success text-xs" title="近期已完成两步验证">
                  MFA 已就绪
                </span>
              )}
            </div>

            <div className="header-actions">
              <Link to="/mfa/enroll" className="btn btn-secondary btn-sm">
                MFA 设置
              </Link>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={logout}
                aria-label="退出登录"
              >
                退出登录
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  )
}
