import React, { useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import type { AssessmentDecisionRecord, AssessmentVersionDetail } from '../types/api'

interface AssessmentReviewPanelProps {
  orgId: string
  caseId: string
  detail: AssessmentVersionDetail | null
  /** 决策已追加，外层据此刷新版本列表与详情。 */
  onDecided?: () => void
}

/** 终态版本不可再决策；修订 = 新版本号。 */
const TERMINAL = new Set(['approved', 'rejected'])

const DECISION_LABEL: Record<string, string> = {
  approved: '复核通过',
  rejected: '复核未通过',
  changes_requested: '打回修改',
  submitted: '已提交复核',
}

/** 状态标记一律配一句限定语，避免「已批准」被读成「具备专利性」。 */
const STATUS_NOTE: Record<string, string> = {
  approved: '仅表示本候选评估包通过内部复核，不代表该方案具备专利性或可授权。',
  rejected: '本候选评估包未通过内部复核，不等于该方案不具备专利性。',
  changes_requested: '已回到草稿，修订请生成新版本号。',
  submitted: '等待复核人作出决定。',
  draft: '尚未提交复核。',
}

export const AssessmentReviewPanel: React.FC<AssessmentReviewPanelProps> = ({
  orgId,
  caseId,
  detail,
  onDecided,
}) => {
  const [comments, setComments] = useState('')
  const [accepts, setAccepts] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [last, setLast] = useState<AssessmentDecisionRecord | null>(null)

  if (!detail) {
    return (
      <div className="card p-md text-sm text-secondary">
        请先在「版本」页签选择一个评估版本，再在此处复核。
      </div>
    )
  }

  const status = detail.status || 'draft'
  const blockers = detail.payload?.blockers || []
  const terminal = TERMINAL.has(status)
  // 有阻塞项时批准必须显式声明并写明理由，否则按钮保持禁用
  const gateSatisfied = blockers.length === 0 || (accepts && comments.trim().length > 0)

  const submit = async () => {
    setBusy('submit')
    setError(null)
    setLast(null)
    try {
      const res = await apiClient.submitAssessmentVersion(orgId, caseId, detail.version_number)
      setLast(res.decision)
      if (onDecided) onDecided()
    } catch (err) {
      setError(refusalText(err))
    } finally {
      setBusy(null)
    }
  }

  const decide = async (decision: 'approved' | 'rejected' | 'changes_requested') => {
    setBusy(decision)
    setError(null)
    setLast(null)
    try {
      const res = await apiClient.decideAssessmentVersion(
        orgId,
        caseId,
        detail.version_number,
        {
          decision,
          comments,
          accepts_insufficient_evidence: decision === 'approved' ? accepts : false,
        }
      )
      setLast(res.decision)
      if (onDecided) onDecided()
    } catch (err) {
      setError(refusalText(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="alert alert-info mb-md">
        <div className="alert-content">
          复核是对<strong>这个候选评估包</strong>的内部确认，不是专利性结论。复核通过只说明
          包内内容已按规则产出并经过人工确认，不代表该方案具备专利性或可授权。
        </div>
      </div>

      {error && (
        <div className="alert alert-error mb-md">
          <div className="alert-content">{error}</div>
        </div>
      )}

      <div className="card p-md mb-md">
        <div className="flex-between mb-sm">
          <h2 className="text-base font-bold">版本 {detail.version_number} 复核状态</h2>
          <span
            className={
              status === 'approved'
                ? 'badge badge-success'
                : status === 'rejected'
                  ? 'badge badge-danger'
                  : status === 'submitted'
                    ? 'badge badge-warning'
                    : 'badge badge-neutral'
            }
          >
            {DECISION_LABEL[status] || status}
          </span>
        </div>
        <p className="text-sm text-secondary">{STATUS_NOTE[status] || ''}</p>
        <p className="text-xs text-secondary mt-xs break-all">
          包摘要 <span className="font-mono">{detail.payload_sha256}</span>
          {last && (
            <>
              {' · 决策签名 '}
              <span className="font-mono">{last.decision_signature.slice(0, 16)}…</span>
            </>
          )}
        </p>
      </div>

      {terminal && (
        <div className="alert alert-warning mb-md">
          <div className="alert-content">
            该版本已处于终态，不可再变更。如需修改，请生成新的版本号 —— 修订不会改写这一份，
            已批准的版本始终指向被批准时的确切字节。
          </div>
        </div>
      )}

      {blockers.length > 0 && (
        <div className="card p-md mb-md">
          <h2 className="text-base font-bold mb-sm">
            该版本仍有 {blockers.length} 项未解决的阻塞项
          </h2>
          <ul className="text-sm">
            {blockers.map((item, idx) => (
              <li key={idx} className="mb-xs">
                <span className="badge badge-danger">阻塞</span> {item}
              </li>
            ))}
          </ul>
          <p className="text-sm text-secondary mt-sm">
            批准一个仍有阻塞项的版本，等于确认「明知证据不足仍接受这份候选输出」，
            必须显式声明并写明理由；否则状态机会拒绝该决定。
          </p>
        </div>
      )}

      {!terminal && (
        <div className="card p-md mb-md">
          <h2 className="text-base font-bold mb-sm">复核动作</h2>

          {status === 'draft' ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy === 'submit'}
              onClick={submit}
            >
              {busy === 'submit' ? '提交中...' : '提交复核'}
            </button>
          ) : (
            <>
              <div className="form-group">
                <label className="form-label" htmlFor="assessment-review-comments">
                  复核意见
                </label>
                <textarea
                  id="assessment-review-comments"
                  className="input-text"
                  rows={3}
                  value={comments}
                  onChange={(e) => setComments(e.target.value)}
                />
              </div>

              {blockers.length > 0 && (
                <div className="form-group">
                  <label className="text-sm flex-row gap-xs">
                    <input
                      type="checkbox"
                      aria-label="明知存在未解决阻塞项仍批准"
                      checked={accepts}
                      onChange={(e) => setAccepts(e.target.checked)}
                    />
                    我明知上列 {blockers.length} 项阻塞项未解决，仍决定批准本评估包
                  </label>
                  {accepts && comments.trim().length === 0 && (
                    <p className="text-sm text-danger mt-xs">接受证据不足必须写明理由。</p>
                  )}
                </div>
              )}

              <div className="flex-row gap-sm flex-wrap">
                <button
                  type="button"
                  className="btn btn-success"
                  disabled={busy !== null || !gateSatisfied}
                  onClick={() => decide('approved')}
                >
                  {busy === 'approved' ? '处理中...' : '批准本评估包'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy !== null}
                  onClick={() => decide('changes_requested')}
                >
                  {busy === 'changes_requested' ? '处理中...' : '打回修改'}
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={busy !== null}
                  onClick={() => decide('rejected')}
                >
                  {busy === 'rejected' ? '处理中...' : '复核未通过'}
                </button>
              </div>
              {!gateSatisfied && (
                <p className="text-sm text-secondary mt-sm">
                  批准按钮在勾选声明并写明理由之前保持禁用。
                </p>
              )}
            </>
          )}
        </div>
      )}
    </>
  )
}

function refusalText(err: unknown) {
  if (err instanceof ApiError) {
    if (err.detail === 'version_frozen') {
      return '该版本已处于终态，不可再变更；修订请生成新版本号。'
    }
    if (err.detail === 'invalid_transition') {
      return '当前状态不允许该动作。'
    }
    return err.message
  }
  return '复核动作失败。'
}
