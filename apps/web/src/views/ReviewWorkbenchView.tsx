import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { MarkdownViewer } from '../components/MarkdownViewer'
import { CaseWorkflowStepper } from '../components/CaseWorkflowStepper'
import type {
  ComparisonMatrixDetail,
  EvidenceSnapshotDetail,
  ItemizedFeedback,
  CaseDetail,
  ReviewSubmission,
} from '../types/api'
import { Link } from '../router/Router'

interface ReviewWorkbenchViewProps {
  orgId: string
  caseId: string
}

export const ReviewWorkbenchView: React.FC<ReviewWorkbenchViewProps> = ({
  orgId,
  caseId,
}) => {
  const { session } = useSession()

  const [currentCase, setCurrentCase] = useState<CaseDetail | null>(null)
  const [currentReview, setCurrentReview] = useState<ReviewSubmission | null>(null)
  const [reviewHistory, setReviewHistory] = useState<ReviewSubmission[]>([])
  const [reportDetail, setReportDetail] = useState<EvidenceSnapshotDetail | null>(null)
  const [matrixData, setMatrixData] = useState<ComparisonMatrixDetail | null>(null)

  const [activeTab, setActiveTab] = useState<'claims' | 'report' | 'history'>('claims')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [copiedMarkdown, setCopiedMarkdown] = useState(false)

  // Submit Modal
  const [showSubmitModal, setShowSubmitModal] = useState(false)
  const [submitNotes, setSubmitNotes] = useState('')

  // Review Decision Form
  const [decisionType, setDecisionType] = useState<'approved' | 'changes_requested' | 'rejected'>('approved')
  const [overallComments, setOverallComments] = useState('')
  const [itemizedFeedback, setItemizedFeedback] = useState<Record<string, string>>({})
  const [showSelfAuditModal, setShowSelfAuditModal] = useState(false)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [cRes, revRes, histRes, repRes, matRes] = await Promise.all([
        apiClient.getCase(orgId, caseId),
        apiClient.getCurrentReview(orgId, caseId).catch(() => ({ review: null })),
        apiClient.listReviewHistory(orgId, caseId).catch(() => ({ items: [] })),
        apiClient.getActiveReport(orgId, caseId).catch(() => null),
        apiClient.getActiveComparisonMatrix(orgId, caseId).catch(() => null),
      ])

      setCurrentCase(cRes)
      setCurrentReview(revRes.review)
      setReviewHistory(histRes.items || [])
      setReportDetail(repRes)
      setMatrixData(matRes)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('加载复核数据失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [orgId, caseId])

  const handleSubmitReview = async () => {
    setActionLoading(true)
    setError(null)
    try {
      await apiClient.submitCaseReview(orgId, caseId, submitNotes)
      setSuccess('已成功发起案件复核申请')
      setShowSubmitModal(false)
      setSubmitNotes('')
      await loadData()
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('提交复核申请失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleRecordDecision = async (confirmedSelfAudit = false) => {
    const isSelf = currentReview?.submitter_identity_id === session?.identity_id
    if (isSelf && !confirmedSelfAudit) {
      setShowSelfAuditModal(true)
      return
    }

    setActionLoading(true)
    setError(null)
    try {
      const feedbackList: ItemizedFeedback[] = Object.entries(itemizedFeedback)
        .filter(([_, comment]) => comment.trim().length > 0)
        .map(([featId, comment]) => ({
          feature_id: featId,
          comment: comment.trim(),
        }))

      await apiClient.recordReviewDecision(orgId, caseId, {
        decision: decisionType,
        overall_comments: overallComments,
        itemized_feedback: feedbackList,
        is_self_audit: isSelf,
      })

      setSuccess(
        decisionType === 'approved'
          ? '🎉 案件已终审批准！证据与分析报告已完成不可变签名封存。'
          : decisionType === 'changes_requested'
          ? '⚠️ 已退回代理师修改，逐项批注已同步至比对工作台。'
          : '已拒绝该提审轮次。'
      )
      setShowSelfAuditModal(false)
      setOverallComments('')
      setItemizedFeedback({})
      await loadData()
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('记录复核决策失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleCopyMarkdown = () => {
    if (reportDetail?.report?.content) {
      navigator.clipboard.writeText(reportDetail.report.content)
      setCopiedMarkdown(true)
      setTimeout(() => setCopiedMarkdown(false), 2000)
    }
  }

  const isSubmitter = currentReview?.submitter_identity_id === session?.identity_id
  const isPending = currentReview?.status === 'pending'
  const isApproved =
    currentCase?.status === 'approved' ||
    currentReview?.status === 'approved' ||
    currentCase?.status === 'delivered'

  return (
    <div className="layout-container">
      <Header />

      <main className="main-content">
        {/* Navigation Breadcrumb */}
        <div className="breadcrumb text-xs text-secondary mb-xs">
          <Link to={`/organizations/${orgId}/cases`}>案件列表</Link> &gt;{' '}
          <Link to={`/organizations/${orgId}/cases/${caseId}`}>
            {currentCase?.case_number || '案件详情'}
          </Link>{' '}
          &gt; ⚖️ 独立复核与三审流转
        </div>

        {/* Page Header */}
        <div className="page-header flex-between mb-md">
          <div>
            <div className="flex-row gap-sm mb-xs">
              <span className="badge badge-neutral font-mono">{currentCase?.case_number}</span>
              <span className="badge badge-neutral">{currentCase?.target_jurisdiction || 'CN'}</span>
              <StatusBadge status={currentCase?.status || 'draft'} />
            </div>
            <h1 className="page-title text-2xl font-bold">
              {currentCase?.title || '专利案件复核'}
            </h1>
            <p className="text-secondary text-sm">
              技术领域：{currentCase?.technical_field || '未指定'}
            </p>
          </div>

          <div className="actions flex-row gap-sm">
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/comparisons`}
              className="btn btn-secondary btn-sm"
            >
              📊 特征对比表
            </Link>
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/reports`}
              className="btn btn-secondary btn-sm"
            >
              📄 证据与报告
            </Link>

            {isApproved ? (
              <Link
                to={`/organizations/${orgId}/cases/${caseId}/delivery`}
                className="btn btn-primary btn-sm"
              >
                📦 进入正式交付中心 →
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => setShowSubmitModal(true)}
                className="btn btn-primary btn-sm"
              >
                {currentReview ? '🔄 重新发起提审 (下一轮)' : '🚀 提交复核申请'}
              </button>
            )}
          </div>
        </div>

        {/* Workflow Lifecycle Stepper */}
        <CaseWorkflowStepper
          orgId={orgId}
          caseId={caseId}
          currentStep="review"
          caseStatus={currentCase?.status}
        />

        {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
        {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

        {/* Status Summary Banner */}
        <div className="card p-md mb-md">
          <div className="flex-between align-center">
            <div className="flex-row gap-md align-center">
              <div>
                <span className="text-xs text-secondary block mb-xs">当前复核状态</span>
                <span className="font-semibold text-sm">
                  {currentReview ? `第 ${currentReview.round_number} 轮提审 (${currentReview.status})` : '尚未发起提审'}
                </span>
              </div>
              <div className="border-l pl-md">
                <span className="text-xs text-secondary block mb-xs">不可变 Merkle Root</span>
                <span className="font-mono text-xs font-bold text-text bg-subtle px-xs py-1 rounded border">
                  {reportDetail?.snapshot.root_sha256
                    ? `${reportDetail.snapshot.root_sha256.slice(0, 20)}...`
                    : currentReview?.root_sha256
                    ? `${currentReview.root_sha256.slice(0, 20)}...`
                    : '未封存'}
                </span>
              </div>
            </div>

            <div className="text-right">
              <span className="text-xs text-secondary block mb-xs">责任提审人</span>
              <span className="text-xs font-mono">
                {currentReview?.submitter_identity_id
                  ? `Identity: ${currentReview.submitter_identity_id.slice(0, 8)}`
                  : '待提审'}
              </span>
            </div>
          </div>
        </div>

        {/* View Navigation Tabs */}
        <div className="flex-row gap-sm border-b pb-xs mb-md">
          <button
            type="button"
            className={`btn btn-sm ${activeTab === 'claims' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab('claims')}
          >
            🔍 权利要求逐项复核与签署 (Claim Chart)
          </button>
          <button
            type="button"
            className={`btn btn-sm ${activeTab === 'report' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab('report')}
          >
            📄 分析与预评估报告全文预览 (Report)
          </button>
          <button
            type="button"
            className={`btn btn-sm ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab('history')}
          >
            📜 多轮复核历史追溯 (Audit Trail)
          </button>
        </div>

        {/* Tab 1: Claims & Sticky Review Decision Form */}
        {activeTab === 'claims' && (
          <div className="grid-2-cols gap-md align-start">
            {/* Left Column: Claims List */}
            <div className="flex-stack gap-md">
              <div className="card p-md">
                <div className="flex-between align-center mb-sm">
                  <h2 className="text-md font-bold">🔍 权利要求逐项比对与复核批注</h2>
                  <span className="text-xs text-secondary">
                    共 {matrixData?.features.length || 0} 个特征项
                  </span>
                </div>
                <p className="text-xs text-secondary mb-md">
                  复核专家可在下方各特征行直接输入修改指引。退回修改后，代理师比对工作台将以黄色显式高亮。
                </p>

                {matrixData?.features && matrixData.features.length > 0 ? (
                  <div className="flex-stack gap-sm">
                    {matrixData.features.map((f) => {
                      const comp = matrixData.comparisons.find((c) => c.claim_feature_id === f.id)
                      const feedback = itemizedFeedback[f.id] || ''

                      return (
                        <div
                          key={f.id}
                          className={`p-sm border rounded ${
                            feedback ? 'bg-yellow-50 border-yellow-300' : 'bg-subtle'
                          }`}
                        >
                          <div className="flex-between align-center mb-xs">
                            <span className="badge badge-primary font-mono font-bold">
                              {f.feature_code}
                            </span>
                            <span
                              className={`badge ${
                                comp?.judgment === 'identical'
                                  ? 'badge-danger'
                                  : comp?.judgment === 'equivalent'
                                  ? 'badge-warning'
                                  : 'badge-success'
                              }`}
                            >
                              判定：{comp?.judgment || '未判定'}
                            </span>
                          </div>

                          <p className="text-xs font-semibold text-text mb-xs">
                            {f.feature_statement}
                          </p>

                          {comp?.citation_quote && (
                            <div className="p-xs bg-surface border-l-2 border-primary rounded text-xs text-secondary mb-xs">
                              <strong>引文佐证：</strong> {comp.citation_quote}
                            </div>
                          )}

                          {isPending && (
                            <div className="mt-xs">
                              <input
                                type="text"
                                value={feedback}
                                onChange={(e) =>
                                  setItemizedFeedback({
                                    ...itemizedFeedback,
                                    [f.id]: e.target.value,
                                  })
                                }
                                placeholder="✍️ 针对该特征输入复核意见（如：依据不足，建议补充说明书段落）..."
                                className="form-input text-xs"
                              />
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="p-lg text-center text-secondary text-sm">
                    暂无比对矩阵数据
                  </div>
                )}
              </div>
            </div>

            {/* Right Column: Sticky Decision & Summary Card */}
            <div className="flex-stack gap-md sticky-top">
              {/* Decision Action Card */}
              <div className="card p-md">
                <h2 className="text-md font-bold mb-xs">✍️ 复核结论签署 (Review Decision)</h2>
                <p className="text-xs text-secondary mb-md">
                  独立复核确认后签署决定，系统将生成不可变 SHA-256 数字决策签名。
                </p>

                {isPending ? (
                  <div className="flex-stack gap-md">
                    {isSubmitter && (
                      <div className="p-sm bg-yellow-50 border border-yellow-300 rounded text-xs text-warning">
                        <strong>⚠️ 职责分离提示：</strong> 您是本案提审人。单人执业允许自审通过，系统将在最终交付报告中记录自审标记。
                      </div>
                    )}

                    <div className="form-group">
                      <label className="form-label text-xs font-bold mb-xs">
                        复核决定 (Decision)
                      </label>
                      <div className="flex-row gap-sm">
                        <button
                          type="button"
                          onClick={() => setDecisionType('approved')}
                          className={`btn btn-sm flex-1 ${
                            decisionType === 'approved' ? 'btn-primary' : 'btn-secondary'
                          }`}
                        >
                          ✅ 终审批准通过
                        </button>
                        <button
                          type="button"
                          onClick={() => setDecisionType('changes_requested')}
                          className={`btn btn-sm flex-1 ${
                            decisionType === 'changes_requested' ? 'btn-primary' : 'btn-secondary'
                          }`}
                        >
                          ⚠️ 要求退回修改
                        </button>
                      </div>
                    </div>

                    <div className="form-group">
                      <label className="form-label text-xs font-bold mb-xs">
                        综合评审意见 (Overall Comments)
                      </label>
                      <textarea
                        value={overallComments}
                        onChange={(e) => setOverallComments(e.target.value)}
                        placeholder="输入综合复核评语、法律风险提示与修改指引..."
                        rows={4}
                        className="form-textarea text-xs"
                      />
                    </div>

                    <button
                      type="button"
                      onClick={() => handleRecordDecision(false)}
                      disabled={actionLoading}
                      className="btn btn-primary btn-sm w-full font-bold"
                    >
                      {actionLoading
                        ? '签署封存中...'
                        : `确认签署：${decisionType === 'approved' ? '批准通过并封存' : '退回修改'}`}
                    </button>
                  </div>
                ) : (
                  <div className="p-md text-center">
                    {isApproved ? (
                      <div className="p-sm bg-green-50 border border-green-300 rounded text-success text-xs font-semibold">
                        🎉 本案已终审批准并完成数字封存
                      </div>
                    ) : (
                      <span className="text-secondary text-xs">
                        当前无待审单，请点击右上角按钮发起提审
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Quick Report Link Card */}
              <div className="card p-md bg-subtle">
                <div className="flex-between align-center mb-xs">
                  <span className="font-bold text-xs text-text">📄 预评估报告预览</span>
                  <button
                    type="button"
                    onClick={() => setActiveTab('report')}
                    className="btn btn-secondary btn-xs"
                  >
                    查看渲染全文 &rarr;
                  </button>
                </div>
                <p className="text-xs text-secondary">
                  已生成包含证据溯源、Claim Chart 与侵权评级的正式分析报告。
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Full Width Rendered Markdown Report */}
        {activeTab === 'report' && (
          <div className="card p-lg">
            <div className="flex-between mb-md align-center">
              <div>
                <h2 className="text-lg font-bold">
                  {reportDetail?.report?.title || '专利证据分析与法律评估报告'}
                </h2>
                <p className="text-xs text-secondary">
                  基于不可变证据链（Root SHA-256）自动生成的专业结构化法律分析报告
                </p>
              </div>

              <div className="flex-row gap-sm">
                <button
                  type="button"
                  className="btn btn-secondary btn-xs"
                  onClick={handleCopyMarkdown}
                >
                  {copiedMarkdown ? '✓ 已复制源码！' : '📋 复制 Markdown 源码'}
                </button>
              </div>
            </div>

            <div className="p-md bg-surface border rounded">
              <MarkdownViewer content={reportDetail?.report?.content} />
            </div>
          </div>
        )}

        {/* Tab 3: Full Width Audit Trail History */}
        {activeTab === 'history' && (
          <div className="card p-lg">
            <div className="flex-between align-center mb-md">
              <div>
                <h2 className="text-lg font-bold">📜 多轮复核历史追溯 (Audit Trail)</h2>
                <p className="text-xs text-secondary">
                  不可变历史审计链，记录历次提审说明、专家批注、增量差异与数字防伪签名。
                </p>
              </div>
            </div>

            {reviewHistory.length > 0 ? (
              <div className="flex-stack gap-md">
                {reviewHistory.map((rev) => (
                  <div
                    key={rev.id}
                    className={`p-md border-l-4 rounded bg-subtle ${
                      rev.status === 'approved'
                        ? 'border-green-500'
                        : rev.status === 'changes_requested'
                        ? 'border-yellow-500'
                        : 'border-blue-500'
                    }`}
                  >
                    <div className="flex-between align-center mb-xs">
                      <div className="flex-row gap-sm align-center">
                        <span className="font-bold text-sm text-text">
                          第 {rev.round_number} 轮提审
                        </span>
                        <span
                          className={`badge text-xs ${
                            rev.status === 'approved'
                              ? 'badge-success'
                              : rev.status === 'changes_requested'
                              ? 'badge-warning'
                              : 'badge-neutral'
                          }`}
                        >
                          {rev.status}
                        </span>
                      </div>
                      <span className="text-xs text-muted">
                        创建时间：{new Date(rev.created_at).toLocaleString('zh-CN')}
                      </span>
                    </div>

                    <div className="text-xs text-secondary mb-xs">
                      <strong>提审说明：</strong> {rev.submitter_notes || '无'}
                    </div>

                    {rev.decision && (
                      <div className="p-sm bg-surface border rounded text-xs mt-xs">
                        <div className="font-semibold text-text mb-xs">
                          <strong>复核决策评语：</strong> {rev.decision.overall_comments || '无'}
                        </div>
                        <div className="font-mono text-muted text-xs">
                          <strong>SHA-256 签名：</strong> {rev.decision.decision_signature}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-lg text-center text-secondary text-sm">
                暂无历史轮次记录
              </div>
            )}
          </div>
        )}

        {/* Submit Modal */}
        {showSubmitModal && (
          <Modal
            isOpen={showSubmitModal}
            title="🚀 提交案件复核申请"
            onClose={() => setShowSubmitModal(false)}
          >
            <div className="flex-stack gap-md">
              <p className="text-xs text-secondary">
                系统将自动锁定当前技术特征、Claim Chart 比对矩阵与说明书附图，生成防篡改证据快照并流转给复核专家。
              </p>
              <div className="form-group">
                <label className="form-label text-xs font-bold mb-xs">
                  提审说明 (Submitter Notes)
                </label>
                <textarea
                  value={submitNotes}
                  onChange={(e) => setSubmitNotes(e.target.value)}
                  placeholder="填写本轮修改重点、查新对比文件聚焦问题或特别提示..."
                  rows={3}
                  className="form-textarea text-xs"
                />
              </div>
              <div className="flex-row gap-sm justify-end">
                <button
                  type="button"
                  onClick={() => setShowSubmitModal(false)}
                  className="btn btn-secondary btn-sm"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSubmitReview}
                  disabled={actionLoading}
                  className="btn btn-primary btn-sm"
                >
                  {actionLoading ? '提交中...' : '确认发起提审'}
                </button>
              </div>
            </div>
          </Modal>
        )}

        {/* Self-Audit Modal */}
        {showSelfAuditModal && (
          <Modal
            isOpen={showSelfAuditModal}
            title="⚠️ 单人自审确认提示"
            onClose={() => setShowSelfAuditModal(false)}
          >
            <div className="flex-stack gap-md">
              <p className="text-sm text-text">
                您当前正以提审人身份对本案进行终审批准。根据业务合规规范，系统将在最终交付报告及审计日志中显式记录【单人执业自审免责标记】。
              </p>
              <div className="flex-row gap-sm justify-end">
                <button
                  type="button"
                  onClick={() => setShowSelfAuditModal(false)}
                  className="btn btn-secondary btn-sm"
                >
                  返回并邀请他人复核
                </button>
                <button
                  type="button"
                  onClick={() => handleRecordDecision(true)}
                  disabled={actionLoading}
                  className="btn btn-primary btn-sm"
                >
                  确认自审并签署封存
                </button>
              </div>
            </div>
          </Modal>
        )}
      </main>
    </div>
  )
}
