import React, { useEffect, useState } from 'react'
import { Icon } from './Icon'
import { useSession } from '../context/SessionContext'
import { Link, useNavigate, useRouter } from '../router/Router'

interface HeaderProps {
  currentOrgName?: string
}

export const Header: React.FC<HeaderProps> = ({ currentOrgName }) => {
  const { session, logout, activeOrgId, activeMembership, isPlatformAdmin, canManageOrganization } =
    useSession()
  const { pathname } = useRouter()
  const navigate = useNavigate()

  // Sprint 3：主题切换（手动选择优先，未选择时跟随系统）
  const [theme, setTheme] = useState<'dark' | 'light' | 'system'>(() => {
    try {
      const t = localStorage.getItem('pe_theme')
      return t === 'dark' || t === 'light' ? t : 'system'
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    if (theme === 'system') {
      delete document.documentElement.dataset.theme
    } else {
      document.documentElement.dataset.theme = theme
    }
  }, [theme])
  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('pe_theme', next)
    } catch {}
  }

  const orgId = activeOrgId
  const casesHref = orgId ? `/organizations/${orgId}/cases` : '/select-organization'
  const canManageCurrentOrg = orgId ? canManageOrganization(orgId) : false
  const showMembersNav = Boolean(orgId && (canManageCurrentOrg || isPlatformAdmin))
  const displayOrgName = currentOrgName || activeMembership?.organization_name

  return (
    <header className="app-header">
      <a href="#main-content" className="skip-link">
        跳到主要内容
      </a>
      <div className="header-inner">
        <div className="header-brand">
          <Link to="/select-organization" className="brand-logo">
            <span className="brand-icon"><Icon name="scales" size={14} /></span>
            <strong>PatentEvidence</strong>
          </Link>
          <span className="badge badge-neutral text-xs">P0 Baseline</span>
        </div>

        {session && (
          <div className="header-nav">
            <nav className="flex-row gap-xs mr-md">
              <Link
                to={casesHref}
                className={`btn btn-sm ${
                  pathname.includes('/cases') ? 'btn-primary' : 'btn-secondary'
                }`}
              >
                <Icon name="folder" size={14} /> 案件中心
              </Link>
              {showMembersNav && orgId && (
                <Link
                  to={`/organizations/${orgId}/members`}
                  className={`btn btn-sm ${
                    pathname.includes('/members') ? 'btn-primary' : 'btn-secondary'
                  }`}
                >
                  <Icon name="users" size={14} /> 机构成员
                </Link>
              )}
              {isPlatformAdmin && (
                <Link
                  to="/platform/organizations"
                  className={`btn btn-sm ${
                    pathname.includes('/platform') ? 'btn-primary' : 'btn-secondary'
                  }`}
                >
                  <Icon name="buildings" size={14} /> 平台管理
                </Link>
              )}
            </nav>

            {displayOrgName && (
              <div className="org-indicator">
                <span className="text-secondary text-xs">当前机构:</span>
                <span className="org-name font-medium">{displayOrgName}</span>
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
                onClick={toggleTheme}
                aria-label={theme === 'dark' ? '切换到亮色模式' : '切换到暗色模式'}
                title={theme === 'dark' ? '切换到亮色模式' : '切换到暗色模式'}
              >
                <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />
              </button>
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
