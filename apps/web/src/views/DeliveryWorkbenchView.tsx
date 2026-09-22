import React, { useEffect, useState } from 'react'
import { Icon } from '../components/Icon'
import { apiClient, ApiError } from '../services/apiClient'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import { StatusBadge } from '../components/StatusBadge'
import { MarkdownViewer } from '../components/MarkdownViewer'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type {
  DeliveryRecord,
  EvidenceSnapshotDetail,
  CaseDetail,
  AssessmentDeliverable,
} from '../types/api'
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
  // 交付包清单里的预评估意见附件（候选，非结论）；可勾选表示是否纳入本次交付包
  const [assessmentAttachment, setAssessmentAttachment] =
    useState<AssessmentDeliverable | null>(null)
  const [includeAssessment, setIncludeAssessment] = useState(true)

  const [clientRecipient, setClientRecipient] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  // P0：正式交付会锁定全案证据链并生成防伪凭证，执行前必须显式二次确认
  const [showDeliverConfirm, setShowDeliverConfirm] = useState(false)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [cRes, dlvRes, repRes, attRes] = await Promise.all([
        apiClient.getCase(orgId, caseId),
        apiClient.getDeliveryRecord(orgId, caseId).catch(() => ({ delivery: null })),
        apiClient.getActiveReport(orgId, caseId).catch(() => null),
        apiClient
          .getAssessmentDeliveryAttachment(orgId, caseId)
          .catch(() => ({ attachment: null })),
      ])

      setCurrentCase(cRes)
      setDeliveryRecord(dlvRes.delivery)
      setReportDetail(repRes)
      setAssessmentAttachment(attRes.attachment)
      // 未达门禁（attachable=false）时默认不勾选，避免把候选悄悄当作可交付件
      setIncludeAssessment(attRes.attachment?.attachable === true)
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
    setShowDeliverConfirm(false)
    try {
      const res = await apiClient.deliverCase(orgId, caseId, clientRecipient.trim())
      setDeliveryRecord(res.delivery)
      setSuccess('案件已正式完成客户交付！交付凭证与防伪下载口令已生成。')
      await loadData()
    } catch (err) {
      if (err instanceof ApiError) {
        // 案件交付门禁：后端拒绝时给出明确原因，绝不乐观默认
        setError(
          err.detail === 'assessment_delivery_gate_not_satisfied'
            ? '案件交付门禁未满足：须存在「已批准且无阻塞项」的预评估版本，才能执行正式交付。'
            : err.message
        )
      } else setError('执行交付失败')
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
  // 案件交付门禁：与后端 assert_delivery_gate 同口径——仅当存在「已批准且无阻塞项」
  // 的预评估版本（attachable=true）时才允许执行不可逆的正式交付。
  const deliveryGateSatisfied = assessmentAttachment?.attachable === true

  return (
    <WorkbenchLayout
      currentStep="delivery"
      caseStatus={currentCase?.status}
      orgId={orgId}
      caseId={caseId}
      title={isDelivered ? '已交付合规证书 (Delivery Certificate)' : '案件交付与归档准备'}
      description={`案件：${currentCase?.title || ''} (${currentCase?.case_number || ''})`}
      breadcrumbCurrent="交付网关"
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
      headerActions={
        <>
          <button
            type="button"
            onClick={handleDownloadReport}
            disabled={!reportDetail?.report}
            className="btn btn-primary btn-sm"
          >
            <Icon name="download" size={14} /> 导出 Markdown 报告
          </button>
          <Link
            to={`/organizations/${orgId}/cases/${caseId}/review`}
            className="btn btn-secondary btn-sm"
          >
            &larr; 返回复核工作台
          </Link>
        </>
      }
    >

        {/* Certificate / Snapshot Info Card */}
        <div className={`card p-md mb-md ${isDelivered ? 'border-l-4 border-green-500 bg-green-50' : ''}`}>
          <div className="flex-between align-center mb-sm">
            <div className="flex-row gap-sm align-center">
              <span className={`badge ${isDelivered ? 'badge-success' : 'badge-neutral'} font-bold`}>
                {isDelivered ? '✓ 最终交付已锁定 (Delivered)' : '待正式交付'}
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
            <h2 className="text-md font-bold mb-xs"><Icon name="sign" size={14} /> 登记客户接收信息并执行正式交付</h2>
            <p className="text-xs text-secondary mb-md">
              正式交付后，系统将锁定全案证据链并生成专有的防伪交付凭证。
            </p>

            {/* 案件交付门禁：未满足时明确说明原因并禁用不可逆的交付动作 */}
            {!deliveryGateSatisfied && (
              <div className="alert alert-warning mb-md">
                <div className="alert-content">
                  <strong>案件交付门禁未满足</strong>：须存在「已批准且无阻塞项」的预评估版本，
                  才能执行正式交付。
                  {assessmentAttachment
                    ? ` 当前最新版本（v${assessmentAttachment.version_number}，${assessmentAttachment.status_label}）未达门禁。`
                    : ' 本案尚未创建任何预评估版本。'}
                </div>
              </div>
            )}

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
                onClick={() => setShowDeliverConfirm(true)}
                disabled={actionLoading || !deliveryGateSatisfied}
                title={
                  deliveryGateSatisfied
                    ? undefined
                    : '案件交付门禁未满足：须存在已批准且无阻塞项的预评估版本'
                }
                className="btn btn-primary btn-sm font-bold"
              >
                {actionLoading
                  ? '交付处理中...'
                  : deliveryGateSatisfied
                    ? '确认正式交付客户 (Mark as Delivered)'
                    : '交付门禁未满足，暂不可交付'}
              </button>
            </div>
          </div>
        ) : (
          <div className="card p-md mb-md border-l-4 border-green-500 bg-green-50">
            <div className="flex-row gap-md align-center">
              <span className="text-2xl"><Icon name="sparkle" size={14} /></span>
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

        {/* Delivery Package Manifest: attachable pre-assessment opinion (candidate, non-conclusion) */}
        <div className="card p-md mb-md">
          <div className="flex-between align-center mb-sm">
            <h2 className="text-md font-bold"><Icon name="scroll" size={14} /> 交付包清单（预评估意见附件）</h2>
            {assessmentAttachment && (
              <span
                className={`badge ${
                  assessmentAttachment.attachable ? 'badge-success' : 'badge-neutral'
                }`}
              >
                {assessmentAttachment.attachable ? '已达门禁，可纳入交付包' : '未达门禁，不可纳入'}
              </span>
            )}
          </div>

          {assessmentAttachment ? (
            <>
              <label className="flex-row gap-sm align-center mb-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeAssessment}
                  disabled={!assessmentAttachment.attachable}
                  onChange={(e) => setIncludeAssessment(e.target.checked)}
                />
                <span className="text-sm font-semibold">
                  预评估意见 v{assessmentAttachment.version_number}（候选，非结论）
                </span>
                {!assessmentAttachment.attachable && assessmentAttachment.attachment_reason && (
                  <span className="text-xs text-secondary">
                    {assessmentAttachment.attachment_reason}
                  </span>
                )}
              </label>

              <div className="grid-3-cols gap-md p-md bg-surface border rounded">
                <div className="min-w-0">
                  <span className="text-xs text-secondary block mb-xs font-semibold">
                    内容摘要 SHA-256 (payload)
                  </span>
                  <div className="font-mono text-xs break-all bg-subtle p-xs rounded border">
                    {assessmentAttachment.payload_sha256}
                  </div>
                </div>
                <div className="min-w-0">
                  <span className="text-xs text-secondary block mb-xs font-semibold">
                    规则版本 (rules_version)
                  </span>
                  <div className="font-mono text-xs bg-subtle p-xs rounded border">
                    {assessmentAttachment.rules_version}
                  </div>
                </div>
                <div className="min-w-0">
                  <span className="text-xs text-secondary block mb-xs font-semibold">
                    复核状态 / 候选发布门禁
                  </span>
                  <div className="text-xs bg-subtle p-xs rounded border">
                    {assessmentAttachment.status_label} ——{' '}
                    {assessmentAttachment.eligibility.eligible
                      ? '允许发布候选判断'
                      : '不允许发布候选判断'}
                  </div>
                </div>
              </div>

              <div className="alert alert-warning mt-sm">
                <div className="alert-content text-xs">{assessmentAttachment.candidate_notice}</div>
              </div>
            </>
          ) : (
            <div className="p-md text-center text-secondary text-sm bg-surface border rounded">
              尚未创建任何预评估版本，无可挂接的预评估意见。
            </div>
          )}
        </div>

        {/* Final Report Full Preview */}
        <div className="card p-md">
          <div className="flex-between align-center mb-sm">
            <h2 className="text-md font-bold"><Icon name="scroll" size={14} /> 正式交付报告全文 (Final Approved Report)</h2>
            <button
              type="button"
              onClick={handleDownloadReport}
              disabled={!reportDetail?.report}
              className="btn btn-secondary btn-xs"
            >
              <Icon name="download" size={14} /> 导出报告 (.md)
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

        {/* P0：正式交付锁定的不可逆二次确认 */}
        <ConfirmDialog
          isOpen={showDeliverConfirm}
          title="确认正式交付并锁定全案？"
          danger
          confirmLabel="确认交付并生成凭证"
          loading={actionLoading}
          onCancel={() => setShowDeliverConfirm(false)}
          onConfirm={handleDeliver}
        >
          <p>
            正式交付后，系统将锁定全案证据链（技术交底、附图、检索策略、Claim Chart
            与评估报告），并向客户【<strong>{clientRecipient.trim() || '未命名接收方'}</strong>】生成专属防伪交付凭证与下载口令。
          </p>
          <p className="text-xs text-secondary mt-xs">
            此操作<b>不可撤销</b>：交付状态与凭证将永久记录，全案不可再退回修改。
          </p>
        </ConfirmDialog>
    </WorkbenchLayout>
  )
}
