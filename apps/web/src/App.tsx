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

  const repMatch = matchPath('/organizations/:orgId/cases/:caseId/reports', pathname)
  if (repMatch.matched) {
    return (
      <ReportsWorkbenchView
        orgId={repMatch.params.orgId}
        caseId={repMatch.params.caseId}
      />
    )
  }

  const dlvMatch = matchPath('/organizations/:orgId/cases/:caseId/delivery', pathname)
  if (dlvMatch.matched) {
    return (
      <DeliveryWorkbenchView
        orgId={dlvMatch.params.orgId}
        caseId={dlvMatch.params.caseId}
      />
    )
  }

  const revMatch = matchPath('/organizations/:orgId/cases/:caseId/review', pathname)
  if (revMatch.matched) {
    return (
      <ReviewWorkbenchView
        orgId={revMatch.params.orgId}
        caseId={revMatch.params.caseId}
      />
    )
  }

  const compMatch =
    matchPath('/organizations/:orgId/cases/:caseId/comparisons', pathname).matched
      ? matchPath('/organizations/:orgId/cases/:caseId/comparisons', pathname)
      : matchPath('/organizations/:orgId/cases/:caseId/comparison', pathname)
  if (compMatch.matched) {
    return (
      <ComparisonWorkbenchView
        orgId={compMatch.params.orgId}
        caseId={compMatch.params.caseId}
      />
    )
  }

  const searchMatch = matchPath('/organizations/:orgId/cases/:caseId/search', pathname)
  if (searchMatch.matched) {
    return (
      <SearchWorkbenchView
        orgId={searchMatch.params.orgId}
        caseId={searchMatch.params.caseId}
      />
    )
  }

  const featuresMatch = matchPath('/organizations/:orgId/cases/:caseId/features', pathname)
  if (featuresMatch.matched) {
    return (
      <FeaturesWorkbenchView
        orgId={featuresMatch.params.orgId}
        caseId={featuresMatch.params.caseId}
      />
    )
  }

  const caseDetailMatch = matchPath('/organizations/:orgId/cases/:caseId', pathname)
  if (caseDetailMatch.matched) {
    return (
      <CaseDetailView
        orgId={caseDetailMatch.params.orgId}
        caseId={caseDetailMatch.params.caseId}
      />
    )
  }

  const casesListMatch = matchPath('/organizations/:orgId/cases', pathname)
  if (casesListMatch.matched) {
    return <CasesListView orgId={casesListMatch.params.orgId} />
  }

  const orgMembersMatch = matchPath('/organizations/:id/members', pathname)
  if (orgMembersMatch.matched) {
    return <OrganizationMembersView orgId={orgMembersMatch.params.id} />
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
