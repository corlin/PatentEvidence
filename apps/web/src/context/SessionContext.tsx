import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import type { SessionInfo } from '../types/api'

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
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined)

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [activeOrgId, setActiveOrgId] = useState<string | null>(null)

  const [isMfaModalOpen, setIsMfaModalOpen] = useState(false)
  const [mfaSuccessCallback, setMfaSuccessCallback] = useState<(() => void) | null>(null)

  const refreshSession = useCallback(async (): Promise<SessionInfo | null> => {
    try {
      const data = await apiClient.getSession()
      setSession(data)
      setError(null)
      return data
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setSession(null)
      } else if (err instanceof Error) {
        setError(err.message)
      }
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshSession()
  }, [refreshSession])

  const logout = useCallback(async () => {
    try {
      await apiClient.logout()
    } catch {
      // ignore logout failures
    } finally {
      setSession(null)
      setActiveOrgId(null)
      window.history.pushState({}, '', '/login')
      window.dispatchEvent(new PopStateEvent('popstate'))
    }
  }, [])

  const requestMfaStepUp = useCallback((onSuccess: () => void) => {
    setMfaSuccessCallback(() => onSuccess)
    setIsMfaModalOpen(true)
  }, [])

  const closeMfaModal = useCallback(() => {
    setIsMfaModalOpen(false)
    setMfaSuccessCallback(null)
  }, [])

  const handleMfaSuccess = useCallback(() => {
    setIsMfaModalOpen(false)
    if (mfaSuccessCallback) {
      mfaSuccessCallback()
      setMfaSuccessCallback(null)
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
