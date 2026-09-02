import React, { useEffect } from 'react'
import { SessionProvider, useSession } from './context/SessionContext'
import { matchPath, Router, useNavigate, useRouter } from './router/Router'
import { MfaStepUpModal } from './components/MfaStepUpModal'
import { LoginView } from './views/LoginView'
import { MfaChallengeView } from './views/MfaChallengeView'
import { MfaEnrollView } from './views/MfaEnrollView'
import { PasswordResetView } from './views/PasswordResetView'
import { PlatformOrganizationsView } from './views/PlatformOrganizationsView'
import { OrganizationMembersView } from './views/OrganizationMembersView'
import { OrganizationSelectView } from './views/OrganizationSelectView'
import { InvitationAcceptView } from './views/InvitationAcceptView'
import { CasesListView } from './views/CasesListView'
import { CaseDetailView } from './views/CaseDetailView'
import { FeaturesWorkbenchView } from './views/FeaturesWorkbenchView'
import { SearchWorkbenchView } from './views/SearchWorkbenchView'
import { ComparisonWorkbenchView } from './views/ComparisonWorkbenchView'
import { ReportsWorkbenchView } from './views/ReportsWorkbenchView'
import { ReviewWorkbenchView } from './views/ReviewWorkbenchView'
import { DeliveryWorkbenchView } from './views/DeliveryWorkbenchView'
import { NotFoundView } from './views/NotFoundView'

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

const AppRoutes: React.FC = () => {
  const { pathname } = useRouter()
  const { session, loading, activeOrgId } = useSession()
  const navigate = useNavigate()

  useEffect(() => {
    if (loading) return

    // Root path smart redirect
    if (pathname === '/') {
      if (!session) {
        navigate('/login')
      } else {
        const orgId = activeOrgId || '90000000-0000-4000-8000-000000000001'
        navigate(`/organizations/${orgId}/cases`)
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
  if (pathname === '/platform/organizations' || pathname === '/platform') {
    return <PlatformOrganizationsView />
  }

  const defaultOrgId = activeOrgId || '90000000-0000-4000-8000-000000000001'

  const WORKBENCH_ROUTES = [
    {
      patterns: ['/organizations/:orgId/cases/:caseId/reports', '/cases/:caseId/reports'],
      render: (p: Record<string, string>) => (
        <ReportsWorkbenchView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/delivery', '/cases/:caseId/delivery'],
      render: (p: Record<string, string>) => (
        <DeliveryWorkbenchView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/review', '/cases/:caseId/review'],
      render: (p: Record<string, string>) => (
        <ReviewWorkbenchView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
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
        <ComparisonWorkbenchView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/search', '/cases/:caseId/search'],
      render: (p: Record<string, string>) => (
        <SearchWorkbenchView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId/features', '/cases/:caseId/features'],
      render: (p: Record<string, string>) => (
        <FeaturesWorkbenchView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases/:caseId', '/cases/:caseId'],
      render: (p: Record<string, string>) => (
        <CaseDetailView orgId={p.orgId || defaultOrgId} caseId={p.caseId} />
      ),
    },
    {
      patterns: ['/organizations/:orgId/cases', '/cases'],
      render: (p: Record<string, string>) => (
        <CasesListView orgId={p.orgId || defaultOrgId} />
      ),
    },
    {
      patterns: ['/organizations/:id/members'],
      render: (p: Record<string, string>) => <OrganizationMembersView orgId={p.id} />,
    },
  ]

  for (const route of WORKBENCH_ROUTES) {
    const match = matchAny(route.patterns, pathname)
    if (match.matched) {
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
        <AppRoutes />
        <MfaStepUpModal />
      </SessionProvider>
    </Router>
  )
}
