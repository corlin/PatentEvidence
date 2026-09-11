import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { ReportsWorkbenchView } from '../src/views/ReportsWorkbenchView'
import type { EvidenceSnapshotDetail } from '../src/types/api'

const mockSnapshotDetail: EvidenceSnapshotDetail = {
  snapshot: {
    id: 'snap-1',
    organization_id: 'org-1',
    case_id: 'case-1',
    snapshot_number: 'SNAP-2026-CASE001-01',
    status: 'sealed',
    root_sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
    sealed_by_identity_id: 'user-1',
    sealed_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
  report: {
    id: 'rep-1',
    title: '专利证据分析与法律评估报告 (2026-CASE-001)',
    content: '# 专利证据分析与法律评估报告\n\n> 案件编号：`2026-CASE-001`\n\n## 1. 权利要求技术特征分解',
  },
  payload: {
    case: { case_number: '2026-CASE-001', title: '大模型量化' },
    document: { filename: 'spec.docx', file_sha256: 'doc123456' },
    features: { version_id: 'v1', items: [{ feature_code: 'F1' }] },
    search: { boolean_query_cnipr: '(大模型 OR LLM)' },
    candidates: [{ publication_number: 'CN117283912A' }],
    comparison: { comparisons: [{ feature_code: 'F1' }], risk_level: 'high_novelty_risk' },
  },
}

describe('Reports & Evidence Snapshots Web Surface', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
    vi.spyOn(apiClient, 'getActiveEvidenceSnapshot').mockResolvedValue(mockSnapshotDetail)
  })

  it('renders reports view with Root SHA-256 and report preview', async () => {
    render(
      <Router>
        <SessionProvider>
          <ReportsWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('证据封存与专业报告 (Reports & Evidence)')).toBeDefined()
      expect(screen.getByText(/SNAP-2026-CASE001-01/)).toBeDefined()
      expect(screen.getByText('复制根哈希')).toBeDefined()
      expect(screen.getByText('专利证据分析与法律评估报告 (2026-CASE-001)')).toBeDefined()
    })
  })

  it('switches between report preview and evidence audit timeline', async () => {
    render(
      <Router>
        <SessionProvider>
          <ReportsWorkbenchView orgId="org-1" caseId="case-1" />
        </SessionProvider>
      </Router>
    )

    await waitFor(() => {
      expect(screen.getByText('专业分析报告在线预览')).toBeDefined()
    })

    // Click Timeline tab
    const timelineBtn = screen.getByRole('button', { name: '全流程证据审计时序链' })
    fireEvent.click(timelineBtn)

    await waitFor(() => {
      expect(screen.getByText('全流程不可变证据链审计时序 (Evidence Audit Chain)')).toBeDefined()
      expect(screen.getByText('原始技术交底文档存证')).toBeDefined()
      expect(screen.getByText('不可变全包 Merkle 根哈希封存印章')).toBeDefined()
    })
  })
})
