export type OrganizationRole = 'organization_admin' | 'patent_agent' | 'reviewer'

export type EffectiveStatus = 'active' | 'suspended' | 'expired'
export type PersistedStatus = 'active' | 'suspended'
export type MemberStatus = 'active' | 'suspended' | 'removed'
export type InvitationStatus = 'pending' | 'accepted' | 'revoked'

export type CaseStatus =
  | 'draft'
  | 'document_ready'
  | 'features_confirmed'
  | 'retrieval_ready'
  | 'evidence_ready'
  | 'assessment_ready'
  | 'in_review'
  | 'changes_requested'
  | 'approved'
  | 'delivered'

export interface SessionInfo {
  identity_id: string
  email: string
  expires_at: string
  mfa_recent: boolean
}

/** 当前身份在某机构内的成员关系（来自 GET /api/v1/auth/me）。 */
export interface MyMembership {
  organization_id: string
  organization_name: string
  role: OrganizationRole
  status: MemberStatus
}

/** 当前身份信息：用于前端路由守卫与工作空间解析，只读。 */
export interface MeInfo {
  identity_id: string
  email: string
  is_platform_admin: boolean
  memberships: MyMembership[]
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

// Case & Document Types
export interface CaseSummary {
  id: string
  organization_id: string
  case_number: string
  title: string
  technical_field: string
  target_jurisdiction: string
  status: CaseStatus
  created_by: string
  created_at: string
  updated_at: string
}

export interface SourceDocument {
  id: string
  filename: string
  file_size: number
  mime_type: string
  sha256: string
  created_at: string
}

export interface ParagraphBlock {
  id: string
  index: number
  section: string
  text: string
  offset_start: number
  offset_end: number
}

export interface DocumentVersion {
  id: string
  version_number: number
  parent_version_id: string | null
  parsed_text: string
  structure_json: ParagraphBlock[] | string
  sha256: string
  is_confirmed: boolean
  created_at: string
}

export interface ReferenceMark {
  mark: string
  name: string
  is_claim_feature?: boolean
  claim_numbers?: number[]
  is_independent?: boolean
}

export interface CaseDrawing {
  id: string
  organization_id: string
  case_id: string
  source_document_id: string | null
  document_version_id: string | null
  figure_label: string
  figure_title: string
  reference_marks: ReferenceMark[]
  storage_key: string
  mime_type: string
  file_size: number
  sha256: string
  page_number: number | null
  order_index: number
  is_manually_added: boolean
  created_at: string
  updated_at: string
}

export interface ParseRun {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  error_summary: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface CaseDetail extends CaseSummary {
  document: SourceDocument | null
  parse_run: ParseRun | null
  document_version: DocumentVersion | null
}

export interface CreateCasePayload {
  case_number: string
  title: string
  technical_field: string
  target_jurisdiction?: string
}

// Technical Feature Types
export type FeatureType = 'preamble' | 'characterizing' | 'dependent'

export interface ClaimFeature {
  id: string
  feature_code: string
  feature_type: FeatureType
  feature_statement: string
  source_paragraph_id: string | null
  citation_quote: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface FeatureSetVersion {
  id: string
  organization_id: string
  case_id: string
  document_version_id: string
  version_number: number
  parent_version_id: string | null
  status: 'draft' | 'confirmed' | 'superseded'
  summary: string | null
  confirmed_by: string | null
  confirmed_at: string | null
  created_at: string
  updated_at: string
}

export interface FeatureSetDetail {
  version: FeatureSetVersion
  features: ClaimFeature[]
}

// Search & Candidate Types
export interface SearchStrategy {
  id: string
  organization_id: string
  case_id: string
  feature_set_version_id: string
  keywords_matrix: Record<string, string[]>
  ipc_classes: Array<{ code: string; description: string }>
  boolean_query_cnipr: string
  boolean_query_standard: string
  status: string
  created_at: string
  updated_at: string
}

export interface HandoffPackage {
  markdown: string
  json: any
  raw_cnipr_query: string
}

export type TriageStatus = 'pending' | 'included' | 'excluded'

export interface SearchCandidate {
  id: string
  publication_number: string
  publication_number_normalized: string
  title: string
  abstract: string
  publication_date: string | null
  applicant: string | null
  ipc_classification: string | null
  source_type: string
  relevance_score: number
  created_at: string
  triage_status: TriageStatus
  exclusion_reason: string | null
  notes: string | null
  triaged_at: string | null
  raw_metadata?: Record<string, any> | null
}

// Comparison Matrix Types
export type JudgmentType = 'identical' | 'equivalent' | 'different'

export interface ComparisonMatrixHeader {
  id: string
  organization_id: string
  case_id: string
  feature_set_version_id: string
  name: string
  status: 'draft' | 'confirmed'
  summary: string | null
  confirmed_at: string | null
  confirmed_by_identity_id: string | null
  created_at: string
  updated_at: string
}

export interface ClaimFeatureComparison {
  id: string
  matrix_id: string
  claim_feature_id: string
  candidate_id: string
  judgment: JudgmentType
  confidence_score: number
  citation_location: string | null
  citation_quote: string | null
  reasoning_analysis: string | null
  is_manually_edited: boolean
  created_at: string
  updated_at: string
}

export interface MatrixEvaluation {
  risk_level: string
  summary: string
  high_risk_candidates: string[]
  partial_risk_candidates: string[]
  total_features_count: number
  total_candidates_count: number
}

export interface ComparisonMatrixDetail {
  matrix: ComparisonMatrixHeader
  evaluation: MatrixEvaluation
  features: Array<{
    id: string
    feature_code: string
    feature_type: FeatureType
    feature_statement: string
    source_paragraph_id: string | null
    sort_order: number
  }>
  candidates: Array<{
    id: string
    publication_number: string
    title: string
    applicant: string | null
    publication_date: string | null
  }>
  comparisons: ClaimFeatureComparison[]
}

// Evidence Snapshot and Analysis Report Types
export interface EvidenceSnapshot {
  id: string
  organization_id: string
  case_id: string
  snapshot_number: string
  status: 'sealed' | 'archived'
  root_sha256: string
  sealed_by_identity_id: string
  sealed_at: string
  created_at: string
}

export interface AnalysisReport {
  id: string
  title: string
  content: string
}

export interface EvidenceSnapshotDetail {
  snapshot: EvidenceSnapshot
  report: AnalysisReport | null
  payload: any
}

// Review and Approval Types
export interface ItemizedFeedback {
  feature_id: string
  feature_code?: string
  comment: string
  suggested_judgment?: JudgmentType | null
}

export interface ReviewDecision {
  id: string
  reviewer_identity_id?: string | null
  decision: 'approved' | 'changes_requested' | 'rejected'
  overall_comments: string
  itemized_feedback: ItemizedFeedback[]
  is_self_audit: boolean
  decision_signature: string
  decided_at: string
}

export interface ReviewSubmission {
  id: string
  case_id: string
  round_number: number
  evidence_snapshot_id?: string | null
  root_sha256?: string | null
  report_id?: string | null
  submitter_identity_id?: string | null
  submitter_notes: string
  status: 'pending' | 'changes_requested' | 'approved' | 'rejected'
  created_at: string
  decision?: ReviewDecision | null
}

// Pre-assessment Types
// 预评估版本只承载候选发现与阻塞项，不含任何专利性结论。
// UI 必须保留 disclaimer 与 requires_human_confirmation 的显著性，
// 不得把候选发现渲染成已确认结论。
export type AssessmentVersionStatus = 'draft' | 'submitted' | 'approved' | 'rejected'

export interface AssessmentFinding {
  risk_kind: string
  level: string
  basis: Record<string, string>[]
  requires_human_confirmation: boolean
  reasoning: string
  rules_version: string
}

export interface AssessmentThreeStep {
  closest_prior_art: string
  closest_prior_art_identical: number
  distinguishing_features: string[]
  actual_technical_problem: string
  rules_version: string
}

export interface AssessmentEvidence {
  source_coverage: number
  verified_citations: number
  total_citations: number
  missing_anchors: string[]
  unverified_citations: string[]
  abstract_only_citations: string[]
  failed_sources: string[]
  partial_sources: string[]
  documents_without_legal_status_timepoint: string[]
  blocking_gaps: string[]
  flags: string[]
  blocks_conclusion: boolean
  level: string
  rules_version: string
}

export interface AssessmentPayload {
  rules_version: string
  reference_kinds: Record<string, string>
  priority: Record<string, any> | null
  entity_observations: Record<string, any>[]
  findings: AssessmentFinding[]
  three_step: AssessmentThreeStep | null
  motivation: Record<string, any> | null
  auxiliary: Record<string, any>
  hindsight: Record<string, any> | null
  evidence: AssessmentEvidence
  blockers: string[]
  flags: string[]
  requires_human_confirmation: boolean
  prompt_versions: Record<string, string>
}

export interface AssessmentVersionSummary {
  id: string
  version_number: number
  rules_version: string
  prompt_versions: Record<string, string>
  payload_sha256: string
  blockers: string[]
  flags: string[]
  requires_human_confirmation: boolean
  created_at: string
  disclaimer: string
}

export interface AssessmentVersionDetail extends AssessmentVersionSummary {
  organization_id: string
  case_id: string
  status: AssessmentVersionStatus | null
  payload: AssessmentPayload
  created_by_identity_id: string | null
}

// Pre-assessment input profiles (mutable input, never approval records)
export interface AssessmentApplicationProfile {
  id: string
  filing_date: string | null
  application_type: string
  priority_claims: Array<Record<string, unknown>>
  recorded_by_identity_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AssessmentCandidateProfile {
  id: string | null
  candidate_id: string
  publication_number: string | null
  title: string | null
  filing_date: string | null
  priority_date: string | null
  filed_in_china: boolean | null
  source_verified: boolean
  verified_by_identity_id: string | null
  created_at: string | null
  updated_at: string | null
  has_profile: boolean
}

export interface AssessmentVersionDiff {
  from_version: number
  to_version: number
  from_payload_sha256: string
  to_payload_sha256: string
  rules_version: { from: string; to: string }
  rules_version_changed: boolean
  prompt_changes: Array<{ name: string; from: string; to: string }>
  blockers: { added: string[]; removed: string[]; retained: string[] }
  flags: { added: string[]; removed: string[]; retained: string[] }
  findings: {
    added: AssessmentFinding[]
    removed: AssessmentFinding[]
    retained: AssessmentFinding[]
  }
  evidence: {
    scalars: Record<string, { from: unknown; to: unknown }>
    lists: Record<string, { added: string[]; removed: string[]; retained: string[] }>
  }
  three_step: {
    closest_prior_art: { from: string | null; to: string | null } | null
    actual_technical_problem: { from: string | null; to: string | null } | null
    distinguishing_features: { added: string[]; removed: string[]; retained: string[] }
    present_in_both: boolean
  }
  entity_observations: {
    added: Array<Record<string, unknown>>
    removed: Array<Record<string, unknown>>
    retained: Array<Record<string, unknown>>
  }
  priority_changed: boolean
  requires_human_confirmation: boolean
  inputs?: AssessmentInputDiff | null
  diff_rules_version: string
  notes: string[]
  disclaimer?: string
}

export interface AssessmentInputDiff {
  application_profile: {
    changed_fields: Array<{ field: string; from: string | null; to: string | null }>
    priority_claims: { added: string[]; removed: string[]; retained: string[] }
  }
  candidate_profiles: {
    added: string[]
    removed: string[]
    changed: Array<{
      publication_number: string
      changed_fields: Array<{ field: string; from: unknown; to: unknown }>
    }>
  }
}

export interface AssessmentDecisionRecord {
  version_id: string
  version_number: number
  payload_sha256: string
  decision: string
  reviewer_identity_id: string | null
  comments: string
  open_blockers: string[]
  accepts_insufficient_evidence: boolean
  decision_signature: string
  decided_at: string | null
  disclaimer: string
}

export interface AssessmentAssembleResult {
  version: AssessmentVersionSummary
  gaps: string[]
  source: Record<string, unknown>
  disclaimer: string
}

// Delivery Types
export interface DeliveryRecord {
  id: string
  case_id: string
  client_recipient: string
  download_token: string
  root_sha256?: string | null
  report_title?: string | null
  delivered_at: string
}




