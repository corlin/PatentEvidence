import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient, ApiError } from '../src/services/apiClient'
import { AssessmentReviewPanel } from '../src/components/AssessmentReviewPanel'
import type {
  AssessmentDecisionRecord,
  AssessmentVersionDetail,
  AssessmentVersionSummary,
} from '../src/types/api'

const summary: AssessmentVersionSummary = {
  id: 'ver-1',
  version_number: 3,
  rules_version: 'assessment-rules-v3',
  prompt_versions: {},
  payload_sha256: 'c'.repeat(64),
  blockers: [],
  flags: [],
  requires_human_confirmation: true,
  created_at: new Date().toISOString(),
  disclaimer: '不构成专利性结论。',
}

function detailWith(overrides: Partial<AssessmentVersionDetail>): AssessmentVersionDetail {
  return {
    ...summary,
    organization_id: 'org-1',
    case_id: 'case-1',
    status: 'draft',
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
        verified_citations: 2,
        total_citations: 2,
        missing_anchors: [],
        unverified_citations: [],
        abstract_only_citations: [],
        failed_sources: [],
        partial_sources: [],
        documents_without_legal_status_timepoint: [],
        blocking_gaps: [],
        flags: [],
        blocks_conclusion: false,
        level: 'sufficient',
        rules_version: 'assessment-rules-v3',
      },
      blockers: [],
      flags: [],
      requires_human_confirmation: true,
      prompt_versions: {},
    },
    ...overrides,
  } as AssessmentVersionDetail
}

const decision: AssessmentDecisionRecord = {
  version_id: 'ver-1',
  version_number: 3,
  payload_sha256: 'c'.repeat(64),
  decision: 'approved',
  reviewer_identity_id: 'user-2',
  comments: '已核对',
  open_blockers: [],
  accepts_insufficient_evidence: false,
  decision_signature: 'sig-abcdefghijklmnop',
  decided_at: new Date().toISOString(),
  disclaimer: '不构成专利性结论。',
}

function renderPanel(detail: AssessmentVersionDetail | null) {
  return render(<AssessmentReviewPanel orgId="org-1" caseId="case-1" detail={detail} />)
}

describe('Pre-assessment review panel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('states that approval is about the package, not patentability', () => {
    renderPanel(detailWith({}))
    expect(screen.getByText(/不代表该方案具备专利性或可授权/)).toBeDefined()
  })

  it('never labels a status in a way that reads as a patentability grant', () => {
    renderPanel(detailWith({ status: 'approved' }))
    expect(screen.getByText('复核通过')).toBeDefined()
    expect(screen.queryByText('已批准')).toBeNull()
    expect(screen.getByText(/仅表示本候选评估包通过内部复核/)).toBeDefined()
  })

  it('offers submission while the version is a draft', async () => {
    const submit = vi
      .spyOn(apiClient, 'submitAssessmentVersion')
      .mockResolvedValue({ decision })

    renderPanel(detailWith({ status: 'draft' }))
    fireEvent.click(screen.getByText('提交复核'))

    await waitFor(() => {
      expect(submit).toHaveBeenCalledWith('org-1', 'case-1', 3)
    })
  })

  it('keeps approval disabled until open blockers are explicitly accepted with a reason', async () => {
    const decide = vi.spyOn(apiClient, 'decideAssessmentVersion')
    const blocked = detailWith({ status: 'submitted' })
    blocked.payload.blockers = ['引证未定位：D1/F2']
    renderPanel(blocked)

    const approve = screen.getByText('批准本评估包') as HTMLButtonElement
    expect(approve.disabled).toBe(true)

    fireEvent.click(screen.getByLabelText('明知存在未解决阻塞项仍批准'))
    // 只勾选还不够，必须写明理由
    expect((screen.getByText('批准本评估包') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('接受证据不足必须写明理由。')).toBeDefined()

    fireEvent.change(screen.getByLabelText('复核意见'), {
      target: { value: '客户已知悉该引证未定位，仍要求出具' },
    })

    expect((screen.getByText('批准本评估包') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByText('批准本评估包'))

    await waitFor(() => {
      expect(decide).toHaveBeenCalledWith('org-1', 'case-1', 3, {
        decision: 'approved',
        comments: '客户已知悉该引证未定位，仍要求出具',
        accepts_insufficient_evidence: true,
      })
    })
  })

  it('allows approval without the gate when there is no open blocker', async () => {
    const decide = vi
      .spyOn(apiClient, 'decideAssessmentVersion')
      .mockResolvedValue({ decision })

    renderPanel(detailWith({ status: 'submitted' }))
    const approve = screen.getByText('批准本评估包') as HTMLButtonElement
    expect(approve.disabled).toBe(false)

    fireEvent.click(approve)

    await waitFor(() => {
      expect(decide).toHaveBeenCalledWith('org-1', 'case-1', 3, {
        decision: 'approved',
        comments: '',
        accepts_insufficient_evidence: false,
      })
    })
  })

  it('offers no action on a terminal version and explains that revision means a new version', () => {
    renderPanel(detailWith({ status: 'approved' }))
    expect(screen.getByText(/该版本已处于终态，不可再变更/)).toBeDefined()
    expect(screen.queryByText('批准本评估包')).toBeNull()
    expect(screen.queryByText('提交复核')).toBeNull()
    expect(screen.queryByText('打回修改')).toBeNull()
  })

  it('explains a frozen refusal instead of showing a generic failure', async () => {
    vi.spyOn(apiClient, 'decideAssessmentVersion').mockRejectedValue(
      new ApiError(409, 'version_frozen')
    )

    renderPanel(detailWith({ status: 'submitted' }))
    fireEvent.click(screen.getByText('打回修改'))

    await waitFor(() => {
      expect(screen.getByText(/修订请生成新版本号/)).toBeDefined()
    })
  })

  it('asks for a version to be selected when none is loaded', () => {
    renderPanel(null)
    expect(screen.getByText(/请先在「版本」页签选择一个评估版本/)).toBeDefined()
  })
})
