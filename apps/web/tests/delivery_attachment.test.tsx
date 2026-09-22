import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { DeliveryWorkbenchView } from '../src/views/DeliveryWorkbenchView'
import type { AssessmentDeliverable, CaseDetail } from '../src/types/api'

const mockCase = {
  id: 'case-1',
  organization_id: 'org-1',
  case_number: '2026-CASE-001',
  title: '大模型量化',
  status: 'review_approved',
  created_at: new Date().toISOString(),
} as unknown as CaseDetail

/** 一个「已达门禁」的候选预评估意见附件。 */
const attachableDeliverable: AssessmentDeliverable = {
  deliverable_version: 'assessment-deliverable-v1',
  version_number: 2,
  rules_version: 'assessment-rules-v3',
  prompt_versions: { 'assessment/novelty': 'novelty-v2' },
  payload_sha256: 'b'.repeat(64),
  status: 'approved',
  status_label: '已批准',
  status_caveat: '复核状态不代表该方案具备专利性或可授权。',
  requires_human_confirmation: true,
  candidate_notice: '本预评估意见全部内容为候选信号，须人工确认，不构成专利性结论。',
  blockers: [],
  flags: [],
  evidence: {
    source_coverage: 0.8,
    verified_citations: 3,
    total_citations: 4,
    missing_anchors: 0,
    unverified_citations: 1,
    failed_sources: 0,
    blocks_conclusion: false,
  },
  three_step: {
    closest_prior_art: 'CN1A',
    closest_prior_art_identical: 1,
    distinguishing_features: ['F2'],
    actual_technical_problem: '待代理师归纳',
    note: '三步法脚手架为待代理师填写的部分。',
  },
  findings: [],
  entity_observations: [],
  eligibility: {
    eligible: true,
    reasons: ['已批准且无阻塞项'],
    version_number: 2,
    payload_sha256: 'b'.repeat(64),
    gate_version: 'report-conclusion-gate-v1',
  },
  publication_disclaimer: '本意见不构成专利性结论或授权前景意见。',
  version_freeze_declaration: '本意见基于冻结的预评估版本 v2 生成。',
  generated_at: new Date().toISOString(),
  attachable: true,
}

const renderView = () =>
  render(
    <Router>
      <SessionProvider>
        <DeliveryWorkbenchView orgId="org-1" caseId="case-1" />
      </SessionProvider>
    </Router>
  )

describe('Delivery package assessment attachment', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
    vi.spyOn(apiClient, 'getCase').mockResolvedValue(mockCase)
    vi.spyOn(apiClient, 'getDeliveryRecord').mockResolvedValue({ delivery: null })
    vi.spyOn(apiClient, 'getActiveReport').mockResolvedValue(null)
  })

  it('shows the attachment item checked with provenance when it passes the gate', async () => {
    vi.spyOn(apiClient, 'getAssessmentDeliveryAttachment').mockResolvedValue({
      attachment: attachableDeliverable,
    })

    renderView()

    await waitFor(() => {
      expect(screen.getByText('交付包清单（预评估意见附件）')).toBeDefined()
    })
    expect(screen.getByText('已达门禁，可纳入交付包')).toBeDefined()
    expect(screen.getByText(/预评估意见 v2（候选，非结论）/)).toBeDefined()
    // provenance 摘要
    expect(screen.getByText('b'.repeat(64))).toBeDefined()
    expect(screen.getByText('assessment-rules-v3')).toBeDefined()
    // 候选措辞始终在场，绝不声称结论
    expect(screen.getByText(/不构成专利性结论/)).toBeDefined()

    const checkbox = screen.getByRole('checkbox') as HTMLInputElement
    expect(checkbox.checked).toBe(true)
    expect(checkbox.disabled).toBe(false)

    // 案件交付门禁满足：正式交付按钮可用
    const deliverBtn = screen.getByRole('button', {
      name: /确认正式交付客户/,
    }) as HTMLButtonElement
    expect(deliverBtn.disabled).toBe(false)
    // 门禁未满足的警示不出现
    expect(screen.queryByText(/案件交付门禁未满足/)).toBeNull()

    // 增量 15：附件项提供可打印 HTML 下载，指向只读导出端点
    const htmlLink = screen.getByRole('link', {
      name: /下载可打印 HTML/,
    }) as HTMLAnchorElement
    expect(htmlLink.href).toContain(
      '/api/v1/organizations/org-1/cases/case-1/assessments/2/deliverable.html'
    )
  })

  it('leaves the item unchecked and explains the gate when not attachable', async () => {
    vi.spyOn(apiClient, 'getAssessmentDeliveryAttachment').mockResolvedValue({
      attachment: {
        ...attachableDeliverable,
        version_number: 3,
        status: 'submitted',
        status_label: '待复核',
        attachable: false,
        attachment_reason: '所选版本尚未达到交付附件门禁：须为已批准且无阻塞项的评估版本。',
        eligibility: { ...attachableDeliverable.eligibility, eligible: false, version_number: 3 },
      },
    })

    renderView()

    await waitFor(() => {
      expect(screen.getByText('未达门禁，不可纳入')).toBeDefined()
    })
    expect(screen.getByText(/尚未达到交付附件门禁/)).toBeDefined()

    const checkbox = screen.getByRole('checkbox') as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    expect(checkbox.disabled).toBe(true)

    // 案件交付门禁未满足：警示在场、不可逆的正式交付按钮被禁用
    expect(screen.getByText(/案件交付门禁未满足/)).toBeDefined()
    expect(screen.getByText(/当前最新版本（v3，待复核）未达门禁/)).toBeDefined()
    const deliverBtn = screen.getByRole('button', {
      name: /交付门禁未满足，暂不可交付/,
    }) as HTMLButtonElement
    expect(deliverBtn.disabled).toBe(true)

    // 未达门禁只禁止「纳入交付包」，不隐藏候选打印件本身（只读且自带免责声明）
    const htmlLink = screen.getByRole('link', {
      name: /下载可打印 HTML/,
    }) as HTMLAnchorElement
    expect(htmlLink.href).toContain(
      '/api/v1/organizations/org-1/cases/case-1/assessments/3/deliverable.html'
    )
  })

  it('shows an honest empty state when no assessment version exists', async () => {
    vi.spyOn(apiClient, 'getAssessmentDeliveryAttachment').mockResolvedValue({
      attachment: null,
    })

    renderView()

    await waitFor(() => {
      expect(
        screen.getByText('尚未创建任何预评估版本，无可挂接的预评估意见。')
      ).toBeDefined()
    })
    expect(screen.queryByRole('checkbox')).toBeNull()
    // 无附件时同样不提供打印件下载
    expect(screen.queryByRole('link', { name: /下载可打印 HTML/ })).toBeNull()

    // 没有任何评估版本同样不满足交付门禁：警示在场、交付按钮禁用
    expect(screen.getByText(/案件交付门禁未满足/)).toBeDefined()
    expect(screen.getByText(/本案尚未创建任何预评估版本/)).toBeDefined()
    const deliverBtn = screen.getByRole('button', {
      name: /交付门禁未满足，暂不可交付/,
    }) as HTMLButtonElement
    expect(deliverBtn.disabled).toBe(true)
  })
})
