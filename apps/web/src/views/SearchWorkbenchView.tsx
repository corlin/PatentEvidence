import React, { useEffect, useState } from 'react'
import { Icon } from '../components/Icon'
import { apiClient, ApiError, isMfaRequired } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
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

  // Key configuration modal
  const [isKeyConfigModalOpen, setIsKeyConfigModalOpen] = useState(false)
  const [keyModalSource, setKeyModalSource] = useState<'epo' | 'uspto'>('epo')
  const [customApiKey, setCustomApiKey] = useState('')
  const [customClientId, setCustomClientId] = useState('')
  const [customClientSecret, setCustomClientSecret] = useState('')

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
      } else if (isMfaRequired(err)) {
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
      if (isMfaRequired(err)) {
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

  const handleExecutePublicSearch = async (
    sourceType: string = 'openalex',
    keyConfig?: { apiKey?: string; clientId?: string; clientSecret?: string }
  ) => {
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.executePublicSearch(orgId, caseId, sourceType, keyConfig)
      const label =
        sourceType === 'epo'
          ? '欧洲专利局 (EPO OPS)'
          : sourceType === 'uspto'
          ? '美国专利商标局 (USPTO ODP)'
          : '全球公开源 (OpenAlex)'
      setSuccess(`${label} 检索执行完成，新增检索出 ${res.results_count} 篇候选文献！`)
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
    <WorkbenchLayout
      currentStep="search"
      caseStatus={candidates.some((c) => c.triage_status === 'included') ? 'assessment_ready' : 'evidence_ready'}
      orgId={orgId}
      caseId={caseId}
      title="专利检索规划与候选证据初筛"
      description="基于确认技术特征制定检索策略、导出 CNIPR 人工交接规范包并执行多路去重初筛"
      breadcrumbCurrent="专利检索与候选池"
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
      headerActions={
        <>
          {candidates.some((c) => c.triage_status === 'included') && (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/comparisons`}
              className="btn btn-primary btn-sm font-bold"
            >
              <Icon name="chart" size={14} /> 前往 Claim Chart 比对 &rarr;
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
        </>
      }
    >

        {/* Tab Navigation */}
        <div className="flex-row gap-md border-b mb-md">
          <button
            type="button"
            className={`tab-btn p-sm font-semibold ${
              activeTab === 'strategy' ? 'tab-active text-primary border-b-2 border-primary' : 'text-secondary'
            }`}
            onClick={() => setActiveTab('strategy')}
          >
            <Icon name="clipboard" size={14} /> 检索规划与 CNIPR 交接包
          </button>
          <button
            type="button"
            className={`tab-btn p-sm font-semibold ${
              activeTab === 'candidates' ? 'tab-active text-primary border-b-2 border-primary' : 'text-secondary'
            }`}
            onClick={() => setActiveTab('candidates')}
          >
            <Icon name="search" size={14} /> 多路检索与候选池初筛 ({candidates.length})
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
                      <Icon name="package" size={14} /> 导出 CNIPR 规范交接包
                    </button>
                    <div className="flex-row gap-xs align-center">
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleExecutePublicSearch('epo', customClientId && customClientSecret ? { clientId: customClientId, clientSecret: customClientSecret } : undefined)}
                        disabled={actionLoading}
                        title="查询欧洲专利局官方 OPS API"
                      >
                         触发 EPO 官方检索
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm px-xs"
                        onClick={() => {
                          setKeyModalSource('epo')
                          setIsKeyConfigModalOpen(true)
                        }}
                        title="配置专属 EPO 官方凭证"
                        aria-label="配置专属 EPO 官方凭证"
                      >
                        <Icon name="gear" size={14} />
                      </button>
                    </div>

                    <div className="flex-row gap-xs align-center">
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleExecutePublicSearch('uspto', customApiKey ? { apiKey: customApiKey } : undefined)}
                        disabled={actionLoading}
                        title="查询美国专利商标局官方 ODP API"
                      >
                        <Icon name="globe" size={14} /> 触发 USPTO 官方检索
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm px-xs"
                        onClick={() => {
                          setKeyModalSource('uspto')
                          setIsKeyConfigModalOpen(true)
                        }}
                        title="配置专属 USPTO 官方凭证"
                        aria-label="配置专属 USPTO 官方凭证"
                      >
                        <Icon name="gear" size={14} />
                      </button>
                    </div>

                    <button
                      type="button"
                      className="btn btn-success btn-sm"
                      onClick={() => handleExecutePublicSearch('openalex')}
                      disabled={actionLoading}
                      title="直连 OpenAlex 全球开放学术与专利技术成果"
                    >
                      <Icon name="lightning" size={14} /> 执行公开源检索
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
                  {actionLoading ? '正在智能规划...' : '一键生成检索策略与 CNIPR 检索式'}
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
                  <Icon name="download" size={14} /> 导入 CNIPR 官方检索结果
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => handleExecutePublicSearch('google_patents')}
                  disabled={actionLoading}
                >
                  <Icon name="globe" size={14} /> 触发公网检索 (Google Patents)
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
                          {cand.source_type === 'cnipr_manual'
                            ? 'CNIPR人工导入'
                            : cand.source_type === 'epo'
                            ? ' EPO官方检索'
                            : cand.source_type === 'uspto'
                            ? 'USPTO官方检索'
                            : '公开源检索'}
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
                      <div className="flex-row gap-xs align-center">
                        <a
                          href={cand.raw_metadata?.google_patents_url || `https://patents.google.com/?q=${encodeURIComponent(cand.publication_number)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-secondary btn-xs"
                          title="在 Google Patents 官方图文库查看真实公开专利"
                        >
                          <Icon name="link" size={14} /> 谷歌专利查验 ↗
                        </a>
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
          <div className="flex-between align-center">
            <p className="text-xs text-secondary">
              支持直接粘贴 CNIPR 官方导出的 CSV 内容，或按行粘贴专利公开号：
            </p>
            <button
              type="button"
              className="btn btn-secondary btn-xs"
              onClick={() => {
                setImportText(`公开(公告)号,发明名称,申请人/专利权人,公开(公告)日,主分类号,摘要
CN117283912A,一种基于大语言模型的多尺度模型量化加速装置及系统,华为技术有限公司,2024-03-15,G06N 3/08,本发明公开了一种基于大语言模型的多尺度模型量化加速装置及系统。该装置包括：特征分析模块，用于获取大语言模型注意力机制中的激活值分布；奇异值分解模块，用于将动态高位宽张量投影为低秩敏感子空间与非敏感残差矩阵；混合精度量化单元，用于对敏感子空间保持FP8精度，对残差矩阵执行INT4非对称量化；稀疏查找表引擎，用于在硬件推理阶段通过跳零索引表直接完成解量化与张量点积运算。本方案大幅降低边缘设备显存占用并显著提升吞吐。
CN116549201B,面向深度神经网络的自适应稀疏矩阵量化计算方法与介质,百度在线网络技术(北京)有限公司,2023-11-20,G06F 17/16,针对大模型注意力层激活值动态范围大且硬件位宽固定的瓶颈，本发明提出一种面向深度神经网络的自适应稀疏矩阵量化计算方法。步骤包括：对多层感知机及注意力权重的极值奇异点进行行级分块敏感度评级；采用多位宽混合定点数自适应校准各块量化尺度因子；在硬件层构建位掩码解码流水线，只对非零稀疏有效权重进行脉动阵列计算。经实测在基本不损失困惑度（PPL）的前提下提升推理能效比2.8倍。
CN115830114A,一种端侧大模型混合精度量化推理加速方法与芯片,北京智谱华章科技有限公司,2023-03-21,G06N 3/04,本发明涉及一种端侧大模型混合精度量化推理加速方法与专用集成芯片。该芯片包括片上高带宽紧耦合SRAM和矢量矩阵乘法单元阵列。推理前通过敏感特征蒸馏确定每一层权重的非均匀量化网格；运行时由硬件专用量化控制器对输入张量实时进行动态通道缩放，并配合稀疏跳过逻辑仅调度有效乘加运算单元。本发明能够在手机或边缘嵌入式计算平台上流畅运行百亿参数规模语言模型。`)
              }}
              title="载入国知局真实 CSV 官方样例"
            >
              <Icon name="idea" size={14} /> 载入官方 CSV 样例
            </button>
          </div>
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

      {/* Key Configuration Modal */}
      <Modal
        isOpen={isKeyConfigModalOpen}
        title={keyModalSource === 'epo' ? '配置欧洲专利局 (EPO OPS) 官方凭证' : '配置美国专利商标局 (USPTO ODP) 官方凭证'}
        onClose={() => setIsKeyConfigModalOpen(false)}
      >
        <div className="form-stack">
          <p className="text-xs text-secondary">
            {keyModalSource === 'epo'
              ? 'EPO Open Patent Services 要求使用 Consumer Key (Client ID) 与 Secret。未配置时系统将自动安全降级至官方沙盒镜像。'
              : 'USPTO Open Data Portal 要求每个机构/用户独立的 X-API-KEY。未配置时系统将自动安全降级至官方沙盒镜像。'}
          </p>

          {keyModalSource === 'epo' ? (
            <>
              <div className="form-group">
                <label className="form-label text-xs">EPO Consumer Key (Client ID)</label>
                <input
                  type="text"
                  className="input-text text-xs font-mono"
                  placeholder="如：aBcDeFgHiJkLmNoP..."
                  value={customClientId}
                  onChange={(e) => setCustomClientId(e.target.value.trim())}
                />
              </div>
              <div className="form-group">
                <label className="form-label text-xs">EPO Consumer Secret</label>
                <input
                  type="password"
                  className="input-text text-xs font-mono"
                  placeholder="如：xYz123456789..."
                  value={customClientSecret}
                  onChange={(e) => setCustomClientSecret(e.target.value.trim())}
                />
              </div>
            </>
          ) : (
            <div className="form-group">
              <label className="form-label text-xs">USPTO API Key (X-API-KEY)</label>
              <input
                type="text"
                className="input-text text-xs font-mono"
                placeholder="从 data.uspto.gov/myodp 获取的专属 API Key"
                value={customApiKey}
                onChange={(e) => setCustomApiKey(e.target.value.trim())}
              />
            </div>
          )}

          <div className="modal-actions mt-md flex-between">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setIsKeyConfigModalOpen(false)}
            >
              取消
            </button>
            <div className="flex-row gap-xs">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => {
                  setIsKeyConfigModalOpen(false)
                  if (keyModalSource === 'epo') {
                    handleExecutePublicSearch('epo', customClientId && customClientSecret ? { clientId: customClientId, clientSecret: customClientSecret } : undefined)
                  } else {
                    handleExecutePublicSearch('uspto', customApiKey ? { apiKey: customApiKey } : undefined)
                  }
                }}
              >
                保存并立即检索
              </button>
            </div>
          </div>
        </div>
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
    </WorkbenchLayout>
  )
}
