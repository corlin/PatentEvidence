import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import type {
  CaseDrawing,
  ClaimFeatureComparison,
  ComparisonMatrixDetail,
  JudgmentType,
} from '../types/api'
import { Link } from '../router/Router'

interface ComparisonWorkbenchViewProps {
  orgId: string
  caseId: string
}

export const ComparisonWorkbenchView: React.FC<ComparisonWorkbenchViewProps> = ({
  orgId,
  caseId,
}) => {
  const { requestMfaStepUp } = useSession()

  const [matrixData, setMatrixData] = useState<ComparisonMatrixDetail | null>(null)
  const [drawings, setDrawings] = useState<CaseDrawing[]>([])
  const [previewDrawing, setPreviewDrawing] = useState<CaseDrawing | null>(null)
  const [showAllDrawingsModal, setShowAllDrawingsModal] = useState(false)

  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Local editing cells
  const [editingCells, setEditingCells] = useState<Record<string, ClaimFeatureComparison>>({})
  const [savingCellId, setSavingCellId] = useState<string | null>(null)
  const [reviewFeedback, setReviewFeedback] = useState<Record<string, string>>({})

  const fetchDrawings = async () => {
    try {
      const res = await apiClient.listCaseDrawings(orgId, caseId)
      setDrawings(res.items || [])
    } catch {}
  }

  const fetchMatrix = async () => {
    setLoading(true)
    setError(null)
    try {
      fetchDrawings()
      const [data, revRes] = await Promise.all([
        apiClient.getActiveComparisonMatrix(orgId, caseId),
        apiClient.getCurrentReview(orgId, caseId).catch(() => ({ review: null })),
      ])
      setMatrixData(data)
      if (revRes.review?.decision?.itemized_feedback) {
        const fbMap: Record<string, string> = {}
        for (const fb of revRes.review.decision.itemized_feedback) {
          fbMap[fb.feature_id] = fb.comment
        }
        setReviewFeedback(fbMap)
      }
      const mapped: Record<string, ClaimFeatureComparison> = {}
      for (const comp of data.comparisons) {
        mapped[comp.id] = { ...comp }
      }
      setEditingCells(mapped)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 404) {
        setMatrixData(null)
      } else if (err instanceof ApiError && err.status === 403) {
        requestMfaStepUp(fetchMatrix)
      } else {
        setError(err.detail || '加载比对表失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMatrix()
  }, [orgId, caseId])

  const handleGenerateMatrix = async () => {
    setActionLoading(true)
    setError(null)
    try {
      const data = await apiClient.generateComparisonMatrix(orgId, caseId)
      setMatrixData(data)
      const mapped: Record<string, ClaimFeatureComparison> = {}
      for (const comp of data.comparisons) {
        mapped[comp.id] = { ...comp }
      }
      setEditingCells(mapped)
      setSuccess('权利要求特征比对矩阵已成功自动生成！')
    } catch (err: any) {
      setError(err.detail || '生成比对矩阵失败，请确保已确认技术特征并在候选池中纳入对比文件')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSaveCell = async (comparisonId: string) => {
    const edit = editingCells[comparisonId]
    if (!edit || !matrixData) return

    setSavingCellId(comparisonId)
    setError(null)
    try {
      const updated = await apiClient.updateComparisonItem(orgId, caseId, comparisonId, {
        judgment: edit.judgment,
        citation_location: edit.citation_location,
        citation_quote: edit.citation_quote,
        reasoning_analysis: edit.reasoning_analysis,
      })
      setMatrixData(updated)
      setSuccess('比对判定及论据已成功保存并标记为人工修订！')
    } catch (err: any) {
      setError(err.detail || '保存比对项失败')
    } finally {
      setSavingCellId(null)
    }
  }

  const handleConfirmMatrix = async () => {
    if (!matrixData) return
    setActionLoading(true)
    setError(null)
    try {
      const confirmed = await apiClient.confirmComparisonMatrix(orgId, caseId, matrixData.matrix.id)
      setMatrixData(confirmed)
      setSuccess('比对矩阵已锁定确认！案件状态推进为【比对已确认】。')
    } catch (err: any) {
      setError(err.detail || '确认比对表失败')
    } finally {
      setActionLoading(false)
    }
  }

  // Find drawings that match a feature text
  const getReferencedDrawings = (statement: string): CaseDrawing[] => {
    if (!drawings || drawings.length === 0) return []
    const matched = drawings.filter((d) => {
      const label = d.figure_label.replace(/\s+/g, '')
      return statement.includes(label) || statement.includes(d.figure_label)
    })
    return matched
  }

  const isConfirmed = matrixData?.matrix.status === 'confirmed'

  return (
    <WorkbenchLayout
      currentStep="comparisons"
      caseStatus={isConfirmed ? 'assessment_ready' : 'evidence_ready'}
      orgId={orgId}
      caseId={caseId}
      title="权利要求特征深度比对表 (Claim Chart)"
      description="逐特征 (F1~Fn) 与对比文献 (D1~Dm) 建立三态比对映射、引文锚定与法律论证"
      breadcrumbCurrent="权利要求特征比对"
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
      headerActions={
        <>
          <Link
            to={`/organizations/${orgId}/cases/${caseId}/search`}
            className="btn btn-secondary btn-sm"
          >
            &larr; 检索与候选池
          </Link>
          {!isConfirmed ? (
            <>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleGenerateMatrix}
                disabled={actionLoading}
              >
                🔄 重新智能比对
              </button>
              <button
                type="button"
                className="btn btn-success btn-sm font-bold"
                onClick={handleConfirmMatrix}
                disabled={actionLoading}
              >
                ✓ 锁定确认比对表
              </button>
            </>
          ) : (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/review`}
              className="btn btn-primary btn-sm"
            >
              ⚖️ 提交复核审批 &rarr;
            </Link>
          )}
          <Link to={`/organizations/${orgId}/cases/${caseId}`} className="btn btn-secondary btn-sm">
            返回案件主页
          </Link>
        </>
      }
    >

        {matrixData ? (
          <div className="flex-stack gap-md">
            {/* Global Risk Banner */}
            <div
              className={`card p-md border-l-4 ${
                matrixData.evaluation.risk_level === 'high_novelty_risk'
                  ? 'border-red-500 bg-red-50'
                  : matrixData.evaluation.risk_level === 'inventiveness_risk'
                  ? 'border-yellow-500 bg-yellow-50'
                  : 'border-green-500 bg-green-50'
              }`}
            >
              <div className="flex-between align-center mb-xs">
                <div className="flex-row gap-sm align-center">
                  <span
                    className={`badge font-bold text-xs ${
                      matrixData.evaluation.risk_level === 'high_novelty_risk'
                        ? 'badge-danger'
                        : matrixData.evaluation.risk_level === 'inventiveness_risk'
                        ? 'badge-warning'
                        : 'badge-success'
                    }`}
                  >
                    {matrixData.evaluation.risk_level === 'high_novelty_risk'
                      ? '⚠️ 新颖性高风险预警'
                      : matrixData.evaluation.risk_level === 'inventiveness_risk'
                      ? '⚡ 创造性审查重点关注'
                      : '✓ 良好授权前景'}
                  </span>
                  <span className="text-xs text-secondary font-medium">
                    特征项: <strong>{matrixData.features.length}</strong> | 纳入对比文献: <strong>{matrixData.candidates.length}</strong>
                  </span>
                </div>

                {drawings.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setShowAllDrawingsModal(true)}
                    className="btn btn-secondary btn-xs"
                  >
                    🖼️ 查看全案说明书附图 ({drawings.length} 幅)
                  </button>
                )}
              </div>

              <p className="text-xs font-semibold text-text mt-xs leading-relaxed">
                {matrixData.evaluation.summary}
              </p>
            </div>

            {/* 2D Comparison Matrix */}
            <div className="flex-stack gap-md">
              {matrixData.features.map((feat) => {
                const matchedDrawings = getReferencedDrawings(feat.feature_statement)
                const hasFeedback = reviewFeedback[feat.id]

                return (
                  <div key={feat.id} className="card p-md border rounded bg-surface shadow-sm">
                    {/* Feature Card Header */}
                    <div className="flex-between align-center mb-sm border-b pb-xs">
                      <div className="flex-row gap-xs align-center">
                        <span className="badge badge-primary font-mono font-bold">
                          {feat.feature_code}
                        </span>
                        <span className="badge badge-neutral text-xs">
                          {feat.feature_type === 'preamble'
                            ? '前序特征'
                            : feat.feature_type === 'characterizing'
                            ? '表征特征'
                            : '从属特征'}
                        </span>
                        {feat.source_paragraph_id && (
                          <span className="badge badge-neutral font-mono text-xs">
                            {feat.source_paragraph_id}
                          </span>
                        )}
                      </div>

                      <div className="flex-row gap-xs align-center">
                        {matchedDrawings.length > 0 ? (
                          matchedDrawings.map((d) => (
                            <button
                              key={d.id}
                              type="button"
                              className="btn btn-secondary btn-xs"
                              onClick={() => setPreviewDrawing(d)}
                              title={`查看 ${d.figure_label}: ${d.figure_title}`}
                            >
                              🖼️ {d.figure_label}
                            </button>
                          ))
                        ) : (
                          <button
                            type="button"
                            className="btn btn-link btn-xs text-secondary"
                            onClick={() => setShowAllDrawingsModal(true)}
                          >
                            🖼️ 附图对照
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Feature Statement Content */}
                    <div className="p-sm bg-subtle border rounded text-xs font-semibold text-text mb-md leading-relaxed">
                      {feat.feature_statement}
                    </div>

                    {/* Review Feedback Warning if requested changes */}
                    {hasFeedback && (
                      <div className="p-sm bg-yellow-50 border border-yellow-300 rounded text-xs text-warning mb-md flex-row gap-xs align-center">
                        <span>⚠️</span>
                        <span>
                          <strong>独立复核专家修改意见：</strong> {hasFeedback}
                        </span>
                      </div>
                    )}

                    {/* Candidate Comparisons Grid */}
                    <div className="grid-2-cols gap-md">
                      {matrixData.candidates.map((cand, cIdx) => {
                        const comp = matrixData.comparisons.find(
                          (item) =>
                            item.claim_feature_id === feat.id && item.candidate_id === cand.id
                        )
                        if (!comp) return null
                        const edit = editingCells[comp.id] || comp

                        return (
                          <div
                            key={cand.id}
                            className={`p-md border rounded flex-stack gap-sm ${
                              edit.judgment === 'identical'
                                ? 'border-red-300 bg-red-50'
                                : edit.judgment === 'equivalent'
                                ? 'border-yellow-300 bg-yellow-50'
                                : 'border-green-300 bg-green-50'
                            }`}
                          >
                            {/* Candidate Box Header */}
                            <div className="flex-between align-center border-b pb-xs">
                              <div className="flex-row gap-xs align-center">
                                <span className="badge badge-neutral font-mono font-bold text-xs">
                                  D{cIdx + 1}: {cand.publication_number}
                                </span>
                                {edit.is_manually_edited && (
                                  <span className="badge badge-warning text-xs">已人工修订</span>
                                )}
                              </div>

                              {!isConfirmed ? (
                                <select
                                  className="input-select btn-xs font-bold"
                                  value={edit.judgment}
                                  onChange={(e) =>
                                    setEditingCells({
                                      ...editingCells,
                                      [comp.id]: {
                                        ...edit,
                                        judgment: e.target.value as JudgmentType,
                                      },
                                    })
                                  }
                                >
                                  <option value="identical">🔴 相同 (完全公开)</option>
                                  <option value="equivalent">🟡 等同 (手段替换)</option>
                                  <option value="different">🟢 差异 (未公开)</option>
                                </select>
                              ) : (
                                <span
                                  className={`badge text-xs font-bold ${
                                    comp.judgment === 'identical'
                                      ? 'badge-danger'
                                      : comp.judgment === 'equivalent'
                                      ? 'badge-warning'
                                      : 'badge-success'
                                  }`}
                                >
                                  {comp.judgment === 'identical'
                                    ? '🔴 相同公开'
                                    : comp.judgment === 'equivalent'
                                    ? '🟡 等同替代'
                                    : '🟢 存在差异'}
                                </span>
                              )}
                            </div>

                            {/* Citation Location */}
                            <div className="form-group">
                              <label className="text-xs text-secondary font-semibold">
                                📍 对比文件引证位置 (Citation Location)
                              </label>
                              {!isConfirmed ? (
                                <input
                                  type="text"
                                  className="input-text text-xs font-mono"
                                  placeholder="例如：说明书第[0025]段 / 实施例3"
                                  value={edit.citation_location || ''}
                                  onChange={(e) =>
                                    setEditingCells({
                                      ...editingCells,
                                      [comp.id]: {
                                        ...edit,
                                        citation_location: e.target.value,
                                      },
                                    })
                                  }
                                />
                              ) : (
                                <div className="text-xs font-mono text-text bg-surface p-xs border rounded">
                                  {comp.citation_location || '全文'}
                                </div>
                              )}
                            </div>

                            {/* Citation Quote */}
                            <div className="form-group">
                              <label className="text-xs text-secondary font-semibold">
                                💬 对比文件引文摘录 (Citation Quote)
                              </label>
                              {!isConfirmed ? (
                                <input
                                  type="text"
                                  className="input-text text-xs"
                                  placeholder="粘贴对比文件中的对应技术描述..."
                                  value={edit.citation_quote || ''}
                                  onChange={(e) =>
                                    setEditingCells({
                                      ...editingCells,
                                      [comp.id]: {
                                        ...edit,
                                        citation_quote: e.target.value,
                                      },
                                    })
                                  }
                                />
                              ) : (
                                <div className="text-xs text-text bg-surface p-xs border rounded italic">
                                  “{comp.citation_quote || '无直接引述'}”
                                </div>
                              )}
                            </div>

                            {/* Reasoning Analysis */}
                            <div className="form-group">
                              <label className="text-xs text-secondary font-semibold">
                                ⚖️ 法律对比论述与技术特征差异 (Reasoning)
                              </label>
                              {!isConfirmed ? (
                                <textarea
                                  className="input-text text-xs"
                                  rows={3}
                                  value={edit.reasoning_analysis || ''}
                                  onChange={(e) =>
                                    setEditingCells({
                                      ...editingCells,
                                      [comp.id]: {
                                        ...edit,
                                        reasoning_analysis: e.target.value,
                                      },
                                    })
                                  }
                                  placeholder="详细阐述对比文件是否公开该特征，以及技术效果与手段差异..."
                                />
                              ) : (
                                <div className="text-xs text-text bg-surface p-xs border rounded leading-relaxed">
                                  {comp.reasoning_analysis || '未填写详细论据'}
                                </div>
                              )}
                            </div>

                            {!isConfirmed && (
                              <div className="flex-row justify-end mt-xs">
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-xs font-semibold"
                                  onClick={() => handleSaveCell(comp.id)}
                                  disabled={savingCellId === comp.id}
                                >
                                  {savingCellId === comp.id ? '保存中...' : '保存修改'}
                                </button>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ) : (
          <div className="card p-xl text-center">
            <h2 className="text-lg font-bold mb-sm">尚未生成权利要求特征比对表</h2>
            <p className="text-sm text-secondary mb-md">
              系统将根据已确认的技术特征集与候选池中纳入的对比文件，自动进行语义比对、三态判定与证据链构建。
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleGenerateMatrix}
              disabled={actionLoading}
            >
              {actionLoading ? '正在比对生成中...' : '⚡ 立即执行智能比对生成 Claim Chart'}
            </button>
          </div>
        )}

        {/* Drawing Preview Modal */}
        {previewDrawing && (
          <Modal
            isOpen={!!previewDrawing}
            title={`🖼️ 说明书附图图文对照: ${previewDrawing.figure_label}`}
            onClose={() => setPreviewDrawing(null)}
          >
            <div className="flex-stack gap-md">
              <div className="flex-between align-center">
                <div>
                  <h3 className="font-bold text-sm text-text">
                    {previewDrawing.figure_label}: {previewDrawing.figure_title}
                  </h3>
                  <span className="text-xs text-secondary font-mono">
                    所在页码: 第 {previewDrawing.page_number || '-'} 页 | 校验指纹: {previewDrawing.sha256.slice(0, 12)}...
                  </span>
                </div>
              </div>

              {previewDrawing.reference_marks && previewDrawing.reference_marks.length > 0 && (
                <div className="p-xs bg-subtle border rounded">
                  <span className="text-xs font-bold text-secondary block mb-xs">
                    附图附图标记清单 (Reference Marks):
                  </span>
                  <div className="flex-row gap-xs flex-wrap">
                    {previewDrawing.reference_marks.map((mark: any, mIdx) => (
                      <span key={mIdx} className="badge badge-neutral text-xs font-mono">
                        {typeof mark === 'string' ? mark : mark.name ? `${mark.mark} (${mark.name})` : mark.mark}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex-row justify-end">
                <button
                  type="button"
                  onClick={() => setPreviewDrawing(null)}
                  className="btn btn-primary btn-sm"
                >
                  关闭对照窗口
                </button>
              </div>
            </div>
          </Modal>
        )}

        {/* All Drawings Modal */}
        {showAllDrawingsModal && (
          <Modal
            isOpen={showAllDrawingsModal}
            title={`🖼️ 全案说明书附图清单 (${drawings.length} 幅)`}
            onClose={() => setShowAllDrawingsModal(false)}
          >
            <div className="flex-stack gap-md">
              <p className="text-xs text-secondary">
                点击任一附图卡片可查看其附图标记定义与说明书段落关联：
              </p>
              <div className="grid-2-cols gap-sm max-h-96 overflow-y-auto">
                {drawings.map((d) => (
                  <div
                    key={d.id}
                    className="p-sm border rounded bg-surface hover:bg-subtle cursor-pointer"
                    onClick={() => {
                      setShowAllDrawingsModal(false)
                      setPreviewDrawing(d)
                    }}
                  >
                    <div className="flex-between mb-xs">
                      <span className="badge badge-primary font-bold text-xs">{d.figure_label}</span>
                      <span className="text-xs text-muted">第 {d.page_number || '-'} 页</span>
                    </div>
                    <div className="text-xs font-semibold text-text mb-xs">{d.figure_title}</div>
                    {d.reference_marks && d.reference_marks.length > 0 && (
                      <div className="text-xs text-secondary truncate">
                        标记: {d.reference_marks.map((m: any) => typeof m === 'string' ? m : m.name ? `${m.mark}: ${m.name}` : m.mark).join(', ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="flex-row justify-end">
                <button
                  type="button"
                  onClick={() => setShowAllDrawingsModal(false)}
                  className="btn btn-secondary btn-sm"
                >
                  关闭
                </button>
              </div>
            </div>
          </Modal>
        )}
    </WorkbenchLayout>
  )
}
