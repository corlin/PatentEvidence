import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { apiClient, ApiError } from '../src/services/apiClient'
import { OrganizationMembersView } from '../src/views/OrganizationMembersView'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <Router>
      <SessionProvider>{ui}</SessionProvider>
    </Router>
  )
}

describe('Organization Members & Administration', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'org-admin-1',
      email: 'admin@huazhi-ip.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
  })

  it('lists members of the specified organization', async () => {
    vi.spyOn(apiClient, 'listOrganizationMembers').mockResolvedValue({
      items: [
        {
          id: 'mem-1',
          organization_id: 'org-123',
          identity_id: 'id-1',
          email: 'agent1@huazhi-ip.com',
          display_name: '张三代理师',
          role: 'patent_agent',
          status: 'active',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    })

    renderWithProviders(<OrganizationMembersView orgId="org-123" />)

    await waitFor(() => {
      expect(screen.getByText('张三代理师')).toBeDefined()
      expect(screen.getByText('agent1@huazhi-ip.com')).toBeDefined()
      expect(screen.getByText('patent_agent')).toBeDefined()
    })
  })

  it('invites a new patent agent and generates 72h token', async () => {
    vi.spyOn(apiClient, 'listOrganizationMembers').mockResolvedValue({
      items: [],
    })
    const inviteSpy = vi.spyOn(apiClient, 'createOrganizationInvitation').mockResolvedValue({
      invitation: {
        id: 'inv-1',
        organization_id: 'org-123',
        email: 'newagent@huazhi-ip.com',
        role: 'patent_agent',
        status: 'pending',
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 72 * 3600000).toISOString(),
        consumed_at: null,
        revoked_at: null,
      },
      invitation_token: 'org-invite-token-xyz',
    })

    renderWithProviders(<OrganizationMembersView orgId="org-123" />)

    await waitFor(() => {
      expect(screen.getByText('机构成员与权限管理')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /\+ 邀请新成员/i }))

    fireEvent.change(screen.getByPlaceholderText(/agent@agency.com/i), {
      target: { value: 'newagent@huazhi-ip.com' },
    })

    fireEvent.click(screen.getByRole('button', { name: '生成邀请链接' }))

    await waitFor(() => {
      expect(inviteSpy).toHaveBeenCalledWith('org-123', 'newagent@huazhi-ip.com', 'patent_agent')
      expect(screen.getByText(/邀请已成功生成！/i)).toBeDefined()
      expect(screen.getByText(/org-invite-token-xyz/)).toBeDefined()
    })
  })

  it('protects the last active administrator against removal / demotion', async () => {
    vi.spyOn(apiClient, 'listOrganizationMembers').mockResolvedValue({
      items: [
        {
          id: 'admin-mem-1',
          organization_id: 'org-123',
          identity_id: 'id-admin',
          email: 'sole-admin@huazhi-ip.com',
          display_name: '唯一机构管理员',
          role: 'organization_admin',
          status: 'active',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    })
    vi.spyOn(apiClient, 'removeMember').mockRejectedValue(
      new ApiError(409, 'last_active_administrator_invariant')
    )

    // Mock confirm to return true
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderWithProviders(<OrganizationMembersView orgId="org-123" />)

    await waitFor(() => {
      expect(screen.getByText('唯一机构管理员')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: '移除' }))

    await waitFor(() => {
      expect(
        screen.getByText(/操作被拒绝：机构必须至少保留一位活跃的机构管理员/i)
      ).toBeDefined()
    })
  })
})
