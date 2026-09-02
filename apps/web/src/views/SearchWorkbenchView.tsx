import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import { CaseWorkflowStepper } from '../components/CaseWorkflowStepper'
import type {
  HandoffPackage,
  SearchCandidate,
  SearchStrategy,
  TriageStatus,
} from '../types/api'
import { Link } from '../router/Router'

interface SearchWorkbenchViewProps {
  orgId: string
  caseId: string
}

export const SearchWorkbenchView: React.FC<SearchWorkbenchViewProps> = ({ orgId, caseId }) => {
  const { requestMfaStepUp } = useSession()

  const [activeTab, setActiveTab] = useState<'strategy' | 'candidates'>('strategy')
  const [strategy, setStrategy] = useState<SearchStrategy | null>(null)
  const [candidates, setCandidates] = useState<SearchCandidate[]>([])
  const [candidateFilter, setCandidateFilter] = useState<string>('all')

  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Handoff Modal
  const [isHandoffModalOpen, setIsHandoffModalOpen] = useState(false)
  const [handoffData, setHandoffData] = useState<HandoffPackage | null>(null)
  const [copied, setCopied] = useState(false)

  // Import CNIPR Modal
  const [isImportModalOpen, setIsImportModalOpen] = useState(false)
  const [importText, setImportText] = useState('')

  // Triage Exclude Modal
  const [isExcludeModalOpen, setIsExcludeModalOpen] = useState(false)
  const [excludeTarget, setExcludeTarget] = useState<SearchCandidate | null>(null)
  const [excludeReason, setExcludeReason] = useState('技术领域不符')
  const [excludeNotes, setExcludeNotes] = useState('')

  // Edit strategy state
  const [editCniprQuery, setEditCniprQuery] = useState('')
  const [editStdQuery, setEditStdQuery] = useState('')

  const fetchStrategy = async () => {
    try {
      const data = await apiClient.getActiveSearchStrategy(orgId, caseId)
      setStrategy(data)
      setEditCniprQuery(data.boolean_query_cnipr)
      setEditStdQuery(data.boolean_query_standard)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 404) {
        setStrategy(null)
      } else if (err instanceof ApiError && err.status === 403) {
        requestMfaStepUp(fetchStrategy)
      } else {
        setError(err.detail || '加载检索策略失败')
      }
    }
  }

  const fetchCandidates = async () => {
    try {
      const res = await apiClient.listSearchCandidates(
        orgId,
        caseId,
        candidateFilter === 'all' ? undefined : candidateFilter
      )
      setCandidates(res.items)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) {
        requestMfaStepUp(fetchCandidates)
      } else {
        setError(err.detail || '加载候选专利池失败')
      }
    }
  }

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    await Promise.all([fetchStrategy(), fetchCandidates()])
    setLoading(false)
  }

  useEffect(() => {
    loadAll()
  }, [orgId, caseId, candidateFilter])

  const handleGenerateStrategy = async () => {
    setActionLoading(true)
    setError(null)
    try {
      const data = await apiClient.generateSearchStrategy(orgId, caseId)
      setStrategy(data)
      setEditCniprQuery(data.boolean_query_cnipr)
      setEditStdQuery(data.boolean_query_standard)
      setSuccess('已成功根据确认技术特征生成检索策略与 CNIPR 布尔检索式！')
    } catch (err: any) {
      setError(err.detail || '生成检索策略失败，请先确认案件技术特征')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSaveStrategy = async () => {
    if (!strategy) return
    setActionLoading(true)
    try {
      const data = await apiClient.updateSearchStrategy(orgId, caseId, strategy.id, {
        boolean_query_cnipr: editCniprQuery,
        boolean_query_standard: editStdQuery,
      })
      setStrategy(data)
      setSuccess('检索式更新成功！')
    } catch (err: any) {
      setError(err.detail || '保存检索式失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleOpenHandoffModal = async () => {
    if (!strategy) return
    setActionLoading(true)
    try {
      const data = await apiClient.getSearchHandoffPackage(orgId, caseId, strategy.id)
      setHandoffData(data)
      setIsHandoffModalOpen(true)
    } catch (err: any) {
      setError(err.detail || '获取交接包失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleExecutePublicSearch = async (sourceType: string = 'google_patents') => {
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.executePublicSearch(orgId, caseId, sourceType)
      setSuccess(`公网检索执行完成，新增检索出 ${res.results_count} 篇候选专利！`)
      await fetchCandidates()
      setActiveTab('candidates')
    } catch (err: any) {
      setError(err.detail || '执行公开检索失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleImportCniprSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importText.trim()) return
    setActionLoading(true)
    try {
      const res = await apiClient.importCniprCandidates(orgId, caseId, importText)
      setSuccess(`成功从 CNIPR 官方结果导入 ${res.imported_count} 篇候选专利！`)
      setIsImportModalOpen(false)
      setImportText('')
      await fetchCandidates()
      setActiveTab('candidates')
    } catch (err: any) {
      setError(err.detail || '导入 CNIPR 结果失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleTriageInclude = async (candidateId: string) => {
    setActionLoading(true)
    try {
      await apiClient.updateCandidateTriage(orgId, caseId, candidateId, {
        triage_status: 'included',
      })
      setSuccess('已将该专利纳入后续权利要求级深度比对清单！')
      fetchCandidates()
    } catch (err: any) {
      setError(err.detail || '更新初筛状态失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleTriageExcludeSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!excludeTarget) return
    setActionLoading(true)
    try {
      await apiClient.updateCandidateTriage(orgId, caseId, excludeTarget.id, {
        triage_status: 'excluded',
        exclusion_reason: excludeReason,
        notes: excludeNotes,
      })
      setSuccess(`已排除专利 ${excludeTarget.publication_number} 并记录排除原因！`)
      setIsExcludeModalOpen(false)
      setExcludeTarget(null)
      setExcludeNotes('')
      fetchCandidates()
    } catch (err: any) {
      setError(err.detail || '排除操作失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleCopyQuery = (textToCopy: string) => {
    navigator.clipboard.writeText(textToCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="layout-container">
      <Header />

      <main className="main-content">
        <div className="breadcrumb text-xs text-secondary mb-xs">
          <Link to={`/organizations/${orgId}/cases`}>案件列表</Link> &gt;{' '}
          <Link to={`/organizations/${orgId}/cases/${caseId}`}>案件详情</Link> &gt; 专利检索与候选池
        </div>

        {/* Page Header */}
        <div className="page-header flex-between mb-md">
          <div>
            <h1 className="page-title text-2xl font-bold">专利检索规划与候选证据初筛</h1>
            <p className="text-secondary text-sm">
              基于确认技术特征制定检索策略、导出 CNIPR 人工交接规范包并执行多路去重初筛
            </p>
          </div>

          <div className="actions flex-row gap-sm">
            {candidates.some((c) => c.triage_status === 'included') && (
              <Link
                to={`/organizations/${orgId}/cases/${caseId}/comparisons`}
                className="btn btn-primary btn-sm font-bold"
              >
                📊 前往 Claim Chart 比对 &rarr;
              </Link>
            )}
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/features`}
              className="btn btn-secondary btn-sm"
            >
              &larr; 查看技术特征
            </Link>
            <Link to={`/organizations/${orgId}/cases/${caseId}`} className="btn btn-secondary btn-sm">
              返回案件详情
            </Link>
          </div>
        </div>

        {/* Workflow Lifecycle Stepper */}
        <CaseWorkflowStepper
          orgId={orgId}
          caseId={caseId}
          currentStep="search"
          caseStatus={candidates.some((c) => c.triage_status === 'included') ? 'assessment_ready' : 'evidence_ready'}
        />

        {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
        {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

        {/* Tab Navigation */}
        <div className="flex-row gap-md border-b mb-md">
          <button
            type="button"
            className={`tab-btn p-sm font-semibold ${
              activeTab === 'strategy' ? 'tab-active text-primary border-b-2 border-primary' : 'text-secondary'
            }`}
            onClick={() => setActiveTab('strategy')}
          >
            📋 检索规划与 CNIPR 交接包
          </button>
          <button
            type="button"
            className={`tab-btn p-sm font-semibold ${
              activeTab === 'candidates' ? 'tab-active text-primary border-b-2 border-primary' : 'text-secondary'
            }`}
            onClick={() => setActiveTab('candidates')}
          >
            🔍 多路检索与候选池初筛 ({candidates.length})
          </button>
        </div>

        {/* TAB 1: Strategy & Handoff */}
        {activeTab === 'strategy' && (
          <div className="strategy-tab-content">
            {strategy ? (
              <div className="flex-stack gap-md">
                {/* Action Bar */}
                <div className="card p-md flex-between">
                  <div>
                    <h2 className="text-md font-bold mb-xs">检索策略已生成 (v1)</h2>
                    <p className="text-xs text-secondary">
                      针对 CNIPR 语法与公开数据源已就绪。支持导出规范人工交接包或直接触发公网检索。
                    </p>
                  </div>
                  <div className="flex-row gap-sm">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={handleGenerateStrategy}
                      disabled={actionLoading}
                    >
                      重新规划
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={handleOpenHandoffModal}
                      disabled={actionLoading}
                    >
                      📦 导出 CNIPR 规范交接包
                    </button>
                    <button
                      type="button"
                      className="btn btn-success btn-sm"
                      onClick={() => handleExecutePublicSearch('google_patents')}
                      disabled={actionLoading}
                    >
                      ⚡ 执行公开源检索
                    </button>
                  </div>
                </div>

                {/* Keywords & IPC Grid */}
                <div className="grid-2-cols gap-md">
                  {/* Keywords Matrix */}
                  <div className="card p-md">
                    <h3 className="text-sm font-bold mb-sm">关键词与同义词扩展矩阵</h3>
                    <div className="flex-stack gap-xs">
                      {Object.entries(strategy.keywords_matrix).map(([root, syns]) => (
                        <div key={root} className="p-xs bg-subtle rounded text-xs">
                          <strong className="text-primary mr-xs">[{root}]</strong>
                          <span>{syns.join(' / ')}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* IPC Classes */}
                  <div className="card p-md">
                    <h3 className="text-sm font-bold mb-sm">推荐 IPC / CPC 分类号</h3>
                    <div className="flex-stack gap-xs">
                      {strategy.ipc_classes.map((ipc, idx) => (
                        <div key={idx} className="p-xs bg-subtle rounded text-xs flex-between">
                          <span className="badge badge-neutral font-mono font-bold">{ipc.code}</span>
                          <span className="text-secondary ml-sm">{ipc.description}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Boolean Query Editors */}
                <div className="card p-md">
                  <div className="flex-between mb-sm">
                    <h3 className="text-sm font-bold">CNIPR 官方系统定制布尔检索式</h3>
                    <button
                      type="button"
                      className="btn btn-secondary btn-xs"
                      onClick={() => handleCopyQuery(editCniprQuery)}
                    >
                      {copied ? '已复制！' : '复制 CNIPR 检索式'}
                    </button>
                  </div>
                  <textarea
                    className="input-text font-mono text-xs mb-md"
                    rows={3}
                    value={editCniprQuery}
                    onChange={(e) => setEditCniprQuery(e.target.value)}
                  />

                  <div className="flex-between mb-sm">
                    <h3 className="text-sm font-bold">通用标准检索式 (Google Patents / EPO)</h3>
                  </div>
                  <textarea
                    className="input-text font-mono text-xs mb-md"
                    rows={3}
                    value={editStdQuery}
                    onChange={(e) => setEditStdQuery(e.target.value)}
                  />

                  <div className="flex-row justify-end">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={handleSaveStrategy}
                      disabled={actionLoading}
                    >
                      保存检索式修改
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="card p-xl text-center">
                <h2 className="text-lg font-bold mb-sm">尚未规划专利检索策略</h2>
                <p className="text-sm text-secondary mb-md">
                  系统将分析案件已确认的权利要求特征，自动提取同义词矩阵、匹配 IPC 分类号并生成 CNIPR 语法检索式。
                </p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleGenerateStrategy}
                  disabled={actionLoading}
                >
                  {actionLoading ? '正在智能规划...' : '⚡ 一键生成检索策略与 CNIPR 检索式'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: Multi-Source Search & Candidates Triage */}
        {activeTab === 'candidates' && (
          <div className="candidates-tab-content">
            {/* Toolbar */}
            <div className="card p-md flex-between mb-md">
              <div className="flex-row gap-xs">
                {['all', 'pending', 'included', 'excluded'].map((st) => (
                  <button
                    key={st}
                    type="button"
                    className={`btn btn-xs ${
                      candidateFilter === st ? 'btn-primary' : 'btn-secondary'
                    }`}
                    onClick={() => setCandidateFilter(st)}
                  >
                    {st === 'all'
                      ? '全部'
                      : st === 'pending'
                      ? '待初筛'
                      : st === 'included'
                      ? '已纳入比对'
                      : '已排除'}
                  </button>
                ))}
              </div>

              <div className="flex-row gap-sm">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setIsImportModalOpen(true)}
                >
                  📥 导入 CNIPR 官方检索结果
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => handleExecutePublicSearch('google_patents')}
                  disabled={actionLoading}
                >
                  🌐 触发公网检索 (Google Patents)
                </button>
              </div>
            </div>

            {/* Candidates List */}
            {candidates.length > 0 ? (
              <div className="flex-stack gap-md">
                {candidates.map((cand) => (
                  <div key={cand.id} className="card p-md border rounded bg-surface">
                    <div className="flex-between mb-xs">
                      <div className="flex-row gap-sm align-center">
                        <span className="badge badge-primary font-mono font-bold">
                          {cand.publication_number}
                        </span>
                        <span
                          className={`badge font-bold text-xs ${
                            cand.relevance_score >= 80
                              ? 'badge-success'
                              : cand.relevance_score >= 50
                              ? 'badge-warning'
                              : 'badge-neutral'
                          }`}
                        >
                          相关度: {cand.relevance_score}分
                        </span>
                        <span className="badge badge-neutral text-xs">
                          {cand.source_type === 'cnipr_manual' ? 'CNIPR人工导入' : '公开源检索'}
                        </span>
                        {cand.publication_date && (
                          <span className="text-xs text-secondary">
                            公开日: {cand.publication_date}
                          </span>
                        )}
                        {cand.ipc_classification && (
                          <span className="badge badge-neutral font-mono text-xs">
                            {cand.ipc_classification}
                          </span>
                        )}
                      </div>

                      {/* Triage Status & Actions */}
                      <div className="flex-row gap-xs">
                        {cand.triage_status === 'pending' && (
                          <>
                            <button
                              type="button"
                              className="btn btn-success btn-xs"
                              onClick={() => handleTriageInclude(cand.id)}
                            >
                              ✓ 纳入比对
                            </button>
                            <button
                              type="button"
                              className="btn btn-danger btn-xs"
                              onClick={() => {
                                setExcludeTarget(cand)
                                setIsExcludeModalOpen(true)
                              }}
                            >
                              ✗ 排除
                            </button>
                          </>
                        )}
                        {cand.triage_status === 'included' && (
                          <div className="flex-row gap-xs align-center">
                            <span className="badge badge-success text-xs">✓ 已纳入比对清单</span>
                            <button
                              type="button"
                              className="btn btn-secondary btn-xs"
                              onClick={() => {
                                setExcludeTarget(cand)
                                setIsExcludeModalOpen(true)
                              }}
                            >
                              改为排除
                            </button>
                          </div>
                        )}
                        {cand.triage_status === 'excluded' && (
                          <div className="flex-row gap-xs align-center">
                            <span className="badge badge-neutral text-xs">
                              已排除: {cand.exclusion_reason || '其他'}
                            </span>
                            <button
                              type="button"
                              className="btn btn-secondary btn-xs"
                              onClick={() => handleTriageInclude(cand.id)}
                            >
                              撤销排除
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Title & Abstract */}
                    <h3 className="text-sm font-bold text-text mb-xs">{cand.title}</h3>
                    <p className="text-xs text-secondary mb-xs line-clamp-3">{cand.abstract}</p>
                    {cand.applicant && (
                      <p className="text-xs text-secondary">申请人/专利权人：{cand.applicant}</p>
                    )}

                    {/* Exclude notes if any */}
                    {cand.triage_status === 'excluded' && cand.notes && (
                      <div className="mt-xs p-xs bg-subtle rounded text-xs text-secondary">
                        <strong>排除备注：</strong> {cand.notes}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="card p-xl text-center">
                <h3 className="text-md font-bold mb-xs">当前候选池中暂无文献</h3>
                <p className="text-xs text-secondary mb-md">
                  请点击上方按钮触发公网自动检索，或将 CNIPR 官方检索结果批量导入。
                </p>
              </div>
            )}
          </div>
        )}
      </main>

      {/* CNIPR Handoff Package Modal */}
      <Modal
        isOpen={isHandoffModalOpen}
        title="CNIPR 官方专利检索人工交接规范包"
        onClose={() => setIsHandoffModalOpen(false)}
      >
        <div className="flex-stack gap-sm">
          <p className="text-xs text-secondary">
            根据合规要求，CNIPR 检索需由代理师在官方系统人工执行。您可复制下方检索式或完整交接文档：
          </p>

          <div className="p-xs bg-subtle rounded">
            <div className="flex-between mb-xs">
              <span className="text-xs font-bold">CNIPR 推荐高级检索式：</span>
              <button
                type="button"
                className="btn btn-secondary btn-xs"
                onClick={() => handleCopyQuery(handoffData?.raw_cnipr_query || '')}
              >
                {copied ? '已复制！' : '复制检索式'}
              </button>
            </div>
            <code className="text-xs font-mono break-all">{handoffData?.raw_cnipr_query}</code>
          </div>

          <div className="form-group">
            <label className="form-label text-xs">规范交接文档 (Markdown 预览)：</label>
            <textarea
              className="input-text font-mono text-xs"
              rows={10}
              readOnly
              value={handoffData?.markdown || ''}
            />
          </div>

          <div className="modal-actions mt-sm flex-between">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => handleCopyQuery(handoffData?.markdown || '')}
            >
              复制完整交接 Markdown
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setIsHandoffModalOpen(false)}
            >
              完成并关闭
            </button>
          </div>
        </div>
      </Modal>

      {/* Import CNIPR Results Modal */}
      <Modal
        isOpen={isImportModalOpen}
        title="导入 CNIPR 官方检索结果"
        onClose={() => setIsImportModalOpen(false)}
      >
        <form onSubmit={handleImportCniprSubmit} className="form-stack">
          <p className="text-xs text-secondary">
            支持直接粘贴 CNIPR 官方导出的 CSV 内容，或按行粘贴专利公开号（如 CN118000123A）：
          </p>
          <textarea
            className="input-text font-mono text-xs"
            rows={8}
            placeholder="公开号,发明名称,摘要,公开日,申请人,IPC分类号&#10;CN117283912A,大模型加速系统,摘要内容...,2024-03-15,智能研究院,G06N 3/08"
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            required
          />

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsImportModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={actionLoading}>
              {actionLoading ? '正在导入并去重...' : '确认导入'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Exclude Candidate Modal */}
      <Modal
        isOpen={isExcludeModalOpen}
        title="排除候选专利并记录原因"
        onClose={() => setIsExcludeModalOpen(false)}
      >
        <form onSubmit={handleTriageExcludeSubmit} className="form-stack">
          <p className="text-xs text-secondary mb-xs">
            排除专利：<strong>{excludeTarget?.publication_number}</strong>（{excludeTarget?.title}）
          </p>

          <div className="form-group">
            <label className="form-label">排除原因标签</label>
            <select
              className="input-select"
              value={excludeReason}
              onChange={(e) => setExcludeReason(e.target.value)}
            >
              <option value="技术领域不符">技术领域不符</option>
              <option value="缺乏关键特征F1">缺乏关键特征 F1 (前序方案不一致)</option>
              <option value="缺乏关键特征F2">缺乏关键特征 F2 (核心表征手段缺失)</option>
              <option value="缺乏关键从属特征">缺乏关键从属特征</option>
              <option value="公开日在申请日之后">公开日在申请日之后 (非现有技术)</option>
              <option value="常规技术手段/非有效对比文件">常规技术手段 / 非有效对比文件</option>
              <option value="其他">其他自定义原因</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">排除详细说明 / 代理师备注</label>
            <textarea
              className="input-text"
              rows={3}
              value={excludeNotes}
              onChange={(e) => setExcludeNotes(e.target.value)}
              placeholder="简要记录排除的技术理由，以便后续生成查新检索排除过程证据链..."
            />
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsExcludeModalOpen(false)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-danger" disabled={actionLoading}>
              确认排除
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
