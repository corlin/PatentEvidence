import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import type { AssessmentFinding, AssessmentVersionDiff } from '../types/api'

interface AssessmentDiffPanelProps {
  orgId: string
  caseId: string
  /** 当前查看的版本号。 */
  versionNumber: number | null
  /** 该案件全部版本号，用于挑选对比对象。 */
  versionNumbers: number[]
}

const EVIDENCE_LABEL: Record<string, string> = {
  source_coverage: '来源覆盖率',
  verified_citations: '已核验引文',
  total_citations: '引文总数',
  level: '完备度等级',
  blocks_conclusion: '是否阻塞结论',
  missing_anchors: '缺定位锚点',
  unverified_citations: '未逐字核验引文',
  abstract_only_citations: '摘要级引用',
  failed_sources: '失败数据源',
  partial_sources: '部分成功数据源',
  blocking_gaps: '阻塞性缺口',
}

function findingText(finding: AssessmentFinding) {
  return finding.reasoning || finding.risk_kind
}

export const AssessmentDiffPanel: React.FC<AssessmentDiffPanelProps> = ({
  orgId,
  caseId,
  versionNumber,
  versionNumbers,
}) => {
  const others = versionNumbers.filter((n) => n !== versionNumber).sort((a, b) => a - b)
  const [compareTo, setCompareTo] = useState<number | null>(null)
  const [diff, setDiff] = useState<AssessmentVersionDiff | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 默认对比上一个版本：复核人最想知道的就是「这一版比上一版改了什么」
  useEffect(() => {
    if (versionNumber === null) {
      setCompareTo(null)
      return
    }
    const lower = others.filter((n) => n < versionNumber)
    setCompareTo(lower.length > 0 ? lower[lower.length - 1] : others[0] ?? null)
  }, [versionNumber, versionNumbers.join(',')])

  useEffect(() => {
    if (versionNumber === null || compareTo === null) {
      setDiff(null)
      return
    }
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.diffAssessmentVersions(
          orgId,
          caseId,
          versionNumber,
          compareTo
        )
        if (!cancelled) setDiff(res.diff)
      } catch (err) {
        if (!cancelled) {
          setDiff(null)
          setError(err instanceof ApiError ? err.message : '加载版本差异失败')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [orgId, caseId, versionNumber, compareTo])

  if (versionNumber === null || others.length === 0) {
    return (
      <div className="card p-md text-sm text-secondary">
        该案件只有一个版本，暂无可对比的对象。
      </div>
    )
  }

  return (
    <div className="card p-md mb-md">
      <div className="flex-between mb-sm">
        <h2 className="text-base font-bold">与另一版本对比</h2>
        <div className="flex-row gap-xs">
          <label className="form-label" htmlFor="assessment-diff-target">
            对比版本
          </label>
          <select
            id="assessment-diff-target"
            className="input-select"
            value={compareTo ?? ''}
            onChange={(e) => setCompareTo(Number(e.target.value))}
          >
            {others.map((n) => (
              <option key={n} value={n}>
                版本 {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="alert alert-error mb-sm">
          <div className="alert-content">{error}</div>
        </div>
      )}

      {loading && <p className="text-sm text-secondary">正在计算差异...</p>}

      {diff && !loading && (
        <>
          {/* 后端给的三条限定语先渲染，它们决定了下面这些差异该怎么读 */}
          {diff.notes.map((note, idx) => (
            <div key={idx} className="alert alert-info mb-sm">
              <div className="alert-content">{note}</div>
            </div>
          ))}

          <p className="text-sm text-secondary mb-sm">
            版本 {diff.from_version} → 版本 {diff.to_version} · 差异规则{' '}
            <span className="font-mono">{diff.diff_rules_version}</span>
            {diff.rules_version_changed && (
              <>
                {' · 规则版本 '}
                <span className="font-mono">{diff.rules_version.from}</span> →{' '}
                <span className="font-mono">{diff.rules_version.to}</span>
              </>
            )}
          </p>

          {diff.inputs && (
            <div className="text-sm mb-sm">
              <div className="font-medium mb-sm">
                输入档案变化（须人工判断是否导致结论变化）
              </div>
              {diff.inputs.application_profile.changed_fields.length > 0 && (
                <div className="mb-sm">
                  <div className="text-secondary">本案申请信息</div>
                  {diff.inputs.application_profile.changed_fields.map((c, idx) => (
                    <div key={idx} className="font-mono">
                      {c.field}：{c.from ?? '—'} → {c.to ?? '—'}
                    </div>
                  ))}
                </div>
              )}
              {diff.inputs.application_profile.priority_claims.added.length > 0 && (
                <div className="mb-sm">
                  新增优先权主张：{diff.inputs.application_profile.priority_claims.added.join('、')}
                </div>
              )}
              {diff.inputs.application_profile.priority_claims.removed.length > 0 && (
                <div className="mb-sm">
                  不再主张的优先权：{diff.inputs.application_profile.priority_claims.removed.join('、')}
                </div>
              )}
              {diff.inputs.candidate_profiles.added.length > 0 && (
                <div className="mb-sm">
                  新增对比文件档案：{diff.inputs.candidate_profiles.added.join('、')}
                </div>
              )}
              {diff.inputs.candidate_profiles.removed.length > 0 && (
                <div className="mb-sm">
                  不再出现的对比文件档案：{diff.inputs.candidate_profiles.removed.join('、')}
                </div>
              )}
              {diff.inputs.candidate_profiles.changed.map((c, idx) => (
                <div key={idx} className="mb-sm">
                  <span className="font-mono">{c.publication_number}</span>：
                  {c.changed_fields
                    .map((f) => `${f.field} ${f.from ?? '—'}→${f.to ?? '—'}`)
                    .join('；')}
                </div>
              ))}
            </div>
          )}

          <div className="grid-3-cols text-sm mb-sm">
            <div>
              <div className="font-medium">新增阻塞项 {diff.blockers.added.length}</div>
              <ul>
                {diff.blockers.added.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="font-medium">不再出现的阻塞项 {diff.blockers.removed.length}</div>
              <ul>
                {diff.blockers.removed.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="font-medium">仍存在的阻塞项 {diff.blockers.retained.length}</div>
              <ul>
                {diff.blockers.retained.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="grid-3-cols text-sm mb-sm">
            <div>
              <div className="font-medium">新增候选发现 {diff.findings.added.length}</div>
              <ul>
                {diff.findings.added.map((item, idx) => (
                  <li key={idx}>{findingText(item)}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="font-medium">
                不再出现的候选发现 {diff.findings.removed.length}
              </div>
              <ul>
                {diff.findings.removed.map((item, idx) => (
                  <li key={idx}>{findingText(item)}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="font-medium">保留的候选发现 {diff.findings.retained.length}</div>
            </div>
          </div>

          {Object.keys(diff.evidence.scalars).length > 0 && (
            <div className="text-sm mb-sm">
              <div className="font-medium">证据完备度变化</div>
              {Object.entries(diff.evidence.scalars).map(([key, value]) => (
                <div key={key}>
                  {EVIDENCE_LABEL[key] || key}：{String(value.from)} → {String(value.to)}
                </div>
              ))}
            </div>
          )}

          {Object.entries(diff.evidence.lists).map(([key, value]) => (
            <div key={key} className="text-sm mb-sm">
              <div className="font-medium">{EVIDENCE_LABEL[key] || key}</div>
              {value.added.length > 0 && <div>新增：{value.added.join('、')}</div>}
              {value.removed.length > 0 && <div>不再出现：{value.removed.join('、')}</div>}
            </div>
          ))}

          {diff.three_step.present_in_both && (
            <div className="text-sm mb-sm">
              <div className="font-medium">三步法脚手架变化</div>
              {diff.three_step.closest_prior_art && (
                <div>
                  最接近的现有技术：{diff.three_step.closest_prior_art.from} →{' '}
                  {diff.three_step.closest_prior_art.to}
                </div>
              )}
              {diff.three_step.actual_technical_problem && (
                <div>
                  实际解决的技术问题：{diff.three_step.actual_technical_problem.from} →{' '}
                  {diff.three_step.actual_technical_problem.to}
                </div>
              )}
              {diff.three_step.distinguishing_features.added.length > 0 && (
                <div>
                  新增区别特征：
                  {diff.three_step.distinguishing_features.added.join('、')}
                </div>
              )}
              {diff.three_step.distinguishing_features.removed.length > 0 && (
                <div>
                  不再列为区别特征：
                  {diff.three_step.distinguishing_features.removed.join('、')}
                </div>
              )}
            </div>
          )}

          {diff.entity_observations.added.length > 0 && (
            <div className="text-sm mb-sm">
              <div className="font-medium">
                新增实体级候选观察项 {diff.entity_observations.added.length}
              </div>
            </div>
          )}

          {diff.priority_changed && (
            <p className="text-sm">
              <span className="badge badge-warning">提示</span> 优先权核验结果发生了变化。
            </p>
          )}
        </>
      )}
    </div>
  )
}
