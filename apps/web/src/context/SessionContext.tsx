import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import type { MeInfo, MyMembership, SessionInfo } from '../types/api'

/** 同一会话内允许连续 MFA Step-Up 成功重放的最大次数（防 403 死循环的最后一道保险）。 */
const MAX_MFA_STEP_UPS = 3

interface SessionContextValue {
  session: SessionInfo | null
  loading: boolean
  error: string | null
  activeOrgId: string | null
  setActiveOrgId: (id: string | null) => void
  refreshSession: () => Promise<SessionInfo | null>
  logout: () => Promise<void>
  isMfaModalOpen: boolean
  requestMfaStepUp: (onSuccess: () => void) => void
  closeMfaModal: () => void
  handleMfaSuccess: () => void
  // 当前身份信息（来自 GET /api/v1/auth/me），用于路由守卫与工作空间解析
  meInfo: MeInfo | null
  meLoading: boolean
  memberships: MyMembership[]
  isPlatformAdmin: boolean
  activeMembership: MyMembership | null
  canManageOrganization: (orgId: string) => boolean
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined)

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [meInfo, setMeInfo] = useState<MeInfo | null>(null)
  const [meLoading, setMeLoading] = useState<boolean>(false)
  const [activeOrgId, setActiveOrgIdState] = useState<string | null>(() => {
    try {
      return localStorage.getItem('pe_active_org_id')
    } catch {
      return null
    }
  })
  // 连续 MFA Step-Up 成功次数（防死循环保险）
  const mfaStepUpCountRef = useRef(0)

  const setActiveOrgId = useCallback((id: string | null) => {
    setActiveOrgIdState(id)
    try {
      if (id) localStorage.setItem('pe_active_org_id', id)
      else localStorage.removeItem('pe_active_org_id')
    } catch {}
  }, [])

  const [isMfaModalOpen, setIsMfaModalOpen] = useState(false)
  const [mfaSuccessCallback, setMfaSuccessCallback] = useState<(() => void) | null>(null)

  const refreshSession = useCallback(async (): Promise<SessionInfo | null> => {
    try {
      const data = await apiClient.getSession()
      setSession(data)
      setError(null)
      // 会话有效时并行获取身份机构信息（只读；失败静默，不阻断会话）
      setMeLoading(true)
      apiClient
        .getMe()
        .then((me) => {
          setMeInfo(me)
          if (me.memberships.length === 0) {
            setActiveOrgId(null)
          }
        })
        .catch(() => {
          setMeInfo(null)
        })
        .finally(() => setMeLoading(false))
      return data
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setSession(null)
        setMeInfo(null)
      } else if (err instanceof Error) {
        setError(err.message)
      }
      return null
    } finally {
      setLoading(false)
    }
  }, [setActiveOrgId])

  useEffect(() => {
    refreshSession()
  }, [refreshSession])

  // 已切换/持久化的 activeOrgId 必须属于当前身份的成员关系，否则视为未选择
  useEffect(() => {
    if (!meInfo || meInfo.memberships.length === 0) {
      if (activeOrgId) setActiveOrgId(null)
      return
    }
    if (activeOrgId && !meInfo.memberships.some((m) => m.organization_id === activeOrgId)) {
      setActiveOrgId(null)
    }
  }, [meInfo, activeOrgId, setActiveOrgId])

  const memberships = useMemo<MyMembership[]>(() => meInfo?.memberships || [], [meInfo])
  const isPlatformAdmin = Boolean(meInfo?.is_platform_admin)
  const activeMembership = useMemo<MyMembership | null>(
    () => memberships.find((m) => m.organization_id === activeOrgId) || null,
    [memberships, activeOrgId]
  )
  const canManageOrganization = useCallback(
    (orgId: string): boolean => {
      const membership = memberships.find((m) => m.organization_id === orgId)
      return Boolean(membership && membership.role === 'organization_admin')
    },
    [memberships]
  )

  const logout = useCallback(async () => {
    try {
      await apiClient.logout()
    } catch {
      // ignore logout failures
    } finally {
      setSession(null)
      setMeInfo(null)
      setActiveOrgId(null)
      mfaStepUpCountRef.current = 0
      window.history.pushState({}, '', '/login')
      window.dispatchEvent(new PopStateEvent('popstate'))
    }
  }, [setActiveOrgId])

  const requestMfaStepUp = useCallback((onSuccess: () => void) => {
    if (mfaStepUpCountRef.current >= MAX_MFA_STEP_UPS) {
      setError('多次安全验证后仍无法完成该操作，请检查您的权限或稍后重试。')
      return
    }
    setMfaSuccessCallback(() => onSuccess)
    setIsMfaModalOpen(true)
  }, [])

  const closeMfaModal = useCallback(() => {
    setIsMfaModalOpen(false)
    setMfaSuccessCallback(null)
  }, [])

  const handleMfaSuccess = useCallback(() => {
    setIsMfaModalOpen(false)
    mfaStepUpCountRef.current += 1
    if (mfaSuccessCallback) {
      const cb = mfaSuccessCallback
      setMfaSuccessCallback(null)
      cb()
    }
    refreshSession()
  }, [mfaSuccessCallback, refreshSession])

  return (
    <SessionContext.Provider
      value={{
        session,
        loading,
        error,
        activeOrgId,
        setActiveOrgId,
        refreshSession,
        logout,
        isMfaModalOpen,
        requestMfaStepUp,
        closeMfaModal,
        handleMfaSuccess,
        meInfo,
        meLoading,
        memberships,
        isPlatformAdmin,
        activeMembership,
        canManageOrganization,
      }}
    >
      {children}
    </SessionContext.Provider>
  )
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext)
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider')
  }
  return context
}
