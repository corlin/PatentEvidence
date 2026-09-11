import React from 'react'
import { Icon } from '../components/Icon'
import { Header } from '../components/Header'
import { Link } from '../router/Router'

interface ForbiddenViewProps {
  message?: string
}

/** 403 无权限视图：路由守卫拒绝后展示，替代"加载失败"的误导性报错。 */
export const ForbiddenView: React.FC<ForbiddenViewProps> = ({
  message = '您没有访问该页面的权限。如需开通，请联系所在机构管理员或平台管理员。',
}) => {
  return (
    <div className="layout-container">
      <Header />
      <main id="main-content" className="main-content p-xl">
        <div className="card p-xl text-center max-w-lg mx-auto">
          <div className="text-3xl mb-sm"><Icon name="lock" size={14} /></div>
          <h1 className="text-lg font-bold mb-sm">无访问权限</h1>
          <p className="text-sm text-secondary mb-md">{message}</p>
          <Link to="/select-organization" className="btn btn-primary btn-sm">
            ← 返回工作空间选择
          </Link>
        </div>
      </main>
    </div>
  )
}
