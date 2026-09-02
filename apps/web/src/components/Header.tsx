import React from 'react'
import { useSession } from '../context/SessionContext'
import { Link, useNavigate, useRouter } from '../router/Router'

interface HeaderProps {
  currentOrgName?: string
}

export const Header: React.FC<HeaderProps> = ({
  currentOrgName = '北京易光知识产权代理有限公司',
}) => {
  const { session, logout, activeOrgId } = useSession()
  const { pathname } = useRouter()
  const navigate = useNavigate()

  const orgId = activeOrgId || '90000000-0000-4000-8000-000000000001'
  const isPlatformUser = session?.email === 'superadmin@patent.com'

  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="header-brand">
          <Link to={`/organizations/${orgId}/cases`} className="brand-logo">
            <span className="brand-icon">⚖️</span>
            <strong>PatentEvidence</strong>
          </Link>
          <span className="badge badge-neutral text-xs">P0 Baseline</span>
        </div>

        {session && (
          <div className="header-nav">
            <nav className="flex-row gap-xs mr-md">
              <Link
                to={`/organizations/${orgId}/cases`}
                className={`btn btn-sm ${
                  pathname.includes('/cases') ? 'btn-primary' : 'btn-secondary'
                }`}
              >
                📁 案件中心
              </Link>
              <Link
                to={`/organizations/${orgId}/members`}
                className={`btn btn-sm ${
                  pathname.includes('/members') ? 'btn-primary' : 'btn-secondary'
                }`}
              >
                👥 机构成员
              </Link>
              <Link
                to="/platform/organizations"
                className={`btn btn-sm ${
                  pathname.includes('/platform') ? 'btn-primary' : 'btn-secondary'
                }`}
              >
                🏢 平台管理
              </Link>
            </nav>

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
