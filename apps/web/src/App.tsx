import React, { lazy, Suspense, useEffect } from 'react'
import { SessionProvider, useSession } from './context/SessionContext'
import { matchPath, Router, useNavigate, useRouter } from './router/Router'
import { MfaStepUpModal } from './components/MfaStepUpModal'
import { LoginView } from './views/LoginView'
import { MfaChallengeView } from './views/MfaChallengeView'
import { MfaEnrollView } from './views/MfaEnrollView'
import { PasswordResetView } from './views/PasswordResetView'
import { ForbiddenView } from './views/ForbiddenView'
import { NotFoundView } from './views/NotFoundView'
import { Link } from './router/Router'

// Sprint 3：路由级代码分割（工作台视图按需加载）
const PlatformOrganizationsView = lazy(() =>
  import('./views/PlatformOrganizationsView').then((m) => ({ default: m.PlatformOrganizationsView }))
)
const OrganizationMembersView = lazy(() =>
  import('./views/OrganizationMembersView').then((m) => ({ default: m.OrganizationMembersView }))
)
const OrganizationSelectView = lazy(() =>
  import('./views/OrganizationSelectView').then((m) => ({ default: m.OrganizationSelectView }))
)
const InvitationAcceptView = lazy(() =>
  import('./views/InvitationAcceptView').then((m) => ({ default: m.InvitationAcceptView }))
)
const CasesListView = lazy(() =>
  import('./views/CasesListView').then((m) => ({ default: m.CasesListView }))
)
const CaseDetailView = lazy(() =>
  import('./views/CaseDetailView').then((m) => ({ default: m.CaseDetailView }))
)
const FeaturesWorkbenchView = lazy(() =>
  import('./views/FeaturesWorkbenchView').then((m) => ({ default: m.FeaturesWorkbenchView }))
)
const SearchWorkbenchView = lazy(() =>
  import('./views/SearchWorkbenchView').then((m) => ({ default: m.SearchWorkbenchView }))
)
const ComparisonWorkbenchView = lazy(() =>
  import('./views/ComparisonWorkbenchView').then((m) => ({ default: m.ComparisonWorkbenchView }))
)
const ReportsWorkbenchView = lazy(() =>
  import('./views/ReportsWorkbenchView').then((m) => ({ default: m.ReportsWorkbenchView }))
)
const ReviewWorkbenchView = lazy(() =>
  import('./views/ReviewWorkbenchView').then((m) => ({ default: m.ReviewWorkbenchView }))
)
const DeliveryWorkbenchView = lazy(() =>
  import('./views/DeliveryWorkbenchView').then((m) => ({ default: m.DeliveryWorkbenchView }))
)
const AssessmentWorkbenchView = lazy(() =>
  import('./views/AssessmentWorkbenchView').then((m) => ({ default: m.AssessmentWorkbenchView }))
)

const RouteFallback: React.FC = () => (
  <div className="layout-container">
    <div className="main-content p-xl text-center text-secondary text-sm">
      正在加载工作台...
    </div>
  </div>
)

function matchAny(
  patterns: string[],
  pathname: string
): { matched: boolean; params: Record<string, string> } {
  for (const p of patterns) {
    const res = matchPath(p, pathname)
    if (res.matched) return res
  }
  return { matched: false, params: {} }
}

/** 已登录但未选择（或无任何）机构时，工作台类页面应引导到工作空间选择。 */
const RequireOrg: React.FC = () => {
  return (
    <div className="layout-container">
      <div className="main-content p-xl">
        <div className="card p-xl text-center max-w-lg mx-auto">
          <h1 className="text-lg font-bold mb-sm">请先选择工作空间</h1>
          <p className="text-sm text-secondary mb-md">
            该页面需要指定机构上下文。请选择一个您所属的机构后再进入。
          </p>
          <Link to="/select-organization" className="btn btn-primary btn-sm">
            前往选择工作空间 →
          </Link>
        </div>
      </div>
    </div>
  )
}

const AppRoutes: React.FC = () => {
  const { pathname } = useRouter()
  const { session, loading, activeOrgId, meInfo, meLoading, isPlatformAdmin, canManageOrganization } =
    useSession()
  const navigate = useNavigate()

  useEffect(() => {
    if (loading) return

    // Root path smart redirect（不再回退到硬编码机构）
    if (pathname === '/') {
      if (!session) {
        navigate('/login')
      } else if (activeOrgId) {
        navigate(`/organizations/${activeOrgId}/cases`)
      } else {
        navigate('/select-organization')
      }
    }
  }, [pathname, session, loading, activeOrgId, navigate])

  if (loading) {
    return (
      <div className="auth-card-container">
        <div className="text-secondary text-sm">正在加载 PatentEvidence 会话...</div>
      </div>
    )
  }

  // 1. Public Auth / Invitation routes
  if (pathname === '/login') {
    return <LoginView />
  }
  if (pathname === '/mfa' || pathname === '/mfa/challenge') {
    return <MfaChallengeView />
  }
  if (pathname === '/mfa/enroll') {
    return <MfaEnrollView />
  }
  if (pathname === '/password-reset') {
    return <PasswordResetView />
  }
  if (pathname === '/invitations/accept') {
    return <InvitationAcceptView />
  }

  // 2. Protected routes (require session)
  if (!session) {
    return <LoginView />
  }

  if (pathname === '/select-organization') {
    return <OrganizationSelectView />
  }

  // 2.1 Platform routes：仅平台管理员可访问
  if (pathname === '/platform/organizations' || pathname === '/platform') {
    if (meLoading) {
      return (
        <div className="layout-container">
          <div className="main-content p-xl text-center text-secondary text-sm">
            正在校验平台权限...
          </div>
        </div>
      )
    }
    if (!isPlatformAdmin) {
      return (
        <ForbiddenView message="平台管理仅限平台管理员访问。若您需要开通机构或管理配额，请联系平台管理员。" />
      )
    }
    return <PlatformOrganizationsView />
  }

  // 2.2 机构成员管理：仅该机构管理员或平台管理员可访问
  const membersRoute = matchPath('/organizations/:id/members', pathname)
  if (membersRoute.matched) {
    if (meLoading) {
      return (
        <div className="layout-container">
          <div className="main-content p-xl text-center text-secondary text-sm">
            正在校验机构权限...
          </div>
        </div>
      )
    }
    const orgId = membersRoute.params.id
    const isOrgAdmin = canManageOrganization(orgId)
    if (!isOrgAdmin && !isPlatformAdmin) {
      return (
        <ForbiddenView message="机构成员管理仅限该机构管理员或平台管理员访问。" />
      )
    }
    return <OrganizationMembersView orgId={orgId} />
  }

  const WORKBENCH_ROUTES = [
    {
      patterns: ['/organizations/:orgId/cases/:caseId/reports', '/cases/:caseId/reports'],
      render: (p: Record<string, string>) => (
        <ReportsWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/delivery', '/cases/:caseId/delivery'],
      render: (p: Record<string, string>) => (
        <DeliveryWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/review', '/cases/:caseId/review'],
      render: (p: Record<string, string>) => (
        <ReviewWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: [
        '/organizations/:orgId/cases/:caseId/comparisons',
        '/organizations/:orgId/cases/:caseId/comparison',
        '/cases/:caseId/comparisons',
        '/cases/:caseId/comparison',
      ],
      render: (p: Record<string, string>) => (
        <ComparisonWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: [
        '/organizations/:orgId/cases/:caseId/assessments',
        '/organizations/:orgId/cases/:caseId/assessment',
        '/cases/:caseId/assessments',
        '/cases/:caseId/assessment',
      ],
      render: (p: Record<string, string>) => (
        <AssessmentWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/search', '/cases/:caseId/search'],
      render: (p: Record<string, string>) => (
        <SearchWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/features', '/cases/:caseId/features'],
      render: (p: Record<string, string>) => (
        <FeaturesWorkbenchView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId', '/cases/:caseId'],
      render: (p: Record<string, string>) => (
        <CaseDetailView orgId={p.orgId || activeOrgId!} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases', '/cases'],
      render: (p: Record<string, string>) => (
        <CasesListView orgId={p.orgId || activeOrgId!} />
      ),
    },
  ]

  for (const route of WORKBENCH_ROUTES) {
    const match = matchAny(route.patterns, pathname)
    if (match.matched) {
      // 短路由（/cases/:caseId）或组织上下文缺失时，未选择机构则引导选择
      if (!match.params.orgId && !activeOrgId) {
        return <RequireOrg />
      }
      return route.render(match.params)
    }
  }

  // 3. Fallback
  return <NotFoundView />
}

export default function App() {
  return (
    <Router>
      <SessionProvider>
        <Suspense fallback={<RouteFallback />}>
          <AppRoutes />
        </Suspense>
        <MfaStepUpModal />
      </SessionProvider>
    </Router>
  )
}
