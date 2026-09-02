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
      } else if (activeOrgId) {
        navigate(`/organizations/${activeOrgId}/members`)
      } else {
        navigate('/platform/organizations')
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
