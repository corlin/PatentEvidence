import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { InvitationAcceptView } from '../src/views/InvitationAcceptView'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <Router>
      <SessionProvider>{ui}</SessionProvider>
    </Router>
  )
}

describe('Public Invitation Acceptance Flow', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(apiClient, 'getSession').mockRejectedValue(new Error('unauthenticated'))
  })

  it('inspects valid invitation token and displays preflight details', async () => {
    const inspectSpy = vi.spyOn(apiClient, 'inspectInvitation').mockResolvedValue({
      organization: {
        id: 'org-123',
        display_name: '创新专利代理事务所',
      },
      email: 'newagent@chuangxin.com',
      role: 'patent_agent',
      status: 'pending',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      existing_identity: false,
    })

    renderWithProviders(<InvitationAcceptView />)

    const tokenInput = screen.getByLabelText(/输入 72 小时单次邀请凭证/i)
    fireEvent.change(tokenInput, { target: { value: 'valid-test-token-123' } })
    fireEvent.click(screen.getByRole('button', { name: '解析邀请信息' }))

    await waitFor(() => {
      expect(inspectSpy).toHaveBeenCalledWith('valid-test-token-123')
      expect(screen.getByText('创新专利代理事务所')).toBeDefined()
      expect(screen.getByText('newagent@chuangxin.com')).toBeDefined()
      expect(screen.getByText('patent_agent')).toBeDefined()
    })
  })

  it('submits name and password to accept invitation for new user', async () => {
    vi.spyOn(apiClient, 'inspectInvitation').mockResolvedValue({
      organization: {
        id: 'org-123',
        display_name: '创新专利代理事务所',
      },
      email: 'newagent@chuangxin.com',
      role: 'patent_agent',
      status: 'pending',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      existing_identity: false,
    })
    const acceptSpy = vi.spyOn(apiClient, 'acceptInvitation').mockResolvedValue({
      membership: {
        id: 'new-membership-id',
        organization_id: 'org-123',
        identity_id: 'new-identity-id',
        email: 'newagent@chuangxin.com',
        display_name: '李四',
        role: 'patent_agent',
        status: 'active',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    })

    renderWithProviders(<InvitationAcceptView />)

    const tokenInput = screen.getByLabelText(/输入 72 小时单次邀请凭证/i)
    fireEvent.change(tokenInput, { target: { value: 'valid-test-token-123' } })
    fireEvent.click(screen.getByRole('button', { name: '解析邀请信息' }))

    await waitFor(() => {
      expect(screen.getByText('创新专利代理事务所')).toBeDefined()
    })

    fireEvent.change(screen.getByPlaceholderText(/例如：张明/i), {
      target: { value: '李四' },
    })
    const passwordInputs = screen.getAllByPlaceholderText(/••••••••••••/i)
    fireEvent.change(passwordInputs[0], { target: { value: 'SecurePass1234!' } })
    fireEvent.change(passwordInputs[1], { target: { value: 'SecurePass1234!' } })

    fireEvent.click(screen.getByRole('button', { name: '确认接受邀请并加入' }))

    await waitFor(() => {
      expect(acceptSpy).toHaveBeenCalledWith({
        token: 'valid-test-token-123',
        display_name: '李四',
        password: 'SecurePass1234!',
      })
      expect(screen.getByText(/已成功加入机构/i)).toBeDefined()
    })
  })
})
