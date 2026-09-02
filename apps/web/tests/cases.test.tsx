import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { CasesListView } from '../src/views/CasesListView'
import { CaseDetailView } from '../src/views/CaseDetailView'
import type { CaseDetail, CaseSummary } from '../src/types/api'

const mockCaseSummary: CaseSummary = {
  id: 'c1000000-0000-4000-8000-000000000001',
  organization_id: 'org-1',
  case_number: '2026-PAT-001',
  title: '混合注意力量化方法',
  technical_field: '计算机与人工智能',
  target_jurisdiction: 'CN',
  status: 'draft',
  created_by: 'user-1',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

const mockCaseDetail: CaseDetail = {
  ...mockCaseSummary,
  document: {
    id: 'doc-1',
    filename: 'disclosure.docx',
    file_size: 10240,
    mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    sha256: 'a1b2c3d4e5f6',
    created_at: new Date().toISOString(),
  },
  parse_run: {
    id: 'run-1',
    status: 'completed',
    error_summary: null,
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
  document_version: {
    id: 'ver-1',
    version_number: 1,
    parent_version_id: null,
    parsed_text: '正文内容',
    structure_json: [
      {
        id: 'p1',
        index: 1,
        section: '技术领域',
        text: '本发明涉及大模型量化技术。',
        offset_start: 0,
        offset_end: 14,
      },
    ],
    sha256: 'a1b2c3d4e5f6',
    is_confirmed: false,
    created_at: new Date().toISOString(),
  },
}

describe('Cases and Document Web Surfaces', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
  })

  it('renders cases list and opens create case modal', async () => {
    vi.spyOn(apiClient, 'listCases').mockResolvedValue({ items: [mockCaseSummary] })

    render(
      <Router>
        <SessionProvider>
          <CasesListView orgId="org-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('专利评估案件列表')).toBeDefined()
      expect(screen.getByText('混合注意力量化方法')).toBeDefined()
      expect(screen.getByText('2026-PAT-001')).toBeDefined()
    })

    // Click create case button
    fireEvent.click(screen.getByRole('button', { name: '+ 新建评估案件' }))
    expect(screen.getByText('新建专利预评估案件')).toBeDefined()
  })

  it('renders case detail with structured paragraphs and handles version confirmation', async () => {
    vi.spyOn(apiClient, 'getCase').mockResolvedValue(mockCaseDetail)
    const confirmSpy = vi.spyOn(apiClient, 'confirmDocumentVersion').mockResolvedValue({
      status: 'confirmed',
      version_id: 'ver-1',
      case_status: 'document_ready',
    })

    render(
      <Router>
        <SessionProvider>
          <CaseDetailView orgId="org-1" caseId={mockCaseDetail.id} />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('混合注意力量化方法')).toBeDefined()
      expect(screen.getByText('disclosure.docx')).toBeDefined()
      expect(screen.getByText('本发明涉及大模型量化技术。')).toBeDefined()
      expect(screen.getByRole('button', { name: '确认文档解析版本并推进' })).toBeDefined()
    })

    // Confirm document version
    fireEvent.click(screen.getByRole('button', { name: '确认文档解析版本并推进' }))
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledWith('org-1', mockCaseDetail.id, 'ver-1')
    })
  })
})
