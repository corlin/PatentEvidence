import React, { useCallback, useEffect, useState } from 'react'
import { apiClient, ApiError, isMfaRequired } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { StatusBadge } from '../components/StatusBadge'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type { ProductDescription, ProductFeature, ProductFeatureSet } from '../types/api'

interface Props {
  orgId: string
  caseId: string
}

const ORIGIN_LABEL: Record<ProductFeature['origin'], string> = {
  split: '规则拆分',
  edited: '已编辑',
  manual: '手工添加',
}

/**
 * 产品技术特征（ADR 0010）：自由文本描述 → 规则拆分候选特征 → 人工编辑与确认。
 * 拆分不调用任何大模型；确认后特征集不可修改，只能新建修订。
 */
export const ProductFeaturesWorkbenchView: React.FC<Props> = ({ orgId, caseId }) => {
  const { requestMfaStepUp } = useSession()
  const [descriptions, setDescriptions] = useState<ProductDescription[]>([])
  const [draftText, setDraftText] = useState('')
  const [featureSet, setFeatureSet] = useState<ProductFeatureSet | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [editing, setEditing] = useState<{ code: string; text: string } | null>(null)
  const [splitting, setSplitting] = useState<{ code: string; at: string } | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [newFeature, setNewFeature] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<ProductFeature | null>(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const handleError = useCallback(
    (err: unknown, fallback: string, retry?: () => void) => {
      if (err instanceof ApiError) {
        if (isMfaRequired(err) && retry) {
          requestMfaStepUp(retry)
          return
        }
        setError(err.detail || fallback)
      } else {
        setError(fallback)
      }
    },
    [requestMfaStepUp]
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [descs, sets] = await Promise.all([
        apiClient.listProductDescriptions(orgId, caseId),
        apiClient.listProductFeatureSets(orgId, caseId),
      ])
      setDescriptions(descs.items)
      setDraftText((current) => current || descs.items[0]?.text || '')
      if (sets.items.length > 0) {
        setFeatureSet(await apiClient.getProductFeatureSet(orgId, caseId, sets.items[0].id))
      } else {
        setFeatureSet(null)
      }
    } catch (err) {
      handleError(err, '加载产品技术特征失败', load)
    } finally {
      setLoading(false)
    }
  }, [orgId, caseId, handleError])

  useEffect(() => {
    load()
  }, [load])

  const run = async (action: () => Promise<ProductFeatureSet>, message: string) => {
    setBusy(true)
    setError(null)
    try {
      const updated = await action()
      setFeatureSet(updated)
      setSelected([])
      setSuccess(message)
      return updated
    } catch (err) {
      handleError(err, '操作失败')
      return null
    } finally {
      setBusy(false)
    }
  }

  const generate = async () => {
    if (!draftText.trim()) {
      setError('请先填写产品描述')
      return
    }
    const created = await run(async () => {
      const description = await apiClient.addProductDescription(orgId, caseId, draftText)
      return apiClient.createProductFeatureDraft(orgId, caseId, description.id)
    }, '已保存描述并生成候选特征，请逐项核对后确认')
    if (created) {
      setWarnings(created.warnings ?? [])
      const descs = await apiClient.listProductDescriptions(orgId, caseId)
      setDescriptions(descs.items)
    }
  }

  const isDraft = featureSet?.status === 'draft'
  const setId = featureSet?.id ?? ''

  const toggle = (code: string) =>
    setSelected((current) => (current.includes(code) ? current.filter((c) => c !== code) : [...current, code]))

  return (
    <WorkbenchLayout
      currentStep="product"
      orgId={orgId}
      caseId={caseId}
      title="产品技术特征"
      description="用自由文本描述产品，系统按规则拆分为候选特征，经人工核对并确认后用于 FTO 逐项比对"
      breadcrumbCurrent="产品技术特征"
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
    >
      <section className="card p-md mb-md" aria-labelledby="product-description-heading">
        <h2 id="product-description-heading" className="text-md font-bold mb-xs">
          产品描述
          {descriptions[0] && (
            <span className="text-xs text-secondary"> （当前第 {descriptions[0].version_number} 版）</span>
          )}
        </h2>
        <p className="text-xs text-secondary mb-sm">
          产品描述属于保密信息。拆分只使用确定性规则，不发送给任何大模型；每次保存都会生成新版本，旧版本保留。
        </p>
        <label htmlFor="product-description" className="sr-only">
          产品描述正文
        </label>
        <textarea
          id="product-description"
          className="input w-full"
          rows={8}
          value={draftText}
          onChange={(e) => setDraftText(e.target.value)}
          placeholder="例如：1. 液冷板由铝合金挤压成型……"
        />
        <div className="mt-sm">
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || loading} onClick={generate}>
            保存描述并生成候选特征
          </button>
        </div>
      </section>

      <section className="card p-md" aria-labelledby="product-features-heading">
        <div className="flex-between mb-sm">
          <h2 id="product-features-heading" className="text-md font-bold">
            技术特征
            {featureSet && <span className="text-xs text-secondary"> （第 {featureSet.version_number} 版）</span>}
          </h2>
          {featureSet && <StatusBadge status={featureSet.status} />}
        </div>

        {loading && <p className="text-secondary">加载中…</p>}
        {!loading && !featureSet && <p className="text-secondary">尚无特征。填写产品描述并生成候选特征。</p>}

        {warnings.length > 0 && isDraft && (
          <ul className="alert alert-warning mb-sm" aria-label="拆分提示">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}

        {featureSet && (
          <>
            <ol className="product-feature-list">
              {featureSet.features.map((feature) => (
                <li key={feature.code} className="border rounded p-sm mb-xs" data-testid={`feature-${feature.code}`}>
                  <div className="flex-between">
                    <label className="flex-row gap-xs align-center">
                      {isDraft && (
                        <input
                          type="checkbox"
                          aria-label={`选择 ${feature.code} 以合并`}
                          checked={selected.includes(feature.code)}
                          onChange={() => toggle(feature.code)}
                        />
                      )}
                      <strong>{feature.code}</strong>
                      <span className="badge text-xs">{ORIGIN_LABEL[feature.origin]}</span>
                    </label>
                    {isDraft && editing?.code !== feature.code && (
                      <div className="flex-row gap-xs">
                        <button type="button" className="btn btn-secondary btn-xs" onClick={() => setEditing({ code: feature.code, text: feature.text })}>
                          编辑
                        </button>
                        <button type="button" className="btn btn-secondary btn-xs" onClick={() => setSplitting({ code: feature.code, at: '' })}>
                          拆分
                        </button>
                        <button type="button" className="btn btn-secondary btn-xs" onClick={() => setDeleteTarget(feature)}>
                          删除
                        </button>
                      </div>
                    )}
                  </div>

                  {editing?.code === feature.code ? (
                    <div className="mt-xs">
                      <label htmlFor={`edit-${feature.code}`} className="sr-only">编辑 {feature.code}</label>
                      <textarea
                        id={`edit-${feature.code}`}
                        className="input w-full"
                        rows={3}
                        value={editing.text}
                        onChange={(e) => setEditing({ code: feature.code, text: e.target.value })}
                      />
                      <div className="flex-row gap-xs mt-xs">
                        <button
                          type="button"
                          className="btn btn-primary btn-xs"
                          disabled={busy}
                          onClick={async () => {
                            const done = await run(() => apiClient.editProductFeature(orgId, caseId, setId, feature.code, editing.text), `已更新 ${feature.code}`)
                            if (done) setEditing(null)
                          }}
                        >
                          保存
                        </button>
                        <button type="button" className="btn btn-secondary btn-xs" onClick={() => setEditing(null)}>
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-xs">{feature.text}</p>
                  )}

                  {splitting?.code === feature.code && (
                    <div className="flex-row gap-xs align-center mt-xs">
                      <label htmlFor={`split-${feature.code}`} className="text-xs">
                        在第几个字符后拆分（1–{feature.text.length - 1}）
                      </label>
                      <input
                        id={`split-${feature.code}`}
                        type="number"
                        min={1}
                        max={feature.text.length - 1}
                        className="input"
                        value={splitting.at}
                        onChange={(e) => setSplitting({ code: feature.code, at: e.target.value })}
                      />
                      <button
                        type="button"
                        className="btn btn-primary btn-xs"
                        disabled={busy || !splitting.at}
                        onClick={async () => {
                          const done = await run(
                            () => apiClient.splitProductFeature(orgId, caseId, setId, feature.code, Number(splitting.at)),
                            `已拆分 ${feature.code}`
                          )
                          if (done) setSplitting(null)
                        }}
                      >
                        确定拆分
                      </button>
                      <button type="button" className="btn btn-secondary btn-xs" onClick={() => setSplitting(null)}>
                        取消
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ol>

            {isDraft ? (
              <div className="mt-sm">
                <div className="flex-row gap-xs align-center mb-sm">
                  <label htmlFor="new-feature" className="sr-only">新增特征</label>
                  <input
                    id="new-feature"
                    className="input w-full"
                    placeholder="手工补充一个特征"
                    value={newFeature}
                    onChange={(e) => setNewFeature(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={busy || !newFeature.trim()}
                    onClick={async () => {
                      const done = await run(() => apiClient.addProductFeature(orgId, caseId, setId, newFeature), '已添加特征')
                      if (done) setNewFeature('')
                    }}
                  >
                    添加
                  </button>
                </div>
                <div className="flex-row gap-xs">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={busy || selected.length < 2}
                    onClick={() => run(() => apiClient.mergeProductFeatures(orgId, caseId, setId, selected), `已合并 ${selected.join('、')}`)}
                  >
                    合并所选（{selected.length}）
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={busy || featureSet.features.length === 0}
                    onClick={() => setShowConfirm(true)}
                  >
                    确认特征集
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-sm">
                <p className="text-xs text-secondary mb-xs">该特征集已确认，不可修改。如需调整，请创建修订版本。</p>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={busy}
                  onClick={() => run(() => apiClient.reviseProductFeatureSet(orgId, caseId, setId), '已创建修订草稿')}
                >
                  创建修订
                </button>
              </div>
            )}
          </>
        )}
      </section>

      <ConfirmDialog
        isOpen={deleteTarget !== null}
        title="删除该特征？"
        danger
        confirmLabel="确认删除"
        loading={busy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return
          const done = await run(() => apiClient.deleteProductFeature(orgId, caseId, setId, deleteTarget.code), `已删除 ${deleteTarget.code}`)
          if (done) setDeleteTarget(null)
        }}
      >
        <p>
          将从草稿中删除 <strong>{deleteTarget?.code}</strong>。
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        isOpen={showConfirm}
        title="确认产品技术特征集？"
        danger
        confirmLabel="确认并锁定"
        loading={busy}
        onCancel={() => setShowConfirm(false)}
        onConfirm={async () => {
          const done = await run(() => apiClient.confirmProductFeatureSet(orgId, caseId, setId), '特征集已确认并锁定')
          if (done) setShowConfirm(false)
        }}
      >
        <p>
          确认后，该特征集及其 {featureSet?.features.length ?? 0} 个特征将不可修改、不可删除，并作为 FTO 比对的依据。之后如需调整，只能创建修订版本。
        </p>
      </ConfirmDialog>
    </WorkbenchLayout>
  )
}
