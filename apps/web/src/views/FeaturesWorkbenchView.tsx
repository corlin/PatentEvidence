import React, { useEffect, useState } from 'react'
import { Icon } from '../components/Icon'
import { apiClient, ApiError, isMfaRequired } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { ClaimFeature, FeatureSetDetail, FeatureType } from '../types/api'
import { Link, useNavigate } from '../router/Router'

interface FeaturesWorkbenchViewProps {
  orgId: string
  caseId: string
}

export const FeaturesWorkbenchView: React.FC<FeaturesWorkbenchViewProps> = ({ orgId, caseId }) => {
  const { requestMfaStepUp } = useSession()
  const navigate = useNavigate()

  const [featureSet, setFeatureSet] = useState<FeatureSetDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Editing state
  const [editingFeatures, setEditingFeatures] = useState<Record<string, ClaimFeature>>({})
  const [savingFeatureId, setSavingFeatureId] = useState<string | null>(null)

  // Modals
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [addForm, setAddForm] = useState({
    feature_code: '',
    feature_type: 'characterizing' as FeatureType,
    feature_statement: '',
    source_paragraph_id: '',
    citation_quote: '',
  })

  const [isSplitModalOpen, setIsSplitModalOpen] = useState(false)
  const [splitTarget, setSplitTarget] = useState<ClaimFeature | null>(null)
  const [splitForm, setSplitForm] = useState({ part1: '', part2: '' })

  const [isMergeModalOpen, setIsMergeModalOpen] = useState(false)
  const [mergeTarget1, setMergeTarget1] = useState<ClaimFeature | null>(null)
  const [mergeTarget2Id, setMergeTarget2Id] = useState<string>('')
  const [mergedStatement, setMergedStatement] = useState('')

  const [actionLoading, setActionLoading] = useState(false)
  // P0：确认特征版本为不可变基准前，必须显式二次确认
  const [showConfirmVersion, setShowConfirmVersion] = useState(false)
  // Sprint 1：删除特征改用品牌确认对话框
  const [deleteFeatureTarget, setDeleteFeatureTarget] = useState<ClaimFeature | null>(null)

  const fetchActiveFeatures = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiClient.getActiveFeatures(orgId, caseId)
      setFeatureSet(data)
      const mapped: Record<string, ClaimFeature> = {}
      for (const f of data.features) {
        mapped[f.id] = { ...f }
      }
      setEditingFeatures(mapped)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 404) {
        setFeatureSet(null)
      } else if (isMfaRequired(err)) {
        requestMfaStepUp(fetchActiveFeatures)
      } else {
        setError(err.detail || '加载技术特征失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchActiveFeatures()
  }, [orgId, caseId])

  const handleExtractDraft = async () => {
    setActionLoading(true)
    setError(null)
    setSuccess(null)
    try {
      const res = await apiClient.extractFeatures(orgId, caseId)
      setFeatureSet(res)
      setSuccess('技术特征草稿提取成功！请在下方进行审查与修订。')
      fetchActiveFeatures()
    } catch (err: any) {
      setError(err.detail || '特征提取失败，请确保已上传并确认交底书文档')
    } finally {
      setActionLoading(false)
    }
  }

  const handleConfirmVersion = async () => {
    if (!featureSet) return
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.confirmFeatureVersion(orgId, caseId, featureSet.version.id)
      setFeatureSet(res)
      setShowConfirmVersion(false)
      setSuccess('技术特征版本已确认并锁定为不可变基准！案件状态已推进为【特征已确认】。')
    } catch (err: any) {
      setError(err.detail || '确认特征版本失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleCreateRevision = async () => {
    if (!featureSet) return
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.createFeatureRevision(orgId, caseId, featureSet.version.id)
      setFeatureSet(res)
      setSuccess(`已创建新修订草稿版本 (v${res.version.version_number})！`)
      fetchActiveFeatures()
    } catch (err: any) {
      setError(err.detail || '创建修订版本失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSaveFeature = async (featureId: string) => {
    const feat = editingFeatures[featureId]
    if (!feat || !featureSet) return

    setSavingFeatureId(featureId)
    setError(null)
    try {
      const res = await apiClient.updateFeatureItem(orgId, caseId, featureSet.version.id, featureId, {
        feature_code: feat.feature_code,
        feature_type: feat.feature_type,
        feature_statement: feat.feature_statement,
        source_paragraph_id: feat.source_paragraph_id,
        citation_quote: feat.citation_quote,
      })
      setFeatureSet(res)
      setSuccess(`特征 ${feat.feature_code} 保存成功`)
    } catch (err: any) {
      setError(err.detail || '保存特征失败')
    } finally {
      setSavingFeatureId(null)
    }
  }

  const handleDeleteFeature = async (featureId: string) => {
    if (!featureSet) return

    setActionLoading(true)
    try {
      const res = await apiClient.deleteFeatureItem(orgId, caseId, featureSet.version.id, featureId)
      setFeatureSet(res)
      setSuccess('特征已成功删除')
      fetchActiveFeatures()
    } catch (err: any) {
      setError(err.detail || '删除特征失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!featureSet) return
    setActionLoading(true)
    try {
      const res = await apiClient.addFeatureItem(orgId, caseId, featureSet.version.id, addForm)
      setFeatureSet(res)
      setIsAddModalOpen(false)
      setAddForm({
        feature_code: '',
        feature_type: 'characterizing',
        feature_statement: '',
        source_paragraph_id: '',
        citation_quote: '',
      })
      setSuccess('新增特征成功！')
      fetchActiveFeatures()
    } catch (err: any) {
      setError(err.detail || '添加特征失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSplitSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!featureSet || !splitTarget) return
    setActionLoading(true)
    try {
      const res = await apiClient.splitFeatureItem(
        orgId,
        caseId,
        featureSet.version.id,
        splitTarget.id,
        splitForm.part1,
        splitForm.part2
      )
      setFeatureSet(res)
      setIsSplitModalOpen(false)
      setSuccess(`特征 ${splitTarget.feature_code} 拆分成功！`)
      fetchActiveFeatures()
    } catch (err: any) {
      setError(err.detail || '拆分特征失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleMergeSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!featureSet || !mergeTarget1 || !mergeTarget2Id) return
    setActionLoading(true)
    try {
      const res = await apiClient.mergeFeatureItems(
        orgId,
        caseId,
        featureSet.version.id,
        mergeTarget1.id,
        mergeTarget2Id,
        mergedStatement
      )
      setFeatureSet(res)
      setIsMergeModalOpen(false)
      setSuccess('特征合并成功！')
      fetchActiveFeatures()
    } catch (err: any) {
      setError(err.detail || '合并特征失败')
    } finally {
      setActionLoading(false)
    }
  }

  const isDraft = featureSet?.version.status === 'draft'

  return (
    <WorkbenchLayout
      currentStep="features"
      caseStatus={featureSet?.version.status === 'confirmed' ? 'evidence_ready' : 'document_ready'}
      orgId={orgId}
      caseId={caseId}
      title="技术特征提取与版本确认"
      description="对交底书进行权利要求级特征拆解、原文段落引文锚定与基准版本锁定"
      breadcrumbCurrent="技术特征建模"
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
      headerActions={
        <>
          {featureSet?.version.status === 'confirmed' && (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/search`}
              className="btn btn-primary btn-sm font-bold"
            >
              <Icon name="search" size={14} /> 前往检索工作台 &rarr;
            </Link>
          )}
          <Link to={`/organizations/${orgId}/cases/${caseId}`} className="btn btn-secondary btn-sm">
            &larr; 返回案件主页
          </Link>
        </>
      }
    >

        {/* Version Status Card */}
        {featureSet ? (
          <div className="card p-md mb-md flex-between">
            <div>
              <div className="flex-row gap-sm mb-xs">
                <span className="text-md font-bold">
                  特征版本：v{featureSet.version.version_number}
                </span>
                <StatusBadge status={featureSet.version.status} />
                {featureSet.version.parent_version_id && (
                  <span className="text-xs text-secondary">
                    (派生自父版本: {featureSet.version.parent_version_id.substring(0, 8)})
                  </span>
                )}
              </div>
              <p className="text-xs text-secondary">
                {isDraft
                  ? '当前处于草稿编辑期。支持行内修改、拆分、合并与新增。'
                  : `该版本已由代理师锁定确认 (${new Date(featureSet.version.confirmed_at || '').toLocaleString()})。`}
              </p>
            </div>

            <div className="flex-row gap-sm">
              {isDraft ? (
                <>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleExtractDraft}
                    disabled={actionLoading}
                  >
                    重新从交底书提取
                  </button>
                  <button
                    type="button"
                    className="btn btn-success btn-sm"
                    onClick={() => setShowConfirmVersion(true)}
                    disabled={actionLoading || featureSet.features.length === 0}
                  >
                    ✓ 确认并锁定特征版本
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleCreateRevision}
                  disabled={actionLoading}
                >
                  + 基于此版本创建新修订版
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="card p-xl text-center mb-md">
            <h2 className="text-lg font-bold mb-sm">尚未生成技术特征集</h2>
            <p className="text-sm text-secondary mb-md">
              系统可根据已解析的交底书文本段落，智能识别前序特征、主体技术方案与实施步骤。
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleExtractDraft}
              disabled={actionLoading}
            >
              {actionLoading ? '正在提取特征...' : '自动提取技术特征草稿'}
            </button>
          </div>
        )}

        {/* Features List Section */}
        {featureSet && (
          <div className="features-section">
            <div className="flex-between mb-sm">
              <h2 className="text-lg font-bold">特征清单 ({featureSet.features.length})</h2>
              {isDraft && (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => setIsAddModalOpen(true)}
                >
                  + 新增自定义特征
                </button>
              )}
            </div>

            <div className="flex-stack gap-md">
              {featureSet.features.map((f, idx) => {
                const edit = editingFeatures[f.id] || f
                return (
                  <div key={f.id} className="card p-md border rounded bg-surface feature-card">
                    <div className="flex-between mb-sm">
                      <div className="flex-row gap-sm">
                        <span className="badge badge-neutral font-mono font-bold">{f.feature_code}</span>
                        {isDraft ? (
                          <select
                            className="input-select btn-xs"
                            value={edit.feature_type}
                            onChange={(e) =>
                              setEditingFeatures({
                                ...editingFeatures,
                                [f.id]: { ...edit, feature_type: e.target.value as FeatureType },
                              })
                            }
                          >
                            <option value="preamble">前序特征 (Preamble)</option>
                            <option value="characterizing">表征特征 (Characterizing)</option>
                            <option value="dependent">从属特征 (Dependent)</option>
                          </select>
                        ) : (
                          <span className="badge badge-neutral text-xs">
                            {f.feature_type === 'preamble'
                              ? '前序特征'
                              : f.feature_type === 'characterizing'
                              ? '表征特征'
                              : '从属特征'}
                          </span>
                        )}

                        {f.source_paragraph_id && (
                          <span className="badge badge-neutral font-mono text-xs">
                            段落: {f.source_paragraph_id}
                          </span>
                        )}
                      </div>

                      {isDraft && (
                        <div className="actions flex-row gap-xs">
                          <button
                            type="button"
                            className="btn btn-secondary btn-xs"
                            onClick={() => {
                              setSplitTarget(f)
                              setSplitForm({
                                part1: f.feature_statement.substring(0, Math.floor(f.feature_statement.length / 2)),
                                part2: f.feature_statement.substring(Math.floor(f.feature_statement.length / 2)),
                              })
                              setIsSplitModalOpen(true)
                            }}
                          >
                            拆分
                          </button>
                          {featureSet.features.length > 1 && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-xs"
                              onClick={() => {
                                setMergeTarget1(f)
                                const other = featureSet.features.find((item) => item.id !== f.id)
                                setMergeTarget2Id(other ? other.id : '')
                                setMergedStatement(
                                  other
                                    ? `${f.feature_statement}；${other.feature_statement}`
                                    : f.feature_statement
                                )
                                setIsMergeModalOpen(true)
                              }}
                            >
                              合并
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-danger btn-xs"
                            onClick={() => setDeleteFeatureTarget(f)}
                          >
                            删除
                          </button>
                          <button
                            type="button"
                            className="btn btn-success btn-xs"
                            onClick={() => handleSaveFeature(f.id)}
                            disabled={savingFeatureId === f.id}
                          >
                            {savingFeatureId === f.id ? '保存中...' : '保存'}
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Feature Statement */}
                    {isDraft ? (
                      <textarea
                        className="input-text mb-sm"
                        rows={3}
                        value={edit.feature_statement}
                        onChange={(e) =>
                          setEditingFeatures({
                            ...editingFeatures,
                            [f.id]: { ...edit, feature_statement: e.target.value },
                          })
                        }
                      />
                    ) : (
                      <p className="text-sm font-medium mb-sm">{f.feature_statement}</p>
                    )}

                    {/* Citation Quote */}
                    {f.citation_quote && (
                      <div className="citation-quote p-xs border rounded bg-subtle text-xs text-secondary">
                        <span className="font-semibold text-text mr-xs">原文引文：</span>
                        <em>“{f.citation_quote}”</em>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

      {/* Add Feature Modal */}
      <Modal isOpen={isAddModalOpen} title="新增自定义技术特征" onClose={() => setIsAddModalOpen(false)}>
        <form onSubmit={handleAddSubmit} className="form-stack">
          <div className="grid-2-cols gap-sm">
            <div className="form-group">
              <label className="form-label">特征编号</label>
              <input
                type="text"
                className="input-text"
                value={addForm.feature_code}
                onChange={(e) => setAddForm({ ...addForm, feature_code: e.target.value })}
                placeholder={`例如：F${(featureSet?.features.length || 0) + 1}`}
              />
            </div>
            <div className="form-group">
              <label className="form-label">特征类型</label>
              <select
                className="input-select"
                value={addForm.feature_type}
                onChange={(e) =>
                  setAddForm({ ...addForm, feature_type: e.target.value as FeatureType })
                }
              >
                <option value="preamble">前序特征</option>
                <option value="characterizing">表征特征</option>
                <option value="dependent">从属特征</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">技术特征陈述</label>
            <textarea
              className="input-text"
              rows={3}
              value={addForm.feature_statement}
              onChange={(e) => setAddForm({ ...addForm, feature_statement: e.target.value })}
              placeholder="清晰描述该技术特征的具体方案..."
              required
            />
          </div>

          <div className="grid-2-cols gap-sm">
            <div className="form-group">
              <label className="form-label">关联段落编号</label>
              <input
                type="text"
                className="input-text"
                value={addForm.source_paragraph_id}
                onChange={(e) => setAddForm({ ...addForm, source_paragraph_id: e.target.value })}
                placeholder="例如：p3"
              />
            </div>
            <div className="form-group">
              <label className="form-label">原文引文片段</label>
              <input
                type="text"
                className="input-text"
                value={addForm.citation_quote}
                onChange={(e) => setAddForm({ ...addForm, citation_quote: e.target.value })}
                placeholder="引文截取..."
              />
            </div>
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsAddModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={actionLoading}>
              确认添加
            </button>
          </div>
        </form>
      </Modal>

      {/* Split Feature Modal */}
      <Modal isOpen={isSplitModalOpen} title="拆分技术特征" onClose={() => setIsSplitModalOpen(false)}>
        <form onSubmit={handleSplitSubmit} className="form-stack">
          <p className="text-xs text-secondary mb-xs">
            将特征 <strong>{splitTarget?.feature_code}</strong> 拆分为两个更具颗粒度的子特征：
          </p>

          <div className="form-group">
            <label className="form-label">前半部分特征陈述</label>
            <textarea
              className="input-text"
              rows={2}
              value={splitForm.part1}
              onChange={(e) => setSplitForm({ ...splitForm, part1: e.target.value })}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">后半部分特征陈述</label>
            <textarea
              className="input-text"
              rows={2}
              value={splitForm.part2}
              onChange={(e) => setSplitForm({ ...splitForm, part2: e.target.value })}
              required
            />
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsSplitModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={actionLoading}>
              确认拆分
            </button>
          </div>
        </form>
      </Modal>

      {/* Merge Feature Modal */}
      <Modal isOpen={isMergeModalOpen} title="合并技术特征" onClose={() => setIsMergeModalOpen(false)}>
        <form onSubmit={handleMergeSubmit} className="form-stack">
          <p className="text-xs text-secondary mb-xs">
            将特征 <strong>{mergeTarget1?.feature_code}</strong> 与另一特征合并为单一特征：
          </p>

          <div className="form-group">
            <label className="form-label">合并目标特征</label>
            <select
              className="input-select"
              value={mergeTarget2Id}
              onChange={(e) => {
                const targetId = e.target.value
                setMergeTarget2Id(targetId)
                const other = featureSet?.features.find((item) => item.id === targetId)
                if (mergeTarget1 && other) {
                  setMergedStatement(`${mergeTarget1.feature_statement}；${other.feature_statement}`)
                }
              }}
              required
            >
              <option value="">-- 请选择要合并的特征 --</option>
              {featureSet?.features
                .filter((f) => f.id !== mergeTarget1?.id)
                .map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.feature_code}: {f.feature_statement.substring(0, 40)}...
                  </option>
                ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">合并后的特征陈述</label>
            <textarea
              className="input-text"
              rows={3}
              value={mergedStatement}
              onChange={(e) => setMergedStatement(e.target.value)}
              required
            />
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsMergeModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={actionLoading}>
              确认合并
            </button>
          </div>
        </form>
      </Modal>

      {/* P0：删除特征的品牌确认对话框 */}
      <ConfirmDialog
        isOpen={deleteFeatureTarget !== null}
        title="删除该技术特征？"
        danger
        confirmLabel="确认删除"
        loading={actionLoading}
        onCancel={() => setDeleteFeatureTarget(null)}
        onConfirm={() => deleteFeatureTarget && handleDeleteFeature(deleteFeatureTarget.id)}
      >
        <p>
          将从当前版本中删除特征
          <strong> {deleteFeatureTarget?.feature_code ?? ''} </strong>
          （{deleteFeatureTarget?.feature_statement?.slice(0, 60) ?? ''}
          {deleteFeatureTarget?.feature_statement && deleteFeatureTarget.feature_statement.length > 60 ? '…' : ''}
          ）。此操作不可撤销。
        </p>
      </ConfirmDialog>

      {/* P0：确认特征版本的不可变基准二次确认 */}
      <ConfirmDialog
        isOpen={showConfirmVersion}
        title="确认并锁定特征版本为不可变基准？"
        danger
        confirmLabel="确认锁定该版本"
        loading={actionLoading}
        onCancel={() => setShowConfirmVersion(false)}
        onConfirm={handleConfirmVersion}
      >
        <p>
          确认后，特征版本 <strong>v{featureSet?.version.version_number}</strong>{' '}
          将被锁定为不可变基准版本，案件状态推进为【特征已确认】。
        </p>
        <p className="text-xs text-secondary mt-xs">
          此操作<b>不可撤销</b>：后续修改需创建新修订版，原版本的 SHA-256 哈希记录将永久保留。
        </p>
      </ConfirmDialog>
    </WorkbenchLayout>
  )
}
