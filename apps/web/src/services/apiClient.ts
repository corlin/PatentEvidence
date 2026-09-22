import type {
  AssessmentApplicationProfile,
  AssessmentAssembleResult,
  AssessmentCandidateProfile,
  AssessmentDecisionRecord,
  AssessmentVersionDetail,
  AssessmentVersionSummary,
  CaseDetail,
  CaseDrawing,
  CaseSummary,
  ClaimFeature,
  ClaimFeatureComparison,
  ComparisonMatrixDetail,
  CreateCasePayload,
  CreateInvitationResult,
  CreateOrganizationPayload,
  CreateOrganizationResult,
  DeliveryRecord,
  DocumentVersion,
  EffectiveStatus,
  EvidenceSnapshotDetail,
  FeatureSetDetail,
  FeatureSetVersion,
  FeatureType,
  HandoffPackage,
  InvitationInspection,
  ItemizedFeedback,
  JudgmentType,
  MeInfo,
  OrganizationDetail,
  OrganizationMembership,
  OrganizationRole,
  OrganizationSummary,
  ReviewDecision,
  ReviewSubmission,
  SearchCandidate,
  SearchStrategy,
  SessionInfo,
  TotpConfirmResult,
  TotpEnrollResult,
  TriageStatus,
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

/**
 * 是否为"需要近期 MFA 验证"的 403（后端 detail='mfa_required'）。
 * 仅此类 403 应触发 MFA Step-Up 弹窗；权限拒绝（detail='forbidden'）等其他 403
 * 必须按普通错误展示，否则会陷入"验证→仍 403→再验证"的死循环。
 */
export function isMfaRequired(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 && err.detail === 'mfa_required'
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
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  if (!headers.has('Content-Type') && options.body && !isFormData && typeof options.body === 'string') {
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

  async getMe(): Promise<MeInfo> {
    return request<MeInfo>('/api/v1/auth/me')
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

  // Cases & Documents
  async listCases(orgId: string): Promise<{ items: CaseSummary[] }> {
    return request(`/api/v1/organizations/${orgId}/cases`)
  },

  async getCase(orgId: string, caseId: string): Promise<CaseDetail> {
    return request<CaseDetail>(`/api/v1/organizations/${orgId}/cases/${caseId}`)
  },

  async createCase(orgId: string, payload: CreateCasePayload): Promise<{ case: CaseSummary }> {
    return request(`/api/v1/organizations/${orgId}/cases`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async uploadDocument(orgId: string, caseId: string, file: File): Promise<any> {
    const formData = new FormData()
    formData.append('file', file)
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/documents`, {
      method: 'POST',
      body: formData,
    })
  },

  async listDocumentVersions(orgId: string, caseId: string): Promise<{ items: DocumentVersion[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/document-versions`)
  },

  async confirmDocumentVersion(orgId: string, caseId: string, versionId: string): Promise<any> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/document-versions/${versionId}/confirm`, {
      method: 'POST',
    })
  },

  // Case Drawings
  async listCaseDrawings(orgId: string, caseId: string): Promise<{ items: CaseDrawing[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/drawings`)
  },

  async createCaseDrawing(
    orgId: string,
    caseId: string,
    payload: {
      filename: string
      figure_label: string
      figure_title?: string
      reference_marks?: Array<{ mark: string; name: string }>
      content_base64?: string
      file?: File
      mime_type?: string
    }
  ): Promise<{ drawing: CaseDrawing }> {
    if (payload.file) {
      const formData = new FormData()
      formData.append('file', payload.file)
      formData.append('figure_label', payload.figure_label)
      if (payload.figure_title) formData.append('figure_title', payload.figure_title)
      if (payload.reference_marks) formData.append('reference_marks', JSON.stringify(payload.reference_marks))
      return request(`/api/v1/organizations/${orgId}/cases/${caseId}/drawings`, {
        method: 'POST',
        body: formData,
      })
    }
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/drawings`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async updateCaseDrawing(
    orgId: string,
    caseId: string,
    drawingId: string,
    updates: {
      figure_label?: string
      figure_title?: string
      reference_marks?: Array<{ mark: string; name: string }>
      order_index?: number
    }
  ): Promise<{ drawing: CaseDrawing }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/drawings/${drawingId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    })
  },

  async deleteCaseDrawing(orgId: string, caseId: string, drawingId: string): Promise<void> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/drawings/${drawingId}`, {
      method: 'DELETE',
    })
  },

  async reExtractCaseDrawings(orgId: string, caseId: string): Promise<{ items: CaseDrawing[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/drawings/re-extract`, {
      method: 'POST',
    })
  },

  getCaseDrawingFileUrl(orgId: string, caseId: string, drawingId: string): string {
    return `/api/v1/organizations/${orgId}/cases/${caseId}/drawings/${drawingId}/file`
  },

  // Technical Features
  async extractFeatures(orgId: string, caseId: string): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(`/api/v1/organizations/${orgId}/cases/${caseId}/features/extract`, {
      method: 'POST',
    })
  },

  async getActiveFeatures(orgId: string, caseId: string): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(`/api/v1/organizations/${orgId}/cases/${caseId}/features/active`)
  },

  async listFeatureVersions(orgId: string, caseId: string): Promise<{ items: FeatureSetVersion[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/features/versions`)
  },

  async getFeatureVersion(orgId: string, caseId: string, versionId: string): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(`/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}`)
  },

  async addFeatureItem(
    orgId: string,
    caseId: string,
    versionId: string,
    payload: {
      feature_code?: string
      feature_type?: FeatureType
      feature_statement: string
      source_paragraph_id?: string | null
      citation_quote?: string | null
    }
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/items`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    )
  },

  async updateFeatureItem(
    orgId: string,
    caseId: string,
    versionId: string,
    featureId: string,
    payload: {
      feature_code?: string
      feature_type?: FeatureType
      feature_statement?: string
      source_paragraph_id?: string | null
      citation_quote?: string | null
      sort_order?: number
    }
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/items/${featureId}`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
      }
    )
  },

  async deleteFeatureItem(
    orgId: string,
    caseId: string,
    versionId: string,
    featureId: string
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/items/${featureId}`,
      {
        method: 'DELETE',
      }
    )
  },

  async splitFeatureItem(
    orgId: string,
    caseId: string,
    versionId: string,
    featureId: string,
    part1_statement: string,
    part2_statement: string
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/items/${featureId}/split`,
      {
        method: 'POST',
        body: JSON.stringify({ part1_statement, part2_statement }),
      }
    )
  },

  async mergeFeatureItems(
    orgId: string,
    caseId: string,
    versionId: string,
    featureId1: string,
    featureId2: string,
    merged_statement: string
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/merge`,
      {
        method: 'POST',
        body: JSON.stringify({
          feature_id_1: featureId1,
          feature_id_2: featureId2,
          merged_statement,
        }),
      }
    )
  },

  async confirmFeatureVersion(
    orgId: string,
    caseId: string,
    versionId: string
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/confirm`,
      {
        method: 'POST',
      }
    )
  },

  async createFeatureRevision(
    orgId: string,
    caseId: string,
    versionId: string
  ): Promise<FeatureSetDetail> {
    return request<FeatureSetDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/features/versions/${versionId}/revision`,
      {
        method: 'POST',
      }
    )
  },

  // Patent Search & Candidate Pool
  async generateSearchStrategy(orgId: string, caseId: string): Promise<SearchStrategy> {
    return request<SearchStrategy>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/strategies/generate`,
      { method: 'POST' }
    )
  },

  async getActiveSearchStrategy(orgId: string, caseId: string): Promise<SearchStrategy> {
    return request<SearchStrategy>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/strategies/active`
    )
  },

  async updateSearchStrategy(
    orgId: string,
    caseId: string,
    strategyId: string,
    payload: {
      keywords_matrix?: Record<string, string[]>
      ipc_classes?: Array<{ code: string; description: string }>
      boolean_query_cnipr?: string
      boolean_query_standard?: string
    }
  ): Promise<SearchStrategy> {
    return request<SearchStrategy>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/strategies/${strategyId}`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
      }
    )
  },

  async getSearchHandoffPackage(
    orgId: string,
    caseId: string,
    strategyId: string
  ): Promise<HandoffPackage> {
    return request<HandoffPackage>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/strategies/${strategyId}/handoff`
    )
  },

  async executePublicSearch(
    orgId: string,
    caseId: string,
    sourceType: string = 'openalex',
    keyConfig?: { apiKey?: string; clientId?: string; clientSecret?: string }
  ): Promise<{ job_id: string; status: string; results_count: number }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/jobs/execute-public`,
      {
        method: 'POST',
        body: JSON.stringify({
          source_type: sourceType,
          api_key: keyConfig?.apiKey,
          client_id: keyConfig?.clientId,
          client_secret: keyConfig?.clientSecret,
        }),
      }
    )
  },

  async importCniprCandidates(
    orgId: string,
    caseId: string,
    rawContent: string
  ): Promise<{ imported_count: number }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/candidates/import-cnipr`,
      {
        method: 'POST',
        body: JSON.stringify({ raw_content: rawContent }),
      }
    )
  },

  async listSearchCandidates(
    orgId: string,
    caseId: string,
    triageStatus?: string
  ): Promise<{ items: SearchCandidate[] }> {
    const query = triageStatus ? `?triage_status=${triageStatus}` : ''
    return request<{ items: SearchCandidate[] }>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/candidates${query}`
    )
  },

  async updateCandidateTriage(
    orgId: string,
    caseId: string,
    candidateId: string,
    payload: {
      triage_status: TriageStatus
      exclusion_reason?: string | null
      notes?: string | null
    }
  ): Promise<SearchCandidate> {
    return request<SearchCandidate>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/search/candidates/${candidateId}/triage`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    )
  },

  // Feature Comparison Matrix
  async generateComparisonMatrix(orgId: string, caseId: string): Promise<ComparisonMatrixDetail> {
    return request<ComparisonMatrixDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/comparisons/generate`,
      { method: 'POST' }
    )
  },

  async getActiveComparisonMatrix(orgId: string, caseId: string): Promise<ComparisonMatrixDetail> {
    return request<ComparisonMatrixDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/comparisons/active`
    )
  },

  async updateComparisonItem(
    orgId: string,
    caseId: string,
    comparisonId: string,
    payload: {
      judgment?: JudgmentType
      citation_location?: string | null
      citation_quote?: string | null
      reasoning_analysis?: string | null
    }
  ): Promise<ComparisonMatrixDetail> {
    return request<ComparisonMatrixDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/comparisons/items/${comparisonId}`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
      }
    )
  },

  async confirmComparisonMatrix(
    orgId: string,
    caseId: string,
    matrixId: string
  ): Promise<ComparisonMatrixDetail> {
    return request<ComparisonMatrixDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/comparisons/${matrixId}/confirm`,
      { method: 'POST' }
    )
  },

  // Evidence Snapshots & Analysis Reports
  async sealEvidenceSnapshot(orgId: string, caseId: string): Promise<EvidenceSnapshotDetail> {
    return request<EvidenceSnapshotDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/evidence/seal`,
      { method: 'POST' }
    )
  },

  async getActiveEvidenceSnapshot(
    orgId: string,
    caseId: string
  ): Promise<EvidenceSnapshotDetail> {
    return request<EvidenceSnapshotDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/evidence/active`
    )
  },

  async generateReport(orgId: string, caseId: string): Promise<EvidenceSnapshotDetail> {
    return request<EvidenceSnapshotDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/reports/generate`,
      { method: 'POST' }
    )
  },

  async getActiveReport(orgId: string, caseId: string): Promise<EvidenceSnapshotDetail> {
    return request<EvidenceSnapshotDetail>(
      `/api/v1/organizations/${orgId}/cases/${caseId}/reports/active`
    )
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

  // Review and Delivery
  async submitCaseReview(
    orgId: string,
    caseId: string,
    submitterNotes: string = ''
  ): Promise<{ submission: ReviewSubmission }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/review/submit`, {
      method: 'POST',
      body: JSON.stringify({ submitter_notes: submitterNotes }),
    })
  },

  async getCurrentReview(
    orgId: string,
    caseId: string
  ): Promise<{ review: ReviewSubmission | null }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/review/current`)
  },

  async listReviewHistory(
    orgId: string,
    caseId: string
  ): Promise<{ items: ReviewSubmission[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/review/history`)
  },

  async recordReviewDecision(
    orgId: string,
    caseId: string,
    payload: {
      decision: 'approved' | 'changes_requested' | 'rejected'
      overall_comments?: string
      itemized_feedback?: ItemizedFeedback[]
      is_self_audit?: boolean
    }
  ): Promise<any> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/review/decide`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async deliverCase(
    orgId: string,
    caseId: string,
    clientRecipient: string
  ): Promise<{ delivery: DeliveryRecord }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/delivery/deliver`, {
      method: 'POST',
      body: JSON.stringify({ client_recipient: clientRecipient }),
    })
  },

  async getDeliveryRecord(
    orgId: string,
    caseId: string
  ): Promise<{ delivery: DeliveryRecord | null }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/delivery/record`)
  },

  // Pre-assessment（只读）
  async listAssessmentVersions(
    orgId: string,
    caseId: string
  ): Promise<{ items: AssessmentVersionSummary[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/assessments`)
  },

  async getAssessmentVersion(
    orgId: string,
    caseId: string,
    versionNumber: number
  ): Promise<{ version: AssessmentVersionDetail }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/assessments/${versionNumber}`
    )
  },

  async createAssessmentVersionFromCase(
    orgId: string,
    caseId: string
  ): Promise<AssessmentAssembleResult> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/assessments/from-case`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
  },

  // 预评估复核动作（追加决策记录，不改写版本）
  async submitAssessmentVersion(
    orgId: string,
    caseId: string,
    versionNumber: number
  ): Promise<{ decision: AssessmentDecisionRecord }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/assessments/${versionNumber}/submit`,
      { method: 'POST', body: JSON.stringify({}) }
    )
  },

  async decideAssessmentVersion(
    orgId: string,
    caseId: string,
    versionNumber: number,
    body: {
      decision: 'approved' | 'rejected' | 'changes_requested'
      comments?: string
      accepts_insufficient_evidence?: boolean
    }
  ): Promise<{ decision: AssessmentDecisionRecord }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/assessments/${versionNumber}/decide`,
      { method: 'POST', body: JSON.stringify(body) }
    )
  },

  // 预评估输入档案（可变；改动只影响下一个版本，改不到已冻结的版本）
  async getAssessmentApplicationProfile(
    orgId: string,
    caseId: string
  ): Promise<{ profile: AssessmentApplicationProfile | null }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/assessment-input/application`)
  },

  async upsertAssessmentApplicationProfile(
    orgId: string,
    caseId: string,
    body: {
      filing_date: string
      application_type?: string
      priority_claims?: Array<Record<string, unknown>>
    }
  ): Promise<{ profile: AssessmentApplicationProfile }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/assessment-input/application`,
      { method: 'POST', body: JSON.stringify(body) }
    )
  },

  async listAssessmentCandidateProfiles(
    orgId: string,
    caseId: string
  ): Promise<{ items: AssessmentCandidateProfile[] }> {
    return request(`/api/v1/organizations/${orgId}/cases/${caseId}/assessment-input/candidates`)
  },

  async upsertAssessmentCandidateProfile(
    orgId: string,
    caseId: string,
    candidateId: string,
    body: {
      filing_date?: string | null
      priority_date?: string | null
      filed_in_china?: boolean
      source_verified?: boolean
    }
  ): Promise<{ profile: AssessmentCandidateProfile }> {
    return request(
      `/api/v1/organizations/${orgId}/cases/${caseId}/assessment-input/candidates/${candidateId}`,
      { method: 'POST', body: JSON.stringify(body) }
    )
  },
}
