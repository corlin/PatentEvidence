import type {
  CreateInvitationResult,
  CreateOrganizationPayload,
  CreateOrganizationResult,
  EffectiveStatus,
  InvitationInspection,
  OrganizationDetail,
  OrganizationMembership,
  OrganizationRole,
  OrganizationSummary,
  SessionInfo,
  TotpConfirmResult,
  TotpEnrollResult,
} from '../types/api'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    message?: string
  ) {
    super(message || detail || `API request failed with status ${status}`)
    this.name = 'ApiError'
  }
}

function generateIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return 'key-' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36)
}

async function request<T>(
  path: string,
  options: RequestInit & { idempotency?: boolean } = {}
): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }
  if (options.idempotency && !headers.has('Idempotency-Key')) {
    headers.set('Idempotency-Key', generateIdempotencyKey())
  }

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: 'include',
  })

  if (response.status === 204) {
    return undefined as unknown as T
  }

  let data: any = null
  const contentType = response.headers.get('content-type')
  if (contentType && contentType.includes('application/json')) {
    try {
      data = await response.json()
    } catch {
      data = null
    }
  }

  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : `HTTP ${response.status}`
    throw new ApiError(response.status, detail)
  }

  return data as T
}

export const apiClient = {
  // Auth
  async login(email: string, password: string): Promise<{ identity_id: string; expires_at: string }> {
    return request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },

  async getSession(): Promise<SessionInfo> {
    return request<SessionInfo>('/api/v1/auth/session')
  },

  async logout(): Promise<void> {
    return request<void>('/api/v1/auth/logout', { method: 'POST' })
  },

  async revokeAllSessions(): Promise<void> {
    return request<void>('/api/v1/auth/sessions/revoke', { method: 'POST' })
  },

  async requestPasswordReset(email: string): Promise<{ status: string }> {
    return request('/api/v1/auth/password-reset/request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  },

  async confirmPasswordReset(token: string, new_password: string): Promise<void> {
    return request<void>('/api/v1/auth/password-reset/confirm', {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    })
  },

  async enrollTotp(): Promise<TotpEnrollResult> {
    return request<TotpEnrollResult>('/api/v1/auth/mfa/totp/enroll', { method: 'POST' })
  },

  async confirmTotp(credential_id: string, code: string): Promise<TotpConfirmResult> {
    return request<TotpConfirmResult>('/api/v1/auth/mfa/totp/confirm', {
      method: 'POST',
      body: JSON.stringify({ credential_id, code }),
    })
  },

  async challengeMfa(params: { code?: string; recovery_code?: string }): Promise<TotpConfirmResult> {
    return request<TotpConfirmResult>('/api/v1/auth/mfa/challenge', {
      method: 'POST',
      body: JSON.stringify(params),
    })
  },

  async getRecoveryCodes(): Promise<{ recovery_codes: string[] }> {
    return request('/api/v1/auth/mfa/recovery-codes', { method: 'POST' })
  },

  // Platform
  async listPlatformOrganizations(): Promise<{ items: OrganizationSummary[] }> {
    return request('/api/v1/platform/organizations')
  },

  async getPlatformOrganization(id: string): Promise<OrganizationDetail> {
    return request(`/api/v1/platform/organizations/${id}`)
  },

  async createPlatformOrganization(payload: CreateOrganizationPayload): Promise<CreateOrganizationResult> {
    return request<CreateOrganizationResult>('/api/v1/platform/organizations', {
      method: 'POST',
      idempotency: true,
      body: JSON.stringify(payload),
    })
  },

  async suspendPlatformOrganization(id: string): Promise<{ organization: OrganizationSummary }> {
    return request(`/api/v1/platform/organizations/${id}/suspend`, {
      method: 'POST',
      idempotency: true,
    })
  },

  async reactivatePlatformOrganization(id: string): Promise<{ organization: OrganizationSummary }> {
    return request(`/api/v1/platform/organizations/${id}/reactivate`, {
      method: 'POST',
      idempotency: true,
    })
  },

  async setPlatformOrganizationExpiry(
    id: string,
    expires_at: string | null
  ): Promise<{ organization: OrganizationSummary }> {
    return request(`/api/v1/platform/organizations/${id}/expiry`, {
      method: 'PUT',
      idempotency: true,
      body: JSON.stringify({ expires_at }),
    })
  },

  // Organization
  async listOrganizationMembers(orgId: string): Promise<{ items: OrganizationMembership[] }> {
    return request(`/api/v1/organizations/${orgId}/members`)
  },

  async createOrganizationInvitation(
    orgId: string,
    email: string,
    role: OrganizationRole
  ): Promise<CreateInvitationResult> {
    return request<CreateInvitationResult>(`/api/v1/organizations/${orgId}/invitations`, {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    })
  },

  async revokeOrganizationInvitation(orgId: string, invitationId: string): Promise<any> {
    return request(`/api/v1/organizations/${orgId}/invitations/${invitationId}/revoke`, {
      method: 'POST',
    })
  },

  async resendOrganizationInvitation(
    orgId: string,
    invitationId: string
  ): Promise<CreateInvitationResult> {
    return request<CreateInvitationResult>(
      `/api/v1/organizations/${orgId}/invitations/${invitationId}/resend`,
      { method: 'POST' }
    )
  },

  async updateMemberRole(
    orgId: string,
    membershipId: string,
    role: OrganizationRole
  ): Promise<OrganizationMembership> {
    return request(`/api/v1/organizations/${orgId}/members/${membershipId}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    })
  },

  async suspendMember(orgId: string, membershipId: string): Promise<OrganizationMembership> {
    return request(`/api/v1/organizations/${orgId}/members/${membershipId}/suspend`, {
      method: 'POST',
    })
  },

  async reactivateMember(orgId: string, membershipId: string): Promise<OrganizationMembership> {
    return request(`/api/v1/organizations/${orgId}/members/${membershipId}/reactivate`, {
      method: 'POST',
    })
  },

  async removeMember(orgId: string, membershipId: string): Promise<OrganizationMembership> {
    return request(`/api/v1/organizations/${orgId}/members/${membershipId}/remove`, {
      method: 'POST',
    })
  },

  // Public Invitations
  async inspectInvitation(token: string): Promise<InvitationInspection> {
    return request<InvitationInspection>('/api/v1/invitations/inspect', {
      method: 'POST',
      body: JSON.stringify({ token }),
    })
  },

  async acceptInvitation(params: {
    token: string
    display_name?: string
    password?: string
  }): Promise<{ membership: OrganizationMembership }> {
    return request('/api/v1/invitations/accept', {
      method: 'POST',
      body: JSON.stringify(params),
    })
  },
}
