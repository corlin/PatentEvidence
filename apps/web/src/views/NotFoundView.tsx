import React from 'react'
import { Link } from '../router/Router'

export const NotFoundView: React.FC = () => {
  return (
    <div className="auth-card-container text-center">
      <div className="card max-w-md p-xl">
        <h1 className="text-4xl font-bold text-secondary mb-sm">404</h1>
        <h2 className="text-lg font-semibold mb-xs">页面不存在或无权访问</h2>
        <p className="text-sm text-secondary mb-lg">
          您请求的资源不存在，或已被跨租户安全隔离策略安全拒绝。
        </p>
        <Link to="/" className="btn btn-primary">
          返回工作台首页
        </Link>
      </div>
    </div>
  )
}
