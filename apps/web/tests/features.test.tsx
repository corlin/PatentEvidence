import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { FeaturesWorkbenchView } from '../src/views/FeaturesWorkbenchView'
import type { FeatureSetDetail } from '../src/types/api'

const mockDraftFeatureSet: FeatureSetDetail = {
  version: {
    id: 'fsv-1',
    organization_id: 'org-1',
    case_id: 'case-1',
    document_version_id: 'dv-1',
    version_number: 1,
    parent_version_id: null,
    status: 'draft',
    summary: '技术特征草稿',
    confirmed_by: null,
    confirmed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  features: [
    {
      id: 'f-1',
      feature_code: 'F1',
      feature_type: 'preamble',
      feature_statement: '一种大模型混合精度量化系统，其特征在于：',
      source_paragraph_id: 'p1',
      citation_quote: '大模型混合精度量化系统',
      sort_order: 1,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: 'f-2',
      feature_code: 'F2',
      feature_type: 'characterizing',
      feature_statement: '通过对权重矩阵执行奇异值分解以获取基向量；',
      source_paragraph_id: 'p2',
      citation_quote: '奇异值分解',
      sort_order: 2,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
}

describe('Features Workbench Web Surface', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
  })

  it('renders features list in draft mode and allows confirmation', async () => {
    vi.spyOn(apiClient, 'getActiveFeatures').mockResolvedValue(mockDraftFeatureSet)
    const confirmSpy = vi.spyOn(apiClient, 'confirmFeatureVersion').mockResolvedValue({
      ...mockDraftFeatureSet,
      version: {
        ...mockDraftFeatureSet.version,
        status: 'confirmed',
        confirmed_at: new Date().toISOString(),
      },
    })

    render(
      <Router>
        <SessionProvider>
          <FeaturesWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('技术特征提取与版本确认')).toBeDefined()
      expect(screen.getByText('F1')).toBeDefined()
      expect(screen.getByText('F2')).toBeDefined()
      expect(screen.getByText('一种大模型混合精度量化系统，其特征在于：')).toBeDefined()
      expect(screen.getByRole('button', { name: '✓ 确认并锁定特征版本' })).toBeDefined()
    })

    // Click Confirm
    fireEvent.click(screen.getByRole('button', { name: '✓ 确认并锁定特征版本' }))
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledWith('org-1', 'case-1', 'fsv-1')
    })
  })

  it('opens split feature modal and handles submit', async () => {
    vi.spyOn(apiClient, 'getActiveFeatures').mockResolvedValue(mockDraftFeatureSet)
    const splitSpy = vi.spyOn(apiClient, 'splitFeatureItem').mockResolvedValue(mockDraftFeatureSet)

    render(
      <Router>
        <SessionProvider>
          <FeaturesWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('F2')).toBeDefined()
    })

    // Click first split button
    const splitButtons = screen.getAllByRole('button', { name: '拆分' })
    fireEvent.click(splitButtons[0])

    expect(screen.getByText('拆分技术特征')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: '确认拆分' }))

    await waitFor(() => {
      expect(splitSpy).toHaveBeenCalled()
    })
  })
})
