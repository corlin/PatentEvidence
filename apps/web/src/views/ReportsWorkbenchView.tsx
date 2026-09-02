import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { MarkdownViewer } from '../components/MarkdownViewer'
import type { EvidenceSnapshotDetail } from '../types/api'
import { Link } from '../router/Router'

interface ReportsWorkbenchViewProps {
  orgId: string
  caseId: string
}

export const ReportsWorkbenchView: React.FC<ReportsWorkbenchViewProps> = ({
  orgId,
  caseId,
}) => {
  const { requestMfaStepUp } = useSession()

  const [snapshotDetail, setSnapshotDetail] = useState<EvidenceSnapshotDetail | null>(null)
  const [activeTab, setActiveTab] = useState<'report' | 'timeline'>('report')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [copiedHash, setCopiedHash] = useState(false)
  const [copiedMarkdown, setCopiedMarkdown] = useState(false)

  const fetchSnapshot = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiClient.getActiveEvidenceSnapshot(orgId, caseId)
      setSnapshotDetail(data)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 404) {
        setSnapshotDetail(null)
      } else if (err instanceof ApiError && err.status === 403) {
        requestMfaStepUp(fetchSnapshot)
      } else {
        setError(err.detail || '加载证据快照失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSnapshot()
  }, [orgId, caseId])

  const handleSealSnapshot = async () => {
    setActionLoading(true)
    setError(null)
    try {
      const data = await apiClient.sealEvidenceSnapshot(orgId, caseId)
      setSnapshotDetail(data)
      setSuccess('不可变证据快照已成功封存！Root SHA-256 哈希已生成，案件状态推进为【已完结】。')
    } catch (err: any) {
      setError(err.detail || '封存证据失败，请确保已确认特征并确认锁定权利要求比对表')
    } finally {
      setActionLoading(false)
    }
  }

  const handleCopyHash = () => {
    if (snapshotDetail?.snapshot.root_sha256) {
      navigator.clipboard.writeText(snapshotDetail.snapshot.root_sha256)
      setCopiedHash(true)
      setTimeout(() => setCopiedHash(false), 2000)
    }
  }

  const handleCopyMarkdown = () => {
    if (snapshotDetail?.report?.content) {
      navigator.clipboard.writeText(snapshotDetail.report.content)
      setCopiedMarkdown(true)
      setTimeout(() => setCopiedMarkdown(false), 2000)
    }
  }

  const handleDownloadMarkdown = () => {
    if (!snapshotDetail?.report?.content) return
    const blob = new Blob([snapshotDetail.report.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${snapshotDetail.snapshot.snapshot_number}_patent_report.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDownloadJson = () => {
    if (!snapshotDetail?.payload) return
    const blob = new Blob([JSON.stringify(snapshotDetail.payload, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${snapshotDetail.snapshot.snapshot_number}_evidence_bundle.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const payload = snapshotDetail?.payload

  return (
    <WorkbenchLayout
      currentStep="reports"
      caseStatus={snapshotDetail ? 'in_review' : 'assessment_ready'}
      orgId={orgId}
      caseId={caseId}
      title="证据封存与专业报告 (Reports & Evidence)"
      description="全案全生命周期不可变证据快照封存、Root SHA-256 防伪溯源与专业法律评估报告"
      breadcrumbCurrent="证据封存与专业报告"
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
      headerActions={
        <>
          <Link
            to={`/organizations/${orgId}/cases/${caseId}/comparisons`}
            className="btn btn-secondary btn-sm"
          >
            &larr; 特征比对表
          </Link>
          {snapshotDetail && (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/review`}
              className="btn btn-primary btn-sm font-bold"
            >
              ⚖️ 前往独立复核 &rarr;
            </Link>
          )}
          <Link to={`/organizations/${orgId}/cases/${caseId}`} className="btn btn-secondary btn-sm">
            返回案件主页
          </Link>
        </>
      }
    >

        {snapshotDetail ? (
          <div className="flex-stack gap-md">
            {/* Top Snapshot Integrity Bar */}
            <div className="card p-md border-l-4 border-green-500 bg-green-50">
              <div className="flex-between align-center">
                <div className="flex-row gap-sm align-center">
                  <span className="badge badge-success text-xs font-bold">
                    ✓ 已封存 ({snapshotDetail.snapshot.snapshot_number})
                  </span>
                  <div className="flex-row gap-xs align-center bg-surface p-xs border rounded">
                    <span className="text-xs text-secondary font-mono">Root SHA-256:</span>
                    <span className="text-xs font-mono font-bold text-text">
                      {snapshotDetail.snapshot.root_sha256.slice(0, 16)}...
                      {snapshotDetail.snapshot.root_sha256.slice(-8)}
                    </span>
                    <button
                      type="button"
                      className="btn btn-secondary btn-xs"
                      onClick={handleCopyHash}
                    >
                      {copiedHash ? '已复制！' : '复制根哈希'}
                    </button>
                  </div>
                </div>

                <div className="flex-row gap-sm">
                  <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={handleDownloadMarkdown}
                  >
                    📥 导出 Markdown 报告
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={handleDownloadJson}
                  >
                    📥 导出 JSON 证据全集
                  </button>
                </div>
              </div>
            </div>

            {/* Navigation Tabs */}
            <div className="flex-row gap-sm border-b pb-xs">
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'report' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('report')}
              >
                📄 专业分析报告在线预览
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'timeline' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveTab('timeline')}
              >
                🔒 全流程证据审计时序链
              </button>
            </div>

            {/* Tab 1: Live Report Preview */}
            {activeTab === 'report' && (
              <div className="card p-lg">
                <div className="flex-between mb-md align-center">
                  <h2 className="text-lg font-bold">
                    {snapshotDetail.report?.title || '专利证据分析与法律评估报告'}
                  </h2>
                  <button
                    type="button"
                    className="btn btn-primary btn-xs"
                    onClick={handleCopyMarkdown}
                  >
                    {copiedMarkdown ? '✓ 已复制 Markdown 源码！' : '📋 复制报告 Markdown 源码'}
                  </button>
                </div>

                <div className="p-md bg-surface border rounded">
                  <MarkdownViewer content={snapshotDetail.report?.content} />
                </div>
              </div>
            )}

            {/* Tab 2: Evidence Chain Timeline */}
            {activeTab === 'timeline' && payload && (
              <div className="card p-lg">
                <h2 className="text-lg font-bold mb-md">全流程不可变证据链审计时序 (Evidence Audit Chain)</h2>

                <div className="flex-stack gap-md">
                  {/* Step 1: Doc */}
                  <div className="p-sm border rounded bg-surface">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-primary font-bold">1</span>
                        <span className="font-bold text-sm">原始技术交底文档存证</span>
                      </div>
                      <span className="badge badge-success text-xs">已确认</span>
                    </div>
                    <p className="text-xs text-secondary">
                      文件: <code>{payload.document?.filename}</code> | 文件哈希: <code>{payload.document?.file_sha256}</code>
                    </p>
                  </div>

                  {/* Step 2: Features */}
                  <div className="p-sm border rounded bg-surface">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-primary font-bold">2</span>
                        <span className="font-bold text-sm">权利要求技术特征建模</span>
                      </div>
                      <span className="badge badge-success text-xs">已确认基准</span>
                    </div>
                    <p className="text-xs text-secondary">
                      特征总数: <strong>{payload.features?.items?.length || 0}</strong> 项 | 版本ID: <code>{payload.features?.version_id}</code>
                    </p>
                  </div>

                  {/* Step 3: Search Strategy */}
                  <div className="p-sm border rounded bg-surface">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-primary font-bold">3</span>
                        <span className="font-bold text-sm">专利检索策略与 CNIPR 人工交接留痕</span>
                      </div>
                      <span className="badge badge-success text-xs">已执行</span>
                    </div>
                    <p className="text-xs text-secondary font-mono">
                      CNIPR表达式: {payload.search?.boolean_query_cnipr}
                    </p>
                  </div>

                  {/* Step 4: Candidates */}
                  <div className="p-sm border rounded bg-surface">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-primary font-bold">4</span>
                        <span className="font-bold text-sm">候选对比文献初筛与排除理由审计</span>
                      </div>
                      <span className="badge badge-success text-xs">已完成初筛</span>
                    </div>
                    <p className="text-xs text-secondary">
                      候选总数: <strong>{payload.candidates?.length || 0}</strong> 篇
                    </p>
                  </div>

                  {/* Step 5: Comparison Matrix */}
                  <div className="p-sm border rounded bg-surface">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-primary font-bold">5</span>
                        <span className="font-bold text-sm">权利要求特征深度比对表 (Claim Chart)</span>
                      </div>
                      <span className="badge badge-success text-xs">已锁定确认</span>
                    </div>
                    <p className="text-xs text-secondary">
                      比对项总数: <strong>{payload.comparison?.comparisons?.length || 0}</strong> 条 | 评级: <strong>{payload.comparison?.risk_level}</strong>
                    </p>
                  </div>

                  {/* Step 6: Root Seal */}
                  <div className="p-sm border rounded bg-green-50 border-green-300">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-success font-bold">6</span>
                        <span className="font-bold text-sm text-green-900">不可变全包 Merkle 根哈希封存印章</span>
                      </div>
                      <span className="badge badge-success text-xs">全案完结归档</span>
                    </div>
                    <p className="text-xs font-mono text-green-800">
                      Root SHA-256: <code>{snapshotDetail.snapshot.root_sha256}</code>
                    </p>
                    <p className="text-xs text-secondary mt-xs">
                      签署人: {snapshotDetail.snapshot.sealed_by_identity_id} 于 {snapshotDetail.snapshot.sealed_at}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="card p-xl text-center">
            <h2 className="text-lg font-bold mb-sm">尚未封存案件不可变证据快照</h2>
            <p className="text-sm text-secondary mb-md">
              系统将全流程固化技术交底文件、权利要求特征集、CNIPR检索留痕、候选池初筛审计以及特征比对矩阵，并计算全包 Root SHA-256 防伪根哈希与生成专业分析报告。
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSealSnapshot}
              disabled={actionLoading}
            >
              {actionLoading ? '正在封存证据并生成报告...' : '📦 立即封存不可变证据包并生成报告'}
            </button>
          </div>
        )}
    </WorkbenchLayout>
  )
}
