import React from 'react'
import { useSession } from '../context/SessionContext'
import { Header } from '../components/Header'
import { Link, useNavigate } from '../router/Router'

export const OrganizationSelectView: React.FC = () => {
  const { session, setActiveOrgId } = useSession()
  const navigate = useNavigate()

  return (
    <div className="layout-container">
      <Header />

      <main className="main-content max-w-xl mx-auto py-xl">
        <div className="card">
          <div className="card-header text-center mb-md">
            <h1 className="card-title text-xl font-bold">选择工作空间</h1>
            <p className="card-subtitle text-sm text-secondary">
              请选择您要进入的机构工作台或平台管理视图
            </p>
          </div>

          <div className="flex-stack gap-sm">
            <button
              type="button"
              onClick={() => {
                setActiveOrgId('90000000-0000-4000-8000-000000000001')
                navigate('/organizations/90000000-0000-4000-8000-000000000001/cases')
              }}
              className="org-select-card p-md border rounded hover-border-primary transition text-left cursor-pointer"
            >
              <div className="flex-between">
                <div>
                  <strong className="text-base text-primary">⚖️ 北京前沿知识产权代理事务所</strong>
                  <p className="text-xs text-secondary mt-xs">
                    标准知识产权代理机构工作空间（案件中心、技术特征建模、Claim Chart 与报告）
                  </p>
                </div>
                <span className="badge badge-success text-xs">进入工作台 &rarr;</span>
              </div>
            </button>

            <Link
              to="/platform/organizations"
              className="org-select-card p-md border rounded hover-border-primary transition"
            >
              <div className="flex-between">
                <div>
                  <strong className="text-base text-primary">🏢 平台全局管理中心</strong>
                  <p className="text-xs text-secondary mt-xs">
                    开通机构、配额策略管理与全局生命周期维护（限超级管理员）
                  </p>
                </div>
                <span className="badge badge-neutral text-xs">Platform</span>
              </div>
            </Link>

            <div className="text-center py-sm text-xs text-secondary">
              或输入特定机构 ID 直接访问：
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                const form = e.target as HTMLFormElement
                const input = form.elements.namedItem('orgIdInput') as HTMLInputElement
                if (input && input.value.trim()) {
                  setActiveOrgId(input.value.trim())
                  navigate(`/organizations/${input.value.trim()}/members`)
                }
              }}
              className="flex-row gap-xs"
            >
              <input
                name="orgIdInput"
                type="text"
                className="input-text text-sm"
                placeholder="机构 UUID (如 00000000-0000-...)"
                required
              />
              <button type="submit" className="btn btn-secondary text-sm">
                进入
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  )
}
