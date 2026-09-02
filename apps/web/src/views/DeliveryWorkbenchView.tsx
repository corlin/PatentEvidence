import React, { useEffect, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { StatusBadge } from '../components/StatusBadge'
import { MarkdownViewer } from '../components/MarkdownViewer'
import { CaseWorkflowStepper } from '../components/CaseWorkflowStepper'
import type { DeliveryRecord, EvidenceSnapshotDetail, CaseDetail } from '../types/api'
import { Link } from '../router/Router'

interface DeliveryWorkbenchViewProps {
  orgId: string
  caseId: string
}

export const DeliveryWorkbenchView: React.FC<DeliveryWorkbenchViewProps> = ({
  orgId,
  caseId,
}) => {
  const [currentCase, setCurrentCase] = useState<CaseDetail | null>(null)
  const [deliveryRecord, setDeliveryRecord] = useState<DeliveryRecord | null>(null)
  const [reportDetail, setReportDetail] = useState<EvidenceSnapshotDetail | null>(null)

  const [clientRecipient, setClientRecipient] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [cRes, dlvRes, repRes] = await Promise.all([
        apiClient.getCase(orgId, caseId),
        apiClient.getDeliveryRecord(orgId, caseId).catch(() => ({ delivery: null })),
        apiClient.getActiveReport(orgId, caseId).catch(() => null),
      ])

      setCurrentCase(cRes)
      setDeliveryRecord(dlvRes.delivery)
      setReportDetail(repRes)
      if (dlvRes.delivery?.client_recipient) {
        setClientRecipient(dlvRes.delivery.client_recipient)
      }
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('加载交付数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [orgId, caseId])

  const handleDeliver = async () => {
    if (!clientRecipient.trim()) {
      setError('请输入客户或委托人接收方名称')
      return
    }

    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.deliverCase(orgId, caseId, clientRecipient.trim())
      setDeliveryRecord(res.delivery)
      setSuccess('🎉 案件已正式完成客户交付！交付凭证与防伪下载口令已生成。')
      await loadData()
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('执行交付失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDownloadReport = () => {
    if (!reportDetail?.report?.content) return
    const blob = new Blob([reportDetail.report.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${currentCase?.case_number || 'patent'}_可专利性分析评估报告.md`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const isDelivered = currentCase?.status === 'delivered' || !!deliveryRecord

  return (
    <div className="layout-container">
      <Header />

      <main className="main-content">
        {/* Navigation Breadcrumb */}
        <div className="breadcrumb text-xs text-secondary mb-xs">
          <Link to={`/organizations/${orgId}/cases`}>案件列表</Link> &gt;{' '}
          <Link to={`/organizations/${orgId}/cases/${caseId}`}>
            {currentCase?.case_number || '案件详情'}
          </Link>{' '}
          &gt;{' '}
          <Link to={`/organizations/${orgId}/cases/${caseId}/review`}>独立复核</Link> &gt;{' '}
          📦 交付网关
        </div>

        {/* Page Header */}
        <div className="page-header flex-between mb-md">
          <div>
            <div className="flex-row gap-sm mb-xs">
              <span className="badge badge-neutral font-mono">{currentCase?.case_number}</span>
              <span className="badge badge-neutral">{currentCase?.target_jurisdiction || 'CN'}</span>
              <StatusBadge status={currentCase?.status || 'draft'} />
            </div>
            <h1 className="page-title text-2xl font-bold">
              {isDelivered ? '🏛️ 已交付合规证书 (Delivery Certificate)' : '📦 案件交付与归档准备'}
            </h1>
            <p className="text-secondary text-sm">
              案件：<strong>{currentCase?.title}</strong> ({currentCase?.case_number})
            </p>
          </div>

          <div className="actions flex-row gap-sm">
            <button
              type="button"
              onClick={handleDownloadReport}
              disabled={!reportDetail?.report}
              className="btn btn-primary btn-sm"
            >
              📥 导出 Markdown 报告
            </button>
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/review`}
              className="btn btn-secondary btn-sm"
            >
              &larr; 返回复核工作台
            </Link>
          </div>
        </div>

        {/* Workflow Lifecycle Stepper */}
        <CaseWorkflowStepper
          orgId={orgId}
          caseId={caseId}
          currentStep="delivery"
          caseStatus={currentCase?.status}
        />

        {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
        {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

        {/* Certificate / Snapshot Info Card */}
        <div className={`card p-md mb-md ${isDelivered ? 'border-l-4 border-green-500 bg-green-50' : ''}`}>
          <div className="flex-between align-center mb-sm">
            <div className="flex-row gap-sm align-center">
              <span className={`badge ${isDelivered ? 'badge-success' : 'badge-neutral'} font-bold`}>
                {isDelivered ? '✓ 最终交付已锁定 (Delivered)' : '⏳ 待正式交付'}
              </span>
              <span className="text-xs text-secondary">
                {isDelivered
                  ? `交付于：${deliveryRecord?.delivered_at ? new Date(deliveryRecord.delivered_at).toLocaleString('zh-CN') : ''}`
                  : '复核已批准，请确认接收方并完成归档'}
              </span>
            </div>
          </div>

          <div className="grid-3-cols gap-md p-md bg-surface border rounded mt-sm">
            <div className="min-w-0">
              <span className="text-xs text-secondary block mb-xs font-semibold">不可变 Merkle Root SHA-256</span>
              <div className="font-mono text-xs font-bold text-text break-all bg-subtle p-xs rounded border">
                {deliveryRecord?.root_sha256 || reportDetail?.snapshot.root_sha256 || '待生成'}
              </div>
            </div>

            <div className="min-w-0">
              <span className="text-xs text-secondary block mb-xs font-semibold">客户接收方 (Client Recipient)</span>
              <div className="text-xs font-semibold text-text bg-subtle p-xs rounded border">
                {deliveryRecord?.client_recipient || '尚未登记'}
              </div>
            </div>

            <div className="min-w-0">
              <span className="text-xs text-secondary block mb-xs font-semibold">防伪下载口令 (Token)</span>
              <div className="font-mono text-xs text-secondary bg-subtle p-xs rounded border">
                {deliveryRecord?.download_token || '交付后自动生成'}
              </div>
            </div>
          </div>
        </div>

        {/* Action Panel for Undelivered Cases */}
        {!isDelivered ? (
          <div className="card p-md mb-md">
            <h2 className="text-md font-bold mb-xs">✍️ 登记客户接收信息并执行正式交付</h2>
            <p className="text-xs text-secondary mb-md">
              正式交付后，系统将锁定全案证据链并生成专有的防伪交付凭证。
            </p>

            <div className="flex-stack gap-md max-w-lg">
              <div className="form-group">
                <label className="form-label text-xs font-bold mb-xs">
                  客户或委托人全称 (Client Organization / Recipient)
                </label>
                <input
                  type="text"
                  value={clientRecipient}
                  onChange={(e) => setClientRecipient(e.target.value)}
                  placeholder="例如：苏州精工仿生机器人科技有限公司 / 李总工程师"
                  className="form-input text-xs"
                />
              </div>

              <button
                type="button"
                onClick={handleDeliver}
                disabled={actionLoading}
                className="btn btn-primary btn-sm font-bold"
              >
                {actionLoading ? '交付处理中...' : '📦 确认正式交付客户 (Mark as Delivered)'}
              </button>
            </div>
          </div>
        ) : (
          <div className="card p-md mb-md border-l-4 border-green-500 bg-green-50">
            <div className="flex-row gap-md align-center">
              <span className="text-2xl">🎉</span>
              <div>
                <h3 className="text-sm font-bold text-success mb-xs">
                  本案已正式交付向客户【{deliveryRecord?.client_recipient}】
                </h3>
                <p className="text-xs text-secondary">
                  技术交底书、说明书附图、检索策略、Claim Chart 对比矩阵与评估报告均已完成防篡改封存。
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Final Report Full Preview */}
        <div className="card p-md">
          <div className="flex-between align-center mb-sm">
            <h2 className="text-md font-bold">📜 正式交付报告全文 (Final Approved Report)</h2>
            <button
              type="button"
              onClick={handleDownloadReport}
              disabled={!reportDetail?.report}
              className="btn btn-secondary btn-xs"
            >
              📥 导出报告 (.md)
            </button>
          </div>

          {reportDetail?.report ? (
            <div className="p-md bg-surface border rounded">
              <MarkdownViewer content={reportDetail.report.content} />
            </div>
          ) : (
            <div className="p-lg text-center text-secondary text-sm">
              暂无可预览的报告内容
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
