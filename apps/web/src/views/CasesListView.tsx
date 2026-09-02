import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import type { CaseSummary, CreateCasePayload } from '../types/api'
import { Link, useNavigate } from '../router/Router'

interface CasesListViewProps {
  orgId: string
}

export const CasesListView: React.FC<CasesListViewProps> = ({ orgId }) => {
  const { requestMfaStepUp } = useSession()
  const navigate = useNavigate()

  const [cases, setCases] = useState<CaseSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Create Case Modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [createForm, setCreateForm] = useState<CreateCasePayload>({
    case_number: '',
    title: '',
    technical_field: '计算机与人工智能',
    target_jurisdiction: 'CN',
  })
  const [createLoading, setCreateLoading] = useState(false)

  const fetchCases = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.listCases(orgId)
      setCases(res.items)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) {
        requestMfaStepUp(fetchCases)
      } else {
        setError(err.detail || '加载案件列表失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCases()
  }, [orgId])

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreateLoading(true)
    setError(null)

    try {
      const res = await apiClient.createCase(orgId, {
        ...createForm,
        case_number: createForm.case_number.trim(),
        title: createForm.title.trim(),
        technical_field: createForm.technical_field.trim(),
      })
      setIsCreateModalOpen(false)
      setSuccess(`案件“${res.case.title} (${res.case.case_number})”创建成功！`)
      fetchCases()
      navigate(`/organizations/${orgId}/cases/${res.case.id}`)
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError(`案号“${createForm.case_number}”在本机构中已存在，请使用唯一案号。`)
        } else if (err.status === 422 && err.detail.includes('quota')) {
          setError('操作被拒绝：本机构本月案件配额已耗尽，请联系平台管理员扩容。')
        } else {
          setError(err.detail || '创建案件失败')
        }
      } else {
        setError('网络连接异常，请重试。')
      }
    } finally {
      setCreateLoading(false)
    }
  }

  return (
    <div className="layout-container">
      <Header />

      <main className="main-content">
        <div className="page-header flex-between mb-md">
          <div>
            <div className="breadcrumb text-xs text-secondary mb-xs">
              <Link to={`/organizations/${orgId}/members`}>机构成员</Link> &gt; 案件工作台
            </div>
            <h1 className="page-title text-2xl font-bold">专利评估案件列表</h1>
            <p className="text-secondary text-sm">
              管理技术交底书导入、文档结构化解析与可专利性预评估报告
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setError(null)
              setIsCreateModalOpen(true)
            }}
          >
            + 新建评估案件
          </button>
        </div>

        {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
        {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

        <div className="card table-card">
          {loading ? (
            <div className="p-lg text-center text-secondary">正在加载案件数据...</div>
          ) : cases.length === 0 ? (
            <div className="empty-state p-xl text-center">
              <p className="text-secondary mb-sm">暂无专利评估案件记录</p>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setIsCreateModalOpen(true)}
              >
                立即建立首个评估案件
              </button>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>案号 / 标题</th>
                  <th>技术领域</th>
                  <th>目标法域</th>
                  <th>当前状态</th>
                  <th>创建时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <div className="case-title-block">
                        <Link
                          to={`/organizations/${orgId}/cases/${c.id}`}
                          className="font-medium text-primary text-sm"
                        >
                          {c.title}
                        </Link>
                        <span className="text-xs text-secondary block font-mono">
                          {c.case_number}
                        </span>
                      </div>
                    </td>
                    <td className="text-sm">{c.technical_field}</td>
                    <td>
                      <span className="badge badge-neutral text-xs font-mono">
                        {c.target_jurisdiction}
                      </span>
                    </td>
                    <td>
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="text-xs text-secondary">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                    <td className="text-right">
                      <Link
                        to={`/organizations/${orgId}/cases/${c.id}`}
                        className="btn btn-secondary btn-xs"
                      >
                        进入工作台 →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* Create Case Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        title="新建专利预评估案件"
        onClose={() => setIsCreateModalOpen(false)}
      >
        <form onSubmit={handleCreateSubmit} className="form-stack">
          <div className="form-group">
            <label className="form-label">机构内部案号</label>
            <input
              type="text"
              className="input-text"
              value={createForm.case_number}
              onChange={(e) => setCreateForm({ ...createForm, case_number: e.target.value })}
              placeholder="例如：2026-PAT-001"
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label">发明/交底书标题</label>
            <input
              type="text"
              className="input-text"
              value={createForm.title}
              onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
              placeholder="例如：基于混合注意力机制的大语言模型量化推理方法"
              required
            />
          </div>

          <div className="grid-2-cols gap-sm">
            <div className="form-group">
              <label className="form-label">技术领域</label>
              <input
                type="text"
                className="input-text"
                value={createForm.technical_field}
                onChange={(e) =>
                  setCreateForm({ ...createForm, technical_field: e.target.value })
                }
                placeholder="例如：计算机软件 / 人工智能"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">目标法域</label>
              <select
                className="input-select"
                value={createForm.target_jurisdiction}
                onChange={(e) =>
                  setCreateForm({ ...createForm, target_jurisdiction: e.target.value })
                }
              >
                <option value="CN">中国大陆 (CN)</option>
                <option value="EP">欧洲专利局 (EP)</option>
                <option value="US">美国专利商标局 (US)</option>
                <option value="WO">PCT 国际申请 (WO)</option>
              </select>
            </div>
          </div>

          <div className="modal-actions mt-md">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsCreateModalOpen(false)}
              disabled={createLoading}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={createLoading}>
              {createLoading ? '正在创建...' : '确认创建'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
