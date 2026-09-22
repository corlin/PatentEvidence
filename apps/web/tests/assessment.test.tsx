import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { AssessmentWorkbenchView } from '../src/views/AssessmentWorkbenchView'
import type { AssessmentVersionDetail, AssessmentVersionSummary, CaseDetail } from '../src/types/api'

const mockCase = {
  id: 'case-1',
  organization_id: 'org-1',
  case_number: '2026-CASE-001',
  title: '大模型量化',
  technical_field: '人工智能',
  status: 'assessment_ready',
  created_at: new Date().toISOString(),
} as unknown as CaseDetail

const summary: AssessmentVersionSummary = {
  id: 'ver-1',
  version_number: 1,
  rules_version: 'assessment-rules-v3',
  prompt_versions: { novelty: 'novelty-v2' },
  payload_sha256: 'a'.repeat(64),
  blockers: ['引证未定位：D1/F2'],
  flags: ['存在系统建议的文献组合，结合动机必须由代理师人工确认'],
  requires_human_confirmation: true,
  created_at: new Date().toISOString(),
  disclaimer: '本评估仅输出候选发现与阻塞项，不构成专利性结论或法律意见。',
}

const detail: AssessmentVersionDetail = {
  ...summary,
  organization_id: 'org-1',
  case_id: 'case-1',
  status: 'draft',
  created_by_identity_id: 'user-1',
  payload: {
    rules_version: 'assessment-rules-v3',
    reference_kinds: { D1: 'prior_art' },
    priority: null,
    entity_observations: [{ feature_code: 'F1', doc_id: 'D1', effect: 'may_defeat_novelty' }],
    findings: [
      {
        risk_kind: 'novelty',
        level: 'high_novelty_risk',
        basis: [{ doc_id: 'D1', feature_code: 'F1' }],
        requires_human_confirmation: true,
        reasoning: 'D1 单独公开了全部特征',
        rules_version: 'assessment-rules-v3',
      },
    ],
    three_step: {
      closest_prior_art: 'D1',
      closest_prior_art_identical: 1,
      distinguishing_features: ['F2'],
      actual_technical_problem: '待代理师归纳',
      rules_version: 'assessment-rules-v3',
    },
    motivation: null,
    auxiliary: { counted: [], unsubstantiated: [] },
    hindsight: null,
    evidence: {
      source_coverage: 0.5,
      verified_citations: 3,
      total_citations: 4,
      missing_anchors: ['D1/F2'],
      unverified_citations: [],
      abstract_only_citations: [],
      failed_sources: [],
      partial_sources: [],
      documents_without_legal_status_timepoint: [],
      blocking_gaps: ['引证未定位：D1/F2'],
      flags: [],
      blocks_conclusion: true,
      level: 'insufficient',
      rules_version: 'assessment-rules-v3',
    },
    blockers: ['引证未定位：D1/F2'],
    flags: ['存在系统建议的文献组合，结合动机必须由代理师人工确认'],
    requires_human_confirmation: true,
    prompt_versions: { novelty: 'novelty-v2' },
  },
}

describe('Pre-assessment Web Surface', () => {
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

  it('always renders the disclaimer banner ahead of any content', async () => {
    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('这不是专利性结论。')).toBeDefined()
    })
    expect(screen.getByText(/不构成专利性结论或法律意见/)).toBeDefined()
  })

  it('labels blockers as the reason no conclusion exists', async () => {
    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('尚未解决的阻塞项（因此本版本不能给出结论）')).toBeDefined()
      expect(screen.getByText(/引证未定位：D1\/F2/)).toBeDefined()
    })
  })

  it('marks candidate findings as requiring human confirmation', async () => {
    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('候选发现（须人工确认）')).toBeDefined()
      expect(screen.getByText('D1 单独公开了全部特征')).toBeDefined()
      expect(screen.getByText('须人工确认')).toBeDefined()
    })
  })

  it('offers no edit or delete affordance for a version', async () => {
    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('版本列表（只读）')).toBeDefined()
    })

    const buttons = screen.getAllByRole('button').map((b) => b.textContent || '')
    expect(buttons.some((t) => t.includes('删除'))).toBe(false)
    expect(buttons.some((t) => t.includes('编辑'))).toBe(false)
  })

  it('explains the empty state without offering manual creation', async () => {
    vi.spyOn(apiClient, 'listAssessmentVersions').mockResolvedValue({ items: [] })

    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText(/该案件尚无预评估版本/)).toBeDefined()
    })
    expect(apiClient.getAssessmentVersion).not.toHaveBeenCalled()
  })

  it('loads the detail for the selected version', async () => {
    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(apiClient.getAssessmentVersion).toHaveBeenCalledWith('org-1', 'case-1', 1)
    })

    expect(screen.getByText('实体级候选观察项（不改变比对判定）')).toBeDefined()
  })

  it('keeps write operations in a separate tab rather than the version area', async () => {
    vi.spyOn(apiClient, 'getAssessmentApplicationProfile').mockResolvedValue({
      profile: {
        id: 'prof-1',
        filing_date: '2025-03-01',
        application_type: 'invention',
        priority_claims: [],
        recorded_by_identity_id: 'user-1',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    })
    vi.spyOn(apiClient, 'listAssessmentCandidateProfiles').mockResolvedValue({ items: [] })

    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    // 默认停在只读版本区，写操作不在其中
    await waitFor(() => {
      expect(screen.getByText('版本列表（只读）')).toBeDefined()
    })
    expect(screen.queryByText('本案申请信息（日期门禁的基准）')).toBeNull()

    fireEvent.click(screen.getByText('准备输入'))

    await waitFor(() => {
      expect(screen.getByText('本案申请信息（日期门禁的基准）')).toBeDefined()
    })
    expect(screen.getByText('生成新版本')).toBeDefined()
    // 切走后版本区不再渲染，避免「可写」与「不可改写」同屏混淆
    expect(screen.queryByText('版本列表（只读）')).toBeNull()
  })

  it('never labels an approved version in a way that reads as patentable', async () => {
    vi.spyOn(apiClient, 'getAssessmentVersion').mockResolvedValue({
      version: { ...detail, status: 'approved' },
    })

    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('复核通过')).toBeDefined()
    })
    expect(screen.queryByText('已批准')).toBeNull()
    expect(screen.getByText(/仅表示本候选评估包通过内部复核/)).toBeDefined()
  })

  it('reloads detail when another version chip is clicked', async () => {
    const second = { ...summary, id: 'ver-2', version_number: 2 }
    vi.spyOn(apiClient, 'listAssessmentVersions').mockResolvedValue({ items: [summary, second] })

    render(
      <Router>
        <SessionProvider>
          <AssessmentWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /版本 2/ })).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: /版本 2/ }))

    await waitFor(() => {
      expect(apiClient.getAssessmentVersion).toHaveBeenCalledWith('org-1', 'case-1', 2)
    })
  })
})
