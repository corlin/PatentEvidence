import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { AssessmentInputPanel } from '../components/AssessmentInputPanel'
import { AssessmentReviewPanel } from '../components/AssessmentReviewPanel'
import { AssessmentDiffPanel } from '../components/AssessmentDiffPanel'
import type {
  AssessmentDeliverable,
  AssessmentInputSnapshot,
  AssessmentVersionDetail,
  AssessmentVersionStatus,
  AssessmentVersionSummary,
  CaseDetail,
} from '../types/api'

interface AssessmentWorkbenchViewProps {
  orgId: string
  caseId: string
}

/** 后端未返回 disclaimer 时的兜底文案，保证横幅在任何情况下都出现。 */
const FALLBACK_DISCLAIMER =
  '本评估仅输出候选发现与阻塞项，不构成专利性结论或法律意见；任何结论须经人工复核确认后方可对外使用。'

/**
 * 状态标记不写「已批准」——那会被读成「具备专利性」。写成「复核通过」并把
 * 限定语固定挂在旁边：通过的是这个候选评估包，不是方案本身。
 */
const STATUS_META: Record<string, { label: string; className: string; note: string }> = {
  draft: { label: '草稿', className: 'badge badge-neutral', note: '尚未提交复核。' },
  submitted: { label: '待复核', className: 'badge badge-warning', note: '等待复核人作出决定。' },
  approved: {
    label: '复核通过',
    className: 'badge badge-success',
    note: '仅表示本候选评估包通过内部复核，不代表该方案具备专利性或可授权。',
  },
  rejected: {
    label: '复核未通过',
    className: 'badge badge-danger',
    note: '本候选评估包未通过内部复核，不等于该方案不具备专利性。',
  },
}

const RISK_KIND_LABEL: Record<string, string> = {
  novelty: '新颖性',
  inventive_combination: '创造性（组合）',
  evidence_completeness: '证据完备度',
}

const LEVEL_LABEL: Record<string, string> = {
  high_novelty_risk: '新颖性高风险',
  high_inventive_risk: '创造性高风险',
  needs_confirmation: '须人工确认',
  low: '低',
}

function statusMeta(status: AssessmentVersionStatus | null | undefined) {
  if (!status) return { label: '草稿', className: 'badge badge-neutral', note: '尚未提交复核。' }
  return STATUS_META[status] || { label: status, className: 'badge badge-neutral', note: '' }
}

export const AssessmentWorkbenchView: React.FC<AssessmentWorkbenchViewProps> = ({
  orgId,
  caseId,
}) => {
  const [currentCase, setCurrentCase] = useState<CaseDetail | null>(null)
  const [versions, setVersions] = useState<AssessmentVersionSummary[]>([])
  const [detail, setDetail] = useState<AssessmentVersionDetail | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  // 版本冻结时的输入档案快照：老版本可能无快照（null），此时诚实展示、不做推断
  const [inputSnapshot, setInputSnapshot] = useState<AssessmentInputSnapshot | null>(null)

  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 只读版本区与输入准备区分开：写操作不混入「不可改写」的版本区
  const [tab, setTab] = useState<'versions' | 'prepare' | 'review'>('versions')

  // 导出预评估意见（候选，非结论）：独立模态，不污染只读版本区
  const [deliverable, setDeliverable] = useState<AssessmentDeliverable | null>(null)
  const [deliverableLoading, setDeliverableLoading] = useState(false)
  const [showDeliverable, setShowDeliverable] = useState(false)

  const openDeliverable = async (versionNumber: number) => {
    setDeliverableLoading(true)
    try {
      const res = await apiClient.getAssessmentDeliverable(orgId, caseId, versionNumber)
      setDeliverable(res.deliverable)
      setShowDeliverable(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导出预评估意见失败')
    } finally {
      setDeliverableLoading(false)
    }
  }

  const loadVersions = async () => {
    setLoading(true)
    setError(null)
    try {
      const [cRes, listRes] = await Promise.all([
        apiClient.getCase(orgId, caseId).catch(() => null),
        apiClient.listAssessmentVersions(orgId, caseId).catch(() => ({ items: [] })),
      ])
      setCurrentCase(cRes)
      const items = listRes.items || []
      setVersions(items)
      // 默认选中版本号最大的一份（列表按版本号倒序返回）
      setSelectedVersion(items.length > 0 ? items[0].version_number : null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载评估版本失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadVersions()
  }, [orgId, caseId])

  useEffect(() => {
    if (selectedVersion === null) {
      setDetail(null)
      setInputSnapshot(null)
      return
    }
    let cancelled = false
    const loadDetail = async () => {
      setDetailLoading(true)
      setError(null)
      try {
        const [versionRes, snapshotRes] = await Promise.all([
          apiClient.getAssessmentVersion(orgId, caseId, selectedVersion),
          // 快照拉取失败或不存在时诚实降级为 null，不回读可变档案表推断
          apiClient
            .getAssessmentInputSnapshot(orgId, caseId, selectedVersion)
            .catch(() => ({ snapshot: null })),
        ])
        if (!cancelled) {
          setDetail(versionRes.version)
          setInputSnapshot(snapshotRes.snapshot)
        }
      } catch (err) {
        if (!cancelled) {
          setDetail(null)
          setInputSnapshot(null)
          setError(err instanceof ApiError ? err.message : '加载评估版本详情失败')
        }
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    }
    loadDetail()
    return () => {
      cancelled = true
    }
  }, [orgId, caseId, selectedVersion])

  const disclaimer = detail?.disclaimer || FALLBACK_DISCLAIMER
  const payload = detail?.payload

  return (
    <WorkbenchLayout
      currentStep="comparisons"
      caseStatus={currentCase?.status}
      orgId={orgId}
      caseId={caseId}
      title="可专利性预评估（候选输出，非结论）"
      description="确定性门禁跑出的候选发现与阻塞项。修订只会产生新版本号，已有版本不可改写。"
      breadcrumbCurrent="预评估"
      error={error}
      onErrorClose={() => setError(null)}
    >
      {/* 常驻免责横幅：不可关闭，先于任何内容出现 */}
      <div className="alert alert-warning mb-md">
        <div className="alert-content">
          <strong>这不是专利性结论。</strong> {disclaimer}
        </div>
      </div>

      <div className="card p-sm mb-md">
        <div className="flex-row gap-sm">
          <button
            type="button"
            className={tab === 'versions' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
            onClick={() => setTab('versions')}
          >
            版本（只读）
          </button>
          <button
            type="button"
            className={tab === 'prepare' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
            onClick={() => setTab('prepare')}
          >
            准备输入
          </button>
          <button
            type="button"
            className={tab === 'review' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
            onClick={() => setTab('review')}
          >
            复核
          </button>
        </div>
      </div>

      {tab === 'review' ? (
        <AssessmentReviewPanel orgId={orgId} caseId={caseId} detail={detail} onDecided={loadVersions} />
      ) : tab === 'prepare' ? (
        <AssessmentInputPanel
          orgId={orgId}
          caseId={caseId}
          onAssembled={(res) => {
            setVersions((prev) => [res.version, ...prev.filter((v) => v.version_number !== res.version.version_number)])
            setSelectedVersion(res.version.version_number)
          }}
        />
      ) : loading ? (
        <div className="card p-lg text-secondary text-sm">正在加载评估版本...</div>
      ) : versions.length === 0 ? (
        <div className="card p-lg">
          <p className="text-sm text-secondary">
            该案件尚无预评估版本。可先在「准备输入」登记本案申请日与对比文件日期，
            再依据案件既有数据生成；版本一旦生成即冻结，页面不提供手工编辑或删除。
          </p>
        </div>
      ) : (
        <>
          <div className="card p-md mb-md">
            <h2 className="text-base font-bold mb-sm">版本列表（只读）</h2>
            <div className="flex-row flex-wrap gap-sm">
              {versions.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={
                    item.version_number === selectedVersion ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'
                  }
                  onClick={() => setSelectedVersion(item.version_number)}
                >
                  版本 {item.version_number}
                  {item.blockers.length > 0 && ` · ${item.blockers.length} 项阻塞`}
                </button>
              ))}
            </div>
          </div>

          {detailLoading && (
            <div className="card p-md mb-md text-secondary text-sm">正在加载版本详情...</div>
          )}

          {detail && !detailLoading && (
            <>
              <div className="card p-md mb-md">
                <div className="flex-between mb-sm">
                  <h2 className="text-base font-bold">版本 {detail.version_number} 概览</h2>
                  <div className="flex-row gap-sm">
                    <span className={statusMeta(detail.status).className}>
                      {statusMeta(detail.status).label}
                    </span>
                    {detail.requires_human_confirmation && (
                      <span className="badge badge-danger">须人工确认</span>
                    )}
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={deliverableLoading}
                      onClick={() => openDeliverable(detail.version_number)}
                    >
                      {deliverableLoading ? '导出中…' : '导出预评估意见'}
                    </button>
                  </div>
                </div>
                <div className="grid-2-cols text-sm">
                  <div>
                    <span className="text-secondary">规则版本：</span>
                    <span className="font-mono">{detail.rules_version}</span>
                  </div>
                  <div>
                    <span className="text-secondary">提示词版本：</span>
                    <span className="font-mono">
                      {Object.entries(detail.prompt_versions || {})
                        .map(([k, v]) => `${k} ${v}`)
                        .join(' · ') || '—'}
                    </span>
                  </div>
                  <div className="break-all">
                    <span className="text-secondary">包摘要：</span>
                    <span className="font-mono text-xs">{detail.payload_sha256}</span>
                  </div>
                  <div>
                    <span className="text-secondary">生成时间：</span>
                    {new Date(detail.created_at).toLocaleString('zh-CN')}
                  </div>
                </div>
                <p className="text-sm text-secondary mt-sm">{statusMeta(detail.status).note}</p>
              </div>

              {/* 冻结输入快照：版本创建时一并冻结的输入档案；老版本无快照时诚实展示，不做推断 */}
              <div className="card p-md mb-md">
                <h2 className="text-base font-bold mb-sm">冻结输入快照（只读）</h2>
                {inputSnapshot ? (
                  <>
                    <div className="grid-2-cols text-sm mb-sm">
                      <div>
                        <span className="text-secondary">本案申请日：</span>
                        {inputSnapshot.application_profile.filing_date || '—'}
                      </div>
                      <div>
                        <span className="text-secondary">申请类型：</span>
                        {inputSnapshot.application_profile.application_type || '—'}
                      </div>
                    </div>

                    {inputSnapshot.application_profile.priority_claims.length > 0 && (
                      <div className="mb-sm">
                        <h3 className="text-sm font-bold mb-xs">优先权主张</h3>
                        <table className="data-table w-full text-sm">
                          <thead>
                            <tr>
                              <th>主张</th>
                              <th>优先权日</th>
                              <th>国家/地区</th>
                              <th>首次申请</th>
                              <th>相同主题</th>
                              <th>证明已核验</th>
                              <th>覆盖</th>
                            </tr>
                          </thead>
                          <tbody>
                            {inputSnapshot.application_profile.priority_claims.map((claim) => (
                              <tr key={claim.claim_id}>
                                <td className="font-mono text-xs">{claim.claim_id}</td>
                                <td>{claim.priority_date || '—'}</td>
                                <td>{claim.country}</td>
                                <td>{claim.first_application ? '是' : '否'}</td>
                                <td>{claim.same_subject ? '是' : '否'}</td>
                                <td>{claim.proof_verified ? '是' : '否'}</td>
                                <td className="font-mono text-xs">{claim.covers.join(', ') || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    <h3 className="text-sm font-bold mb-xs">对比文件档案</h3>
                    {inputSnapshot.candidate_profiles.length > 0 ? (
                      <table className="data-table w-full text-sm">
                        <thead>
                          <tr>
                            <th>公开号</th>
                            <th>申请日</th>
                            <th>优先权日</th>
                            <th>中国申请</th>
                            <th>来源已核验</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inputSnapshot.candidate_profiles.map((doc, idx) => (
                            <tr key={`${doc.publication_number}-${idx}`}>
                              <td className="font-mono text-xs">{doc.publication_number}</td>
                              <td>{doc.filing_date || '—'}</td>
                              <td>{doc.priority_date || '—'}</td>
                              <td>{doc.filed_in_china ? '是' : '否'}</td>
                              <td>
                                {doc.source_verified ? (
                                  <span className="badge badge-success">已核验</span>
                                ) : (
                                  <span className="badge badge-warning">未核验</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <p className="text-sm text-secondary">快照中无对比文件档案。</p>
                    )}
                    <p className="text-xs text-secondary mt-sm">
                      以上为版本 v{detail.version_number} 创建时冻结的输入档案，此后档案表若被修改
                      不会反映在此处；版本间输入变化请以版本对比为准。
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-secondary">
                    本版本创建于输入快照功能上线之前，无冻结快照；此处不回读可变档案表做推断。
                    如需对照输入，请以之后创建的版本为基准。
                  </p>
                )}
              </div>

              <AssessmentDiffPanel
                orgId={orgId}
                caseId={caseId}
                versionNumber={detail.version_number}
                versionNumbers={versions.map((item) => item.version_number)}
              />

              {/* 阻塞项：标题必须说清「因此当前没有结论」 */}
              <div className="card p-md mb-md">
                <h2 className="text-base font-bold mb-sm">
                  尚未解决的阻塞项（因此本版本不能给出结论）
                </h2>
                {payload && payload.blockers.length > 0 ? (
                  <ul className="text-sm">
                    {payload.blockers.map((item, idx) => (
                      <li key={idx} className="mb-xs">
                        <span className="badge badge-danger">阻塞</span> {item}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-secondary">本版本无阻塞项。</p>
                )}
              </div>

              {payload && payload.flags.length > 0 && (
                <div className="card p-md mb-md">
                  <h2 className="text-base font-bold mb-sm">提示项</h2>
                  <ul className="text-sm">
                    {payload.flags.map((item, idx) => (
                      <li key={idx} className="mb-xs">
                        <span className="badge badge-warning">提示</span> {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {payload && (
                <div className="card p-md mb-md">
                  <h2 className="text-base font-bold mb-sm">候选发现（须人工确认）</h2>
                  {payload.findings.length === 0 ? (
                    <p className="text-sm text-secondary">本版本未产生候选发现。</p>
                  ) : (
                    <table className="data-table w-full text-sm">
                      <thead>
                        <tr>
                          <th>类别</th>
                          <th>等级</th>
                          <th>说明</th>
                          <th>人工确认</th>
                        </tr>
                      </thead>
                      <tbody>
                        {payload.findings.map((finding, idx) => (
                          <tr key={idx}>
                            <td>{RISK_KIND_LABEL[finding.risk_kind] || finding.risk_kind}</td>
                            <td>
                              <StatusBadge
                                status={finding.level}
                                label={LEVEL_LABEL[finding.level] || finding.level}
                              />
                            </td>
                            <td>{finding.reasoning}</td>
                            <td>
                              {finding.requires_human_confirmation ? (
                                <span className="badge badge-danger">必需</span>
                              ) : (
                                <span className="badge badge-neutral">否</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {payload?.three_step && (
                <div className="card p-md mb-md">
                  <h2 className="text-base font-bold mb-sm">三步法脚手架（候选）</h2>
                  <div className="text-sm">
                    <p className="mb-xs">
                      <span className="text-secondary">最接近的现有技术：</span>
                      {payload.three_step.closest_prior_art}
                    </p>
                    <p className="mb-xs">
                      <span className="text-secondary">区别特征：</span>
                      {payload.three_step.distinguishing_features.join('、') || '—'}
                    </p>
                    <p className="mb-xs">
                      <span className="text-secondary">实际解决的技术问题：</span>
                      {payload.three_step.actual_technical_problem}
                    </p>
                  </div>
                </div>
              )}

              {payload && (
                <div className="card p-md mb-md">
                  <h2 className="text-base font-bold mb-sm">证据完备度</h2>
                  <div className="grid-3-cols text-sm">
                    <div>
                      <span className="text-secondary">来源覆盖率：</span>
                      {(payload.evidence.source_coverage * 100).toFixed(0)}%
                    </div>
                    <div>
                      <span className="text-secondary">已核验引文：</span>
                      {payload.evidence.verified_citations} / {payload.evidence.total_citations}
                    </div>
                    <div>
                      <span className="text-secondary">等级：</span>
                      {payload.evidence.level}
                    </div>
                  </div>
                  {payload.evidence.missing_anchors.length > 0 && (
                    <p className="text-sm mt-sm">
                      <span className="text-secondary">缺定位锚点：</span>
                      {payload.evidence.missing_anchors.join('、')}
                    </p>
                  )}
                </div>
              )}

              {payload && payload.entity_observations.length > 0 && (
                <div className="card p-md mb-md">
                  <h2 className="text-base font-bold mb-sm">
                    实体级候选观察项（不改变比对判定）
                  </h2>
                  <ul className="text-sm">
                    {payload.entity_observations.map((obs, idx) => (
                      <li key={idx} className="mb-xs">
                        <span className="badge badge-warning">候选</span>{' '}
                        {obs.feature_code} / {obs.doc_id} — {obs.effect}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="alert alert-info">
                <div className="alert-content">
                  本版本不可编辑或删除。如需修订，请生成新的版本号；已批准的版本始终指向
                  被批准时的确切字节（包摘要 {detail.payload_sha256.slice(0, 12)}…）。
                </div>
              </div>
            </>
          )}
        </>
      )}

      {showDeliverable && deliverable && (
        <DeliverableModal
          deliverable={deliverable}
          onClose={() => setShowDeliverable(false)}
        />
      )}
    </WorkbenchLayout>
  )
}

/** 导出预评估意见模态：只读、候选措辞、带人工确认与免责声明，可下载 JSON。 */
const DeliverableModal: React.FC<{
  deliverable: AssessmentDeliverable
  onClose: () => void
}> = ({ deliverable, onClose }) => {
  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(deliverable, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `assessment-deliverable-v${deliverable.version_number}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Modal isOpen title="预评估意见（候选，非结论）" onClose={onClose} size="lg">
      <div className="alert alert-warning mb-sm">
        <div className="alert-content">
          <strong>{deliverable.candidate_notice}</strong>
        </div>
      </div>

      <div className="flex-row flex-wrap gap-sm mb-sm">
        <span className="badge badge-neutral">版本 v{deliverable.version_number}</span>
        <span className={deliverable.eligibility.eligible ? 'badge badge-success' : 'badge badge-danger'}>
          {deliverable.eligibility.eligible ? '允许发布候选判断' : '不允许发布候选判断'}
        </span>
        <span className="badge badge-danger">须人工确认</span>
      </div>

      <div className="text-sm mb-sm">
        <div>
          <span className="text-secondary">复核状态：</span>
          {deliverable.status_label} —— {deliverable.status_caveat}
        </div>
        <div className="break-all">
          <span className="text-secondary">包摘要：</span>
          <span className="font-mono text-xs">{deliverable.payload_sha256}</span>
        </div>
      </div>

      <div className="card p-sm mb-sm">
        <h3 className="text-sm font-bold mb-xs">是否允许发布候选判断（结论门禁）</h3>
        <ul className="text-sm">
          {deliverable.eligibility.reasons.map((reason, idx) => (
            <li key={idx} className="mb-xs">
              {reason}
            </li>
          ))}
        </ul>
      </div>

      {deliverable.blockers.length > 0 && (
        <div className="card p-sm mb-sm">
          <h3 className="text-sm font-bold mb-xs">尚未解决的阻塞项（因此不能给出结论）</h3>
          <ul className="text-sm">
            {deliverable.blockers.map((item, idx) => (
              <li key={idx} className="mb-xs">
                <span className="badge badge-danger">阻塞</span> {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {deliverable.findings.length > 0 && (
        <div className="card p-sm mb-sm">
          <h3 className="text-sm font-bold mb-xs">候选发现（须人工确认）</h3>
          <table className="data-table w-full text-sm">
            <thead>
              <tr>
                <th>类别</th>
                <th>等级</th>
                <th>人工确认</th>
              </tr>
            </thead>
            <tbody>
              {deliverable.findings.map((finding, idx) => (
                <tr key={idx}>
                  <td>{RISK_KIND_LABEL[finding.risk_kind] || finding.risk_kind}</td>
                  <td>{LEVEL_LABEL[finding.level] || finding.level}</td>
                  <td>
                    {finding.requires_human_confirmation ? (
                      <span className="badge badge-danger">必需</span>
                    ) : (
                      <span className="badge badge-neutral">否</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deliverable.entity_observations.length > 0 && (
        <div className="card p-sm mb-sm">
          <h3 className="text-sm font-bold mb-xs">实体级候选观察项</h3>
          <ul className="text-sm">
            {deliverable.entity_observations.map((obs, idx) => (
              <li key={idx} className="mb-xs">
                <span className="badge badge-warning">候选</span>{' '}
                {obs.feature_code} / {obs.doc_id} — {obs.effect}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="alert alert-info mb-sm">
        <div className="alert-content">{deliverable.publication_disclaimer}</div>
      </div>
      <div className="alert alert-info">
        <div className="alert-content">{deliverable.version_freeze_declaration}</div>
      </div>

      <div className="modal-actions mt-md">
        <button type="button" className="btn btn-primary btn-sm" onClick={downloadJson}>
          下载 JSON
        </button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
          关闭
        </button>
      </div>
    </Modal>
  )
}
