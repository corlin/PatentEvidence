import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { SearchWorkbenchView } from '../src/views/SearchWorkbenchView'
import type { SearchStrategy, SearchCandidate, HandoffPackage } from '../src/types/api'

const mockStrategy: SearchStrategy = {
  id: 'strat-1',
  organization_id: 'org-1',
  case_id: 'case-1',
  feature_set_version_id: 'v-1',
  keywords_matrix: {
    大模型: ['大模型', '大语言模型', 'LLM'],
    量化: ['量化', '低位宽', '混合精度'],
  },
  ipc_classes: [
    { code: 'G06N 3/08', description: '神经网络计算' },
    { code: 'G06F 17/16', description: '矩阵计算' },
  ],
  boolean_query_cnipr: '(大模型 OR LLM) AND (量化 OR 低位宽) AND (IPC:G06N+)',
  boolean_query_standard: '(大模型 OR LLM) AND (量化 OR 低位宽)',
  status: 'confirmed',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

const mockCandidates: SearchCandidate[] = [
  {
    id: 'cand-1',
    publication_number: 'CN117283912A',
    publication_number_normalized: 'CN117283912A',
    title: '一种大模型多尺度量化加速系统',
    abstract: '本发明公开了一种基于奇异值分解的量化方法...',
    publication_date: '2024-03-15',
    applicant: '前沿智能科技创新研究院',
    ipc_classification: 'G06N 3/08',
    source_type: 'google_patents',
    relevance_score: 95.0,
    created_at: new Date().toISOString(),
    triage_status: 'pending',
    exclusion_reason: null,
    notes: null,
    triaged_at: null,
  },
]

const mockHandoff: HandoffPackage = {
  markdown: '# CNIPR 官方专利检索人工交接规范包\n案件编号: 2026-TEST-001',
  json: { case: { case_number: '2026-TEST-001' } },
  raw_cnipr_query: '(大模型 OR LLM) AND (量化 OR 低位宽) AND (IPC:G06N+)',
}

describe('Search & Candidate Pool Web Surface', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
    vi.spyOn(apiClient, 'getActiveSearchStrategy').mockResolvedValue(mockStrategy)
    vi.spyOn(apiClient, 'listSearchCandidates').mockResolvedValue({ items: mockCandidates })
    vi.spyOn(apiClient, 'getSearchHandoffPackage').mockResolvedValue(mockHandoff)
  })

  it('renders search strategy and opens handoff modal', async () => {
    render(
      <Router>
        <SessionProvider>
          <SearchWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('专利检索规划与候选证据初筛')).toBeDefined()
      expect(screen.getByText('检索策略已生成 (v1)')).toBeDefined()
      expect(screen.getByText('G06N 3/08')).toBeDefined()
    })

    // Click Export Handoff Modal
    const exportBtn = screen.getByRole('button', { name: '导出 CNIPR 规范交接包' })
    fireEvent.click(exportBtn)

    await waitFor(() => {
      expect(screen.getByText('CNIPR 官方专利检索人工交接规范包')).toBeDefined()
    })
  })

  it('switches to candidate pool tab and performs triage action', async () => {
    const triageSpy = vi.spyOn(apiClient, 'updateCandidateTriage').mockResolvedValue({
      ...mockCandidates[0],
      triage_status: 'included',
    })

    render(
      <Router>
        <SessionProvider>
          <SearchWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('检索规划与 CNIPR 交接包')).toBeDefined()
    })

    // Switch Tab to candidates
    const candTabBtn = screen.getByRole('button', { name: /多路检索与候选池初筛/ })
    fireEvent.click(candTabBtn)

    await waitFor(() => {
      expect(screen.getByText('CN117283912A')).toBeDefined()
      expect(screen.getByText('一种大模型多尺度量化加速系统')).toBeDefined()
    })

    // Click Include Button
    const includeBtn = screen.getByRole('button', { name: '✓ 纳入比对' })
    fireEvent.click(includeBtn)

    await waitFor(() => {
      expect(triageSpy).toHaveBeenCalledWith('org-1', 'case-1', 'cand-1', {
        triage_status: 'included',
      })
    })
  })

  it('links OpenAlex candidates to their original source record', async () => {
    vi.spyOn(apiClient, 'listSearchCandidates').mockResolvedValue({
      items: [
        {
          ...mockCandidates[0],
          id: 'openalex-1',
          publication_number: 'DOI:10.1109/lra.2022.3187876',
          publication_number_normalized: 'DOI101109LRA20223187876',
          source_type: 'openalex',
          raw_metadata: {
            source_url: 'https://openalex.org/W4283693873',
            authors: ['Cosimo Della Santina', 'Manuel G. Catalano'],
          },
        },
      ],
    })

    render(
      <Router>
        <SessionProvider>
          <SearchWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    fireEvent.click(
      await screen.findByRole('button', { name: /多路检索与候选池初筛/ })
    )

    const sourceLink = await screen.findByRole('link', { name: '来源记录查验 ↗' })
    expect(sourceLink.getAttribute('href')).toBe('https://openalex.org/W4283693873')
    expect(screen.getByText('作者：Cosimo Della Santina, Manuel G. Catalano')).toBeDefined()
  })
})
