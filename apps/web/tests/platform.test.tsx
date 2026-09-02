import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { PlatformOrganizationsView } from '../src/views/PlatformOrganizationsView'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <Router>
      <SessionProvider>{ui}</SessionProvider>
    </Router>
  )
}

describe('Platform Organizations Administration', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'plat-admin-1',
      email: 'platform@patenevidence.local',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
  })

  it('lists existing organizations with their statuses', async () => {
    vi.spyOn(apiClient, 'listPlatformOrganizations').mockResolvedValue({
      items: [
        {
          id: 'org-1',
          slug: 'beijing-ip',
          display_name: '北京知识产权代理所',
          persisted_status: 'active',
          effective_status: 'active',
          expires_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    })

    renderWithProviders(<PlatformOrganizationsView />)

    await waitFor(() => {
      expect(screen.getByText('北京知识产权代理所')).toBeDefined()
      expect(screen.getByText('beijing-ip')).toBeDefined()
    })
  })

  it('opens a new organization and displays initial administrator invitation token', async () => {
    vi.spyOn(apiClient, 'listPlatformOrganizations').mockResolvedValue({
      items: [],
    })
    const createSpy = vi.spyOn(apiClient, 'createPlatformOrganization').mockResolvedValue({
      organization: {
        id: 'new-org-id',
        slug: 'shanghai-patent',
        display_name: '上海专利代理事务所',
        persisted_status: 'active',
        effective_status: 'active',
        expires_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      initial_invitation: {
        id: 'inv-1',
        organization_id: 'new-org-id',
        email: 'admin@shanghai-patent.com',
        role: 'organization_admin',
        status: 'pending',
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 72 * 3600000).toISOString(),
        consumed_at: null,
        revoked_at: null,
      },
      invitation_token: 'secret-one-time-token-abc',
    })

    renderWithProviders(<PlatformOrganizationsView />)

    await waitFor(() => {
      expect(screen.getByText('平台机构管理')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /\+ 开通新机构/i }))

    fireEvent.change(screen.getByPlaceholderText(/例如：北京华智知识产权代理事务所/i), {
      target: { value: '上海专利代理事务所' },
    })
    fireEvent.change(screen.getByPlaceholderText(/例如：huazhi-ip/i), {
      target: { value: 'shanghai-patent' },
    })
    fireEvent.change(screen.getByPlaceholderText(/admin@huazhi-ip.com/i), {
      target: { value: 'admin@shanghai-patent.com' },
    })

    fireEvent.click(screen.getByRole('button', { name: '确认开通' }))

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalled()
      expect(screen.getByText(/机构“上海专利代理事务所”已成功开通！/i)).toBeDefined()
      expect(screen.getByText(/secret-one-time-token-abc/)).toBeDefined()
    })
  })
})
