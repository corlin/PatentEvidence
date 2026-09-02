import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { LoginView } from '../src/views/LoginView'
import { MfaChallengeView } from '../src/views/MfaChallengeView'
import { MfaEnrollView } from '../src/views/MfaEnrollView'
import { PasswordResetView } from '../src/views/PasswordResetView'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <Router>
      <SessionProvider>{ui}</SessionProvider>
    </Router>
  )
}

describe('Authentication & Security Invariants', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('pe_session')).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
  })

  it('renders login form and submits credentials securely', async () => {
    const loginSpy = vi.spyOn(apiClient, 'login').mockResolvedValue({
      identity_id: 'id-123',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
    })
    const getSessionSpy = vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'id-123',
      email: 'admin@agency.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })

    renderWithProviders(<LoginView />)

    expect(screen.getByRole('heading', { name: 'PatentEvidence' })).toBeDefined()
    const emailInput = screen.getByLabelText(/工作邮箱/i)
    const passwordInput = screen.getByLabelText(/登录密码/i)
    const submitBtn = screen.getByRole('button', { name: '登录' })

    fireEvent.change(emailInput, { target: { value: 'admin@agency.com' } })
    fireEvent.change(passwordInput, { target: { value: 'StrongPassword123!' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(loginSpy).toHaveBeenCalledWith('admin@agency.com', 'StrongPassword123!')
    })
  })

  it('verifies TOTP MFA challenge input', async () => {
    const challengeSpy = vi.spyOn(apiClient, 'challengeMfa').mockResolvedValue({
      status: 'verified',
      expires_at: new Date().toISOString(),
    })
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'id-123',
      email: 'admin@agency.com',
      expires_at: new Date().toISOString(),
      mfa_recent: true,
    })

    renderWithProviders(<MfaChallengeView />)

    const codeInput = screen.getByLabelText(/6 位动态验证码/i)
    const submitBtn = screen.getByRole('button', { name: /确认并进入工作台/i })

    fireEvent.change(codeInput, { target: { value: '123456' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(challengeSpy).toHaveBeenCalledWith({ code: '123456' })
    })
  })

  it('enrolls TOTP MFA and displays recovery codes', async () => {
    vi.spyOn(apiClient, 'enrollTotp').mockResolvedValue({
      credential_id: 'cred-1',
      secret: 'JBSWY3DPEHPK3PXP',
    })
    vi.spyOn(apiClient, 'confirmTotp').mockResolvedValue({
      status: 'verified',
      expires_at: new Date().toISOString(),
      recovery_codes: ['code-1', 'code-2', 'code-3', 'code-4', 'code-5', 'code-6', 'code-7', 'code-8'],
    })
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'id-123',
      email: 'admin@agency.com',
      expires_at: new Date().toISOString(),
      mfa_recent: true,
    })

    renderWithProviders(<MfaEnrollView />)

    await waitFor(() => {
      expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeDefined()
    })

    const codeInput = screen.getByLabelText(/输入验证器生成的 6 位动态验证码确认/i)
    fireEvent.change(codeInput, { target: { value: '654321' } })

    const confirmBtn = await screen.findByRole('button', { name: /确认并启用/i })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(screen.getByText('保存您的一次性恢复码')).toBeDefined()
      expect(screen.getByText('code-1')).toBeDefined()
    })
  })

  it('handles password reset request submission', async () => {
    const resetSpy = vi.spyOn(apiClient, 'requestPasswordReset').mockResolvedValue({
      status: 'accepted',
    })

    renderWithProviders(<PasswordResetView />)

    const emailInput = screen.getByLabelText(/注册邮箱/i)
    fireEvent.change(emailInput, { target: { value: 'agent@agency.com' } })
    fireEvent.click(screen.getByRole('button', { name: /发送重置请求/i }))

    await waitFor(() => {
      expect(resetSpy).toHaveBeenCalledWith('agent@agency.com')
      expect(screen.getByText(/重置指令已发出/i)).toBeDefined()
    })
  })
})
