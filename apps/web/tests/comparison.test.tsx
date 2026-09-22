import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { ComparisonWorkbenchView } from '../src/views/ComparisonWorkbenchView'
import type { ComparisonMatrixDetail } from '../src/types/api'

const mockMatrixData: ComparisonMatrixDetail = {
  matrix: {
    id: 'mat-1',
    organization_id: 'org-1',
    case_id: 'case-1',
    feature_set_version_id: 'v-1',
    name: '权利要求特征比对表',
    status: 'draft',
    summary: '【新颖性高风险预警】：对比文件 CN117283912A 已经全面公开了本申请权利要求的全部技术特征。',
    confirmed_at: null,
    confirmed_by_identity_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  evaluation: {
    risk_level: 'high_novelty_risk',
    summary: '【新颖性高风险预警】：对比文件 CN117283912A 已经全面公开了本申请权利要求的全部技术特征。',
    high_risk_candidates: ['CN117283912A'],
    partial_risk_candidates: [],
    total_features_count: 1,
    total_candidates_count: 1,
    covered_features_count: 1,
    three_step_analysis: {
      step_1_closest_prior_art: {
        candidate_id: 'cand-1',
        publication_number: 'CN117283912A',
        verified_covered_features: 1,
      },
      step_2_distinguishing_features: [],
      step_3_motivation_and_effect: 'not_assessed',
    },
  },
  features: [
    {
      id: 'feat-1',
      feature_code: 'F1',
      feature_type: 'preamble',
      feature_statement: '一种基于大模型混合精度量化的推理加速方法。',
      source_paragraph_id: 'p1',
      sort_order: 1,
    },
  ],
  candidates: [
    {
      id: 'cand-1',
      publication_number: 'CN117283912A',
      title: '大模型多尺度量化加速系统',
      applicant: '前沿智能科技创新研究院',
      publication_date: '2024-03-15',
    },
  ],
  comparisons: [
    {
      id: 'comp-1',
      matrix_id: 'mat-1',
      claim_feature_id: 'feat-1',
      candidate_id: 'cand-1',
      judgment: 'identical',
      confidence_score: 92.0,
      citation_location: '说明书第[0025]段',
      citation_quote: '本发明公开了一种面向大语言模型的低位宽混合精度量化加速架构...',
      reasoning_analysis: '对比文献在说明书中直接公开了该特征的全部技术手段。',
      evidence_status: 'verified',
      evaluation_source: 'jev_live',
      evaluation_metadata: {
        model_id: 'jev-1.13.0',
        question_set_version: 'patent-feature-disclosure-v1',
        latency_ms: 137,
      },
      is_manually_edited: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
}

describe('Comparison Matrix Web Surface', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
    vi.spyOn(apiClient, 'getActiveComparisonMatrix').mockResolvedValue(mockMatrixData)
  })

  it('renders comparison matrix with global risk banner and feature rows', async () => {
    render(
      <Router>
        <SessionProvider>
          <ComparisonWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('权利要求特征深度比对表 (Claim Chart)')).toBeDefined()
      expect(screen.getByText('新颖性高风险预警')).toBeDefined()
      expect(screen.getByText('F1')).toBeDefined()
      expect(screen.getByText(/D1: CN117283912A/)).toBeDefined()
      expect(screen.getByText('Jev 概率判断')).toBeDefined()
      expect(screen.getByText('步骤 1 · 最接近现有技术')).toBeDefined()
      expect(screen.getByText(/模型 jev-1.13.0/)).toBeDefined()
      expect(screen.getByRole('button', { name: '✓ 锁定确认比对表' })).toBeDefined()
    })
  })

  it('allows editing comparison judgment and saving changes', async () => {
    const updateSpy = vi.spyOn(apiClient, 'updateComparisonItem').mockResolvedValue({
      ...mockMatrixData,
      comparisons: [
        {
          ...mockMatrixData.comparisons[0],
          judgment: 'equivalent',
          is_manually_edited: true,
        },
      ],
    })

    render(
      <Router>
        <SessionProvider>
          <ComparisonWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('F1')).toBeDefined()
    })

    // Click Save changes button
    const saveBtn = screen.getByRole('button', { name: '保存修改' })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith('org-1', 'case-1', 'comp-1', {
        judgment: 'identical',
        citation_location: '说明书第[0025]段',
        citation_quote: '本发明公开了一种面向大语言模型的低位宽混合精度量化加速架构...',
        reasoning_analysis: '对比文献在说明书中直接公开了该特征的全部技术手段。',
      })
    })
  })
})
