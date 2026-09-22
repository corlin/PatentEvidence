import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { AssessmentWorkbenchView } from '../src/views/AssessmentWorkbenchView'
import type {
  AssessmentInputSnapshot,
  AssessmentVersionDetail,
  AssessmentVersionSummary,
  CaseDetail,
} from '../src/types/api'

const mockCase = {
  id: 'case-1',
  organization_id: 'org-1',
  case_number: '2026-CASE-001',
  title: '大模型量化',
  status: 'assessment_ready',
  created_at: new Date().toISOString(),
} as unknown as CaseDetail

const summary: AssessmentVersionSummary = {
  id: 'ver-1',
  version_number: 1,
  rules_version: 'assessment-rules-v3',
  prompt_versions: { novelty: 'novelty-v2' },
  payload_sha256: 'a'.repeat(64),
  blockers: [],
  flags: [],
  requires_human_confirmation: true,
  created_at: new Date().toISOString(),
  disclaimer: '本评估仅输出候选发现与阻塞项，不构成专利性结论或法律意见。',
}

const detail: AssessmentVersionDetail = {
  ...summary,
  organization_id: 'org-1',
  case_id: 'case-1',
  status: 'approved',
  created_by_identity_id: 'user-1',
  payload: {
    rules_version: 'assessment-rules-v3',
    reference_kinds: {},
    priority: null,
    entity_observations: [],
    findings: [],
    three_step: null,
    motivation: null,
    auxiliary: { counted: [], unsubstantiated: [] },
    hindsight: null,
    evidence: {
      source_coverage: 1,
      verified_citations: 4,
      total_citations: 4,
      missing_anchors: [],
      unverified_citations: [],
      abstract_only_citations: [],
      failed_sources: [],
      partial_sources: [],
      documents_without_legal_status_timepoint: [],
      blocking_gaps: [],
      flags: [],
      blocks_conclusion: false,
    },
    blockers: [],
    flags: [],
  },
} as unknown as AssessmentVersionDetail

const snapshot: AssessmentInputSnapshot = {
  application_profile: {
    filing_date: '2025-06-01',
    application_type: 'invention',
    priority_claims: [
      {
        claim_id: 'P1',
        priority_date: '2024-06-01',
        country: 'CN',
        first_application: true,
        same_subject: true,
        proof_verified: true,
        covers: ['F1'],
      },
    ],
  },
  candidate_profiles: [
    {
      publication_number: 'CN1A',
      filing_date: '2023-05-01',
      priority_date: null,
      filed_in_china: true,
      source_verified: true,
    },
    {
      publication_number: 'CN2A',
      filing_date: '2023-08-01',
      priority_date: '2023-07-01',
      filed_in_china: false,
      source_verified: false,
    },
  ],
  rules_version: 'assessment-rules-v3',
}

const renderView = () =>
  render(
    <Router>
      <SessionProvider>
        <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
      </SessionProvider>
    </Router>
  )

describe('Frozen input snapshot surface', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
    vi.spyOn(apiClient, 'getCase').mockResolvedValue(mockCase)
    vi.spyOn(apiClient, 'listAssessmentVersions').mockResolvedValue({ items: [summary] })
    vi.spyOn(apiClient, 'getAssessmentVersion').mockResolvedValue({ version: detail })
  })

  it('renders the frozen snapshot read-only with application and candidate profiles', async () => {
    vi.spyOn(apiClient, 'getAssessmentInputSnapshot').mockResolvedValue({ snapshot })

    renderView()

    await waitFor(() => {
      expect(screen.getByText('冻结输入快照（只读）')).toBeDefined()
    })
    // 本案申请信息
    expect(screen.getByText('本案申请日：')).toBeDefined()
    expect(screen.getByText('2025-06-01')).toBeDefined()
    // 优先权主张
    expect(screen.getByText('优先权主张')).toBeDefined()
    expect(screen.getByText('P1')).toBeDefined()
    expect(screen.getByText('2024-06-01')).toBeDefined()
    // 对比文件档案：两份，核验状态如实区分
    expect(screen.getByText('对比文件档案')).toBeDefined()
    expect(screen.getByText('CN1A')).toBeDefined()
    expect(screen.getByText('CN2A')).toBeDefined()
    expect(screen.getByText('已核验')).toBeDefined()
    expect(screen.getByText('未核验')).toBeDefined()
    // 快照是不可变的：版本冻结声明在场
    expect(screen.getByText(/创建时冻结的输入档案/)).toBeDefined()
    // 快照展示绝不声称结论
    expect(screen.queryByText(/已构成结论/)).toBeNull()
  })

  it('shows an honest empty state for pre-snapshot versions without inferring', async () => {
    vi.spyOn(apiClient, 'getAssessmentInputSnapshot').mockResolvedValue({ snapshot: null })

    renderView()

    await waitFor(() => {
      expect(screen.getByText('冻结输入快照（只读）')).toBeDefined()
    })
    expect(screen.getByText(/无冻结快照/)).toBeDefined()
    expect(screen.getByText(/不回读可变档案表做推断/)).toBeDefined()
    // 空态下不渲染档案表格内容
    expect(screen.queryByText('对比文件档案')).toBeNull()
  })
})
