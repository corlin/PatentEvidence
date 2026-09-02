export type OrganizationRole = 'organization_admin' | 'patent_agent' | 'reviewer'

export type EffectiveStatus = 'active' | 'suspended' | 'expired'
export type PersistedStatus = 'active' | 'suspended'
export type MemberStatus = 'active' | 'suspended' | 'removed'
export type InvitationStatus = 'pending' | 'accepted' | 'revoked'

export interface SessionInfo {
  identity_id: string
  email: string
  expires_at: string
  mfa_recent: boolean
}

export interface OrganizationMembership {
  id: string
  organization_id: string
  organization_name?: string
  identity_id: string
  email: string
  display_name: string
  role: OrganizationRole
  status: MemberStatus
  created_at: string
  updated_at: string
}

export interface OrganizationSummary {
  id: string
  slug: string
  display_name: string
  persisted_status: PersistedStatus
  effective_status: EffectiveStatus
  expires_at: string | null
  created_at: string
  updated_at: string
}

export interface PlanQuota {
  id: string
  organization_id: string
  plan_key: string
  monthly_case_allowance: number
  current_period_start: string
  current_period_end: string
  quota_status: PersistedStatus
  effective_status: EffectiveStatus
  created_at: string
  updated_at: string
}

export interface OrganizationDetail {
  organization: OrganizationSummary
  plan_quota?: PlanQuota
}

export interface OrganizationInvitation {
  id: string
  organization_id: string
  email: string
  role: OrganizationRole
  status: InvitationStatus
  created_at: string
  expires_at: string
  consumed_at: string | null
  revoked_at: string | null
}

export interface InvitationInspection {
  organization: {
    id: string
    display_name: string
  }
  email: string
  role: OrganizationRole
  status: InvitationStatus
  expires_at: string
  existing_identity: boolean
}

export interface CreateOrganizationPayload {
  slug: string
  display_name: string
  admin_email: string
  plan_key: string
  monthly_case_allowance: number
  current_period_start: string
  current_period_end: string
  expires_at?: string | null
}

export interface CreateOrganizationResult {
  organization: OrganizationSummary
  initial_invitation: OrganizationInvitation
  invitation_token: string
}

export interface CreateInvitationResult {
  invitation: OrganizationInvitation
  invitation_token: string
}

export interface TotpEnrollResult {
  credential_id: string
  secret: string
}

export interface TotpConfirmResult {
  status: 'verified'
  expires_at: string
  recovery_codes?: string[]
}
