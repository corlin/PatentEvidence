import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import type {
  AssessmentApplicationProfile,
  AssessmentAssembleResult,
  AssessmentCandidateProfile,
} from '../types/api'

interface AssessmentInputPanelProps {
  orgId: string
  caseId: string
  /** 组装成功后回调，外层据此刷新只读版本列表。 */
  onAssembled?: (result: AssessmentAssembleResult) => void
}

/** 后端拒绝组装时的 422 码 → 人话。缺什么就说什么，不泛化成「操作失败」。 */
const REFUSAL_TEXT: Record<string, string> = {
  application_profile_missing:
    '尚未登记本案申请日。日期门禁需要基准日，缺基准日时组装会直接拒绝，不会产出版本。',
  no_comparison_matrix: '该案件还没有已确认的比对矩阵，无法取出特征单元格。',
  no_comparison_cells: '已确认的比对矩阵里没有任何特征单元格，无法组装。',
  case_not_found: '未找到该案件，或它不属于当前组织。',
}

function refusalText(detail: string | null | undefined) {
  if (!detail) return '组装被拒绝。'
  return REFUSAL_TEXT[detail] || `组装被拒绝：${detail}`
}

export const AssessmentInputPanel: React.FC<AssessmentInputPanelProps> = ({
  orgId,
  caseId,
  onAssembled,
}) => {
  const [profile, setProfile] = useState<AssessmentApplicationProfile | null>(null)
  const [candidates, setCandidates] = useState<AssessmentCandidateProfile[]>([])

  const [filingDate, setFilingDate] = useState('')
  const [applicationType, setApplicationType] = useState('invention')
  const [priorityClaims, setPriorityClaims] = useState<
    Array<{ claim_id: string; priority_date: string; country: string; proof_verified: boolean }>
  >([])

  const [drafts, setDrafts] = useState<Record<string, { filing_date: string; priority_date: string; filed_in_china: boolean; source_verified: boolean }>>({})

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [assembling, setAssembling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [result, setResult] = useState<AssessmentAssembleResult | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [profileRes, candRes] = await Promise.all([
        apiClient.getAssessmentApplicationProfile(orgId, caseId),
        apiClient.listAssessmentCandidateProfiles(orgId, caseId),
      ])
      const loaded = profileRes.profile
      setProfile(loaded)
      if (loaded) {
        setFilingDate(loaded.filing_date || '')
        setApplicationType(loaded.application_type || 'invention')
        setPriorityClaims(
          (loaded.priority_claims || []).map((c) => ({
            claim_id: String(c.claim_id ?? ''),
            priority_date: String(c.priority_date ?? ''),
            country: String(c.country ?? ''),
            proof_verified: Boolean(c.proof_verified),
          }))
        )
      }
      setCandidates(candRes.items || [])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载评估输入档案失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [orgId, caseId])

  const draftFor = (item: AssessmentCandidateProfile) =>
    drafts[item.candidate_id] || {
      filing_date: item.filing_date || '',
      priority_date: item.priority_date || '',
      filed_in_china: item.filed_in_china === null ? true : item.filed_in_china,
      source_verified: item.source_verified,
    }

  const saveApplication = async () => {
    if (!filingDate) {
      setError('本案申请日是日期门禁的基准日，不能为空。')
      return
    }
    setSaving('application')
    setError(null)
    setNotice(null)
    try {
      const res = await apiClient.upsertAssessmentApplicationProfile(orgId, caseId, {
        filing_date: filingDate,
        application_type: applicationType,
        priority_claims: priorityClaims
          .filter((c) => c.claim_id && c.priority_date)
          .map((c) => ({
            claim_id: c.claim_id,
            priority_date: c.priority_date,
            country: c.country,
            first_application: true,
            same_subject: true,
            proof_verified: c.proof_verified,
            covers: [],
          })),
      })
      setProfile(res.profile)
      setNotice('本案申请信息已保存。它只用于之后生成的新版本。')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(null)
    }
  }

  const saveCandidate = async (item: AssessmentCandidateProfile) => {
    const draft = draftFor(item)
    setSaving(item.candidate_id)
    setError(null)
    setNotice(null)
    try {
      const res = await apiClient.upsertAssessmentCandidateProfile(
        orgId,
        caseId,
        item.candidate_id,
        {
          filing_date: draft.filing_date || null,
          priority_date: draft.priority_date || null,
          filed_in_china: draft.filed_in_china,
          source_verified: draft.source_verified,
        }
      )
      setCandidates((prev) =>
        prev.map((c) => (c.candidate_id === item.candidate_id ? res.profile : c))
      )
      setNotice(`${item.publication_number || item.candidate_id} 的档案已保存。`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(null)
    }
  }

  const assemble = async () => {
    setAssembling(true)
    setError(null)
    setNotice(null)
    setResult(null)
    try {
      const res = await apiClient.createAssessmentVersionFromCase(orgId, caseId)
      setResult(res)
      if (onAssembled) onAssembled(res)
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : null
      setError(refusalText(detail))
    } finally {
      setAssembling(false)
    }
  }

  const pendingCount = candidates.filter((c) => !c.has_profile).length

  if (loading) {
    return <div className="card p-md text-sm text-secondary">正在加载输入档案...</div>
  }

  return (
    <>
      {/* 输入档案是可变的，版本是冻结的 —— 这句话必须在填写区之前说清 */}
      <div className="alert alert-info mb-md">
        <div className="alert-content">
          这里填写的是<strong>输入档案</strong>，不是评估结论。改动档案只影响<strong>之后生成的新版本</strong>，
          不会改写任何已经生成的版本；已批准的版本始终指向被批准时的确切字节。
        </div>
      </div>

      {error && (
        <div className="alert alert-error mb-md">
          <div className="alert-content">{error}</div>
        </div>
      )}
      {notice && (
        <div className="alert alert-success mb-md">
          <div className="alert-content">{notice}</div>
        </div>
      )}

      <div className="card p-md mb-md">
        <h2 className="text-base font-bold mb-sm">本案申请信息（日期门禁的基准）</h2>
        <p className="text-sm text-secondary mb-sm">
          申请日无法从任何既有数据推断，必须人工登记；公开日不等于申请日。留空时组装会直接拒绝，
          不会替你猜一个基准日。
        </p>
        <div className="grid-3-cols">
          <div className="form-group">
            <label className="form-label" htmlFor="assessment-filing-date">
              申请日
            </label>
            <input
              id="assessment-filing-date"
              className="input-text"
              type="date"
              aria-label="本案申请日"
              value={filingDate}
              onChange={(e) => setFilingDate(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="assessment-app-type">
              申请类型
            </label>
            <select
              id="assessment-app-type"
              className="input-select"
              value={applicationType}
              onChange={(e) => setApplicationType(e.target.value)}
            >
              <option value="invention">发明</option>
              <option value="utility_model">实用新型</option>
              <option value="design">外观设计</option>
            </select>
          </div>
          <div className="form-group">
            <span className="form-label">当前状态</span>
            <div className="text-sm">
              {profile ? (
                <span className="badge badge-success">已登记</span>
              ) : (
                <span className="badge badge-danger">未登记</span>
              )}
            </div>
          </div>
        </div>

        <div className="mt-sm">
          <div className="flex-between mb-xs">
            <h3 className="text-sm font-bold">优先权主张（选填）</h3>
            <button
              type="button"
              className="btn btn-secondary btn-xs"
              onClick={() =>
                setPriorityClaims((prev) => [
                  ...prev,
                  { claim_id: '', priority_date: '', country: '', proof_verified: false },
                ])
              }
            >
              + 添加一项
            </button>
          </div>
          {priorityClaims.length === 0 ? (
            <p className="text-sm text-secondary">无优先权主张。</p>
          ) : (
            priorityClaims.map((claim, idx) => (
              <div key={idx} className="flex-row gap-sm mb-xs">
                <input
                  className="input-text"
                  placeholder="在先申请号"
                  aria-label="在先申请号"
                  value={claim.claim_id}
                  onChange={(e) => {
                    const next = [...priorityClaims]
                    next[idx] = { ...next[idx], claim_id: e.target.value }
                    setPriorityClaims(next)
                  }}
                />
                <input
                  className="input-text"
                  type="date"
                  aria-label="优先权日"
                  value={claim.priority_date}
                  onChange={(e) => {
                    const next = [...priorityClaims]
                    next[idx] = { ...next[idx], priority_date: e.target.value }
                    setPriorityClaims(next)
                  }}
                />
                <input
                  className="input-text"
                  placeholder="国家或地区"
                  aria-label="国家或地区"
                  value={claim.country}
                  onChange={(e) => {
                    const next = [...priorityClaims]
                    next[idx] = { ...next[idx], country: e.target.value }
                    setPriorityClaims(next)
                  }}
                />
                <label className="text-sm flex-row gap-xs">
                  <input
                    type="checkbox"
                    aria-label="优先权证明文件已核验"
                    checked={claim.proof_verified}
                    onChange={(e) => {
                      const next = [...priorityClaims]
                      next[idx] = { ...next[idx], proof_verified: e.target.checked }
                      setPriorityClaims(next)
                    }}
                  />
                  副本已核验
                </label>
                <button
                  type="button"
                  className="btn btn-secondary btn-xs"
                  onClick={() =>
                    setPriorityClaims((prev) => prev.filter((_, i) => i !== idx))
                  }
                >
                  移除
                </button>
              </div>
            ))
          )}
        </div>

        <button
          type="button"
          className="btn btn-primary btn-sm mt-sm"
          disabled={saving === 'application'}
          onClick={saveApplication}
        >
          {saving === 'application' ? '保存中...' : '保存本案申请信息'}
        </button>
      </div>

      <div className="card p-md mb-md">
        <div className="flex-between mb-sm">
          <h2 className="text-base font-bold">对比文件档案</h2>
          {pendingCount > 0 && (
            <span className="badge badge-danger">{pendingCount} 篇尚未建档</span>
          )}
        </div>
        <p className="text-sm text-secondary mb-sm">
          列表包含全部检索候选，<strong>未建档的也会列出</strong>。申请日与优先权日无法从公开日推断，
          来源核验也不等于检索命中 —— 命中只是检索到了，核验要求确认文献本身。
        </p>
        {candidates.length === 0 ? (
          <p className="text-sm text-secondary">该案件尚无检索候选文献。</p>
        ) : (
          <table className="data-table w-full text-sm">
            <thead>
              <tr>
                <th>文献</th>
                <th>申请日</th>
                <th>优先权日</th>
                <th>中国申请</th>
                <th>来源已核验</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {candidates.map((item) => {
                const draft = draftFor(item)
                const setDraft = (patch: Partial<typeof draft>) =>
                  setDrafts((prev) => ({
                    ...prev,
                    [item.candidate_id]: { ...draft, ...patch },
                  }))
                const label = item.publication_number || item.candidate_id
                return (
                  <tr key={item.candidate_id}>
                    <td>
                      <div className="font-medium">{item.publication_number || '—'}</div>
                      <div className="text-xs text-secondary">{item.title || ''}</div>
                      {!item.has_profile && (
                        <span className="badge badge-warning">未建档</span>
                      )}
                    </td>
                    <td>
                      <input
                        className="input-text"
                        type="date"
                        aria-label={`${label} 申请日`}
                        value={draft.filing_date}
                        onChange={(e) => setDraft({ filing_date: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="input-text"
                        type="date"
                        aria-label={`${label} 优先权日`}
                        value={draft.priority_date}
                        onChange={(e) => setDraft({ priority_date: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${label} 是否中国申请`}
                        checked={draft.filed_in_china}
                        onChange={(e) => setDraft({ filed_in_china: e.target.checked })}
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${label} 来源已核验`}
                        checked={draft.source_verified}
                        onChange={(e) => setDraft({ source_verified: e.target.checked })}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        aria-label={`保存 ${label} 档案`}
                        disabled={saving === item.candidate_id}
                        onClick={() => saveCandidate(item)}
                      >
                        {saving === item.candidate_id ? '保存中...' : '保存'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card p-md mb-md">
        <h2 className="text-base font-bold mb-sm">依据案件既有数据生成新版本</h2>
        <p className="text-sm text-secondary mb-sm">
          组装会读取已确认的比对矩阵、检索候选与检索任务，跑一遍确定性门禁后冻结成新版本号。
          <strong>缺失项不会被补默认值</strong>：缺基准日或单元格会直接拒绝，其余缺口并入该版本的阻塞项。
        </p>
        <button
          type="button"
          className="btn btn-primary"
          disabled={assembling}
          onClick={assemble}
        >
          {assembling ? '正在组装...' : '生成新版本'}
        </button>
      </div>

      {/* 组装结果：缺口必须比「成功」更显眼，否则一键操作会把缺口藏起来 */}
      {result && (
        <div className="card p-md mb-md">
          <h2 className="text-base font-bold mb-sm">
            已生成版本 {result.version.version_number}
          </h2>
          {result.gaps.length > 0 ? (
            <div className="alert alert-error mb-sm">
              <div className="alert-content">
                <strong>
                  新版本已生成，但下列源数据缺口未解决，已并入该版本的阻塞项 —— 它因此不能给出结论。
                </strong>
                <ul className="mt-xs">
                  {result.gaps.map((gap, idx) => (
                    <li key={idx}>{gap}</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <div className="alert alert-warning mb-sm">
              <div className="alert-content">
                新版本已生成。它仍是候选发现与阻塞项，不构成专利性结论。
              </div>
            </div>
          )}
          <div className="text-sm">
            <span className="text-secondary">该版本阻塞项：</span>
            {result.version.blockers.length} 项
          </div>
        </div>
      )}
    </>
  )
}
