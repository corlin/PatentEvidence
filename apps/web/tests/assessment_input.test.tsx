import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient, ApiError } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { AssessmentInputPanel } from '../src/components/AssessmentInputPanel'
import type {
  AssessmentApplicationProfile,
  AssessmentAssembleResult,
  AssessmentCandidateProfile,
  AssessmentVersionSummary,
} from '../src/types/api'

const profile: AssessmentApplicationProfile = {
  id: 'prof-1',
  filing_date: '2025-03-01',
  application_type: 'invention',
  priority_claims: [],
  recorded_by_identity_id: 'user-1',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

const profiled: AssessmentCandidateProfile = {
  id: 'cdp-1',
  candidate_id: 'cand-1',
  publication_number: 'CN1A',
  title: '文献一',
  filing_date: '2023-05-01',
  priority_date: null,
  filed_in_china: true,
  source_verified: true,
  verified_by_identity_id: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  has_profile: true,
}

const unprofiled: AssessmentCandidateProfile = {
  ...profiled,
  id: null,
  candidate_id: 'cand-2',
  publication_number: 'CN2A',
  title: '文献二',
  filing_date: null,
  priority_date: null,
  filed_in_china: null,
  source_verified: false,
  has_profile: false,
}

const version: AssessmentVersionSummary = {
  id: 'ver-9',
  version_number: 9,
  rules_version: 'assessment-rules-v3',
  prompt_versions: {},
  payload_sha256: 'b'.repeat(64),
  blockers: ['对比文件 CN2A 缺申请日与优先权日'],
  flags: [],
  requires_human_confirmation: true,
  created_at: new Date().toISOString(),
  disclaimer: '不构成专利性结论。',
}

const assembleResult: AssessmentAssembleResult = {
  version,
  gaps: ['对比文件 CN2A 缺申请日与优先权日', '对比文件 CN2A 来源未核验'],
  source: { cell_count: 3 },
  disclaimer: '不构成专利性结论。',
}

function renderPanel() {
  return render(
    <Router>
      <SessionProvider>
        <AssessmentInputPanel orgId="org-1" caseId="case-1" />
      </SessionProvider>
    </Router>
  )
}

describe('Pre-assessment input panel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getAssessmentApplicationProfile').mockResolvedValue({ profile })
    vi.spyOn(apiClient, 'listAssessmentCandidateProfiles').mockResolvedValue({
      items: [profiled, unprofiled],
    })
  })

  it('states that editing profiles cannot rewrite a version already written', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/不会改写任何已经生成的版本/)).toBeDefined()
    })
  })

  it('lists un-profiled candidates instead of hiding them', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('CN2A')).toBeDefined()
    })
    expect(screen.getByText('未建档')).toBeDefined()
    expect(screen.getByText('1 篇尚未建档')).toBeDefined()
  })

  it('saves the subject filing date and priority claims', async () => {
    const upsert = vi
      .spyOn(apiClient, 'upsertAssessmentApplicationProfile')
      .mockResolvedValue({ profile })

    renderPanel()
    await waitFor(() => {
      expect(screen.getByLabelText('本案申请日')).toBeDefined()
    })

    fireEvent.click(screen.getByText('+ 添加一项'))
    fireEvent.change(screen.getByLabelText('在先申请号'), {
      target: { value: 'CN202410000001' },
    })
    fireEvent.change(screen.getByLabelText('优先权日'), { target: { value: '2024-04-01' } })
    fireEvent.click(screen.getByText('保存本案申请信息'))

    await waitFor(() => {
      expect(upsert).toHaveBeenCalledWith('org-1', 'case-1', {
        filing_date: '2025-03-01',
        application_type: 'invention',
        priority_claims: [
          {
            claim_id: 'CN202410000001',
            priority_date: '2024-04-01',
            country: '',
            first_application: true,
            same_subject: true,
            proof_verified: false,
            covers: [],
          },
        ],
      })
    })
  })

  it('refuses to save without a filing date rather than sending a blank baseline', async () => {
    vi.spyOn(apiClient, 'getAssessmentApplicationProfile').mockResolvedValue({ profile: null })
    const upsert = vi.spyOn(apiClient, 'upsertAssessmentApplicationProfile')

    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('本案申请信息（日期门禁的基准）')).toBeDefined()
    })

    fireEvent.click(screen.getByText('保存本案申请信息'))

    await waitFor(() => {
      expect(screen.getByText(/申请日是日期门禁的基准日，不能为空/)).toBeDefined()
    })
    expect(upsert).not.toHaveBeenCalled()
  })

  it('shows source gaps ahead of any success signal after assembling', async () => {
    vi.spyOn(apiClient, 'createAssessmentVersionFromCase').mockResolvedValue(assembleResult)

    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('生成新版本')).toBeDefined()
    })

    fireEvent.click(screen.getByText('生成新版本'))

    await waitFor(() => {
      expect(screen.getByText(/下列源数据缺口未解决/)).toBeDefined()
    })
    expect(screen.getByText('对比文件 CN2A 缺申请日与优先权日')).toBeDefined()
    expect(screen.getByText('对比文件 CN2A 来源未核验')).toBeDefined()
    // 组装成功时不得只回一句「成功」而把缺口藏起来
    expect(screen.queryByText(/组装成功/)).toBeNull()
  })

  it('translates an assembly refusal into what is actually missing', async () => {
    vi.spyOn(apiClient, 'createAssessmentVersionFromCase').mockRejectedValue(
      new ApiError(422, 'application_profile_missing')
    )

    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('生成新版本')).toBeDefined()
    })

    fireEvent.click(screen.getByText('生成新版本'))

    await waitFor(() => {
      expect(screen.getByText(/尚未登记本案申请日/)).toBeDefined()
    })
  })

  it('saves a candidate profile with the dates entered', async () => {
    const upsert = vi
      .spyOn(apiClient, 'upsertAssessmentCandidateProfile')
      .mockResolvedValue({ profile: { ...unprofiled, id: 'cdp-2', has_profile: true } })

    renderPanel()
    await waitFor(() => {
      expect(screen.getByText('CN2A')).toBeDefined()
    })

    fireEvent.change(screen.getByLabelText('CN2A 申请日'), {
      target: { value: '2022-08-08' },
    })
    fireEvent.click(screen.getByLabelText('保存 CN2A 档案'))

    await waitFor(() => {
      expect(upsert).toHaveBeenCalledWith('org-1', 'case-1', 'cand-2', {
        filing_date: '2022-08-08',
        priority_date: null,
        filed_in_china: true,
        source_verified: false,
      })
    })
  })
})
