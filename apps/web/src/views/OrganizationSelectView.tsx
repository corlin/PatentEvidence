import React from 'react'
import { Icon } from '../components/Icon'
import { useSession } from '../context/SessionContext'
import { Header } from '../components/Header'
import { Link, useNavigate } from '../router/Router'

export const OrganizationSelectView: React.FC = () => {
  const { memberships, meLoading, isPlatformAdmin, setActiveOrgId } = useSession()
  const navigate = useNavigate()

  const enterOrganization = (orgId: string) => {
    setActiveOrgId(orgId)
    navigate(`/organizations/${orgId}/cases`)
  }

  return (
    <div className="layout-container">
      <Header />

      <main id="main-content" className="main-content max-w-xl mx-auto py-xl">
        <div className="card">
          <div className="card-header text-center mb-md">
            <h1 className="card-title text-xl font-bold">选择工作空间</h1>
            <p className="card-subtitle text-sm text-secondary">
              请选择您要进入的机构工作台或平台管理视图
            </p>
          </div>

          <div className="flex-stack gap-sm">
            {meLoading ? (
              <div className="p-md text-center text-secondary text-sm">
                正在加载您的机构列表...
              </div>
            ) : memberships.length > 0 ? (
              memberships.map((membership) => (
                <button
                  key={membership.organization_id}
                  type="button"
                  onClick={() => enterOrganization(membership.organization_id)}
                  className="org-select-card p-md border rounded hover-border-primary transition text-left cursor-pointer"
                >
                  <div className="flex-between">
                    <div>
                      <strong className="text-base text-primary">
                        <Icon name="scales" size={14} /> {membership.organization_name}
                      </strong>
                      <p className="text-xs text-secondary mt-xs">
                        角色：
                        {membership.role === 'organization_admin'
                          ? '机构管理员'
                          : membership.role === 'reviewer'
                          ? '复核专家'
                          : '专利代理师'}
                        {membership.status === 'suspended' && '（已暂停）'}
                      </p>
                    </div>
                    <span className="badge badge-success text-xs">进入工作台 &rarr;</span>
                  </div>
                </button>
              ))
            ) : (
              <div className="p-md text-center text-secondary text-sm">
                您当前尚未加入任何机构。如需开通机构工作空间，请联系机构管理员发送邀请，或联系平台管理员。
              </div>
            )}

            {isPlatformAdmin && (
              <Link
                to="/platform/organizations"
                className="org-select-card p-md border rounded hover-border-primary transition"
              >
                <div className="flex-between">
                  <div>
                    <strong className="text-base text-primary"><Icon name="buildings" size={14} /> 平台全局管理中心</strong>
                    <p className="text-xs text-secondary mt-xs">
                      开通机构、配额策略管理与全局生命周期维护（限平台管理员）
                    </p>
                  </div>
                  <span className="badge badge-neutral text-xs">Platform</span>
                </div>
              </Link>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
