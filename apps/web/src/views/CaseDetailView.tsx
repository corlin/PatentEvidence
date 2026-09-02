import React, { useEffect, useRef, useState } from 'react'
import { apiClient, ApiError } from '../services/apiClient'
import { useSession } from '../context/SessionContext'
import { Alert } from '../components/Alert'
import { Header } from '../components/Header'
import { StatusBadge } from '../components/StatusBadge'
import { DrawingsGallery } from '../components/DrawingsGallery'
import { WorkbenchLayout } from '../components/WorkbenchLayout'
import type { CaseDetail, ParagraphBlock } from '../types/api'
import { Link } from '../router/Router'

interface CaseDetailViewProps {
  orgId: string
  caseId: string
}

export const CaseDetailView: React.FC<CaseDetailViewProps> = ({ orgId, caseId }) => {
  const { requestMfaStepUp } = useSession()

  const [caseData, setCaseData] = useState<CaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Upload state
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Confirming state
  const [confirming, setConfirming] = useState(false)

  const fetchCaseDetail = async () => {
    try {
      const data = await apiClient.getCase(orgId, caseId)
      setCaseData(data)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 403) {
        requestMfaStepUp(fetchCaseDetail)
      } else {
        setError(err.detail || '加载案件详情失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCaseDetail()
  }, [orgId, caseId])

  // Polling for parse runs
  useEffect(() => {
    if (!caseData?.parse_run) return
    const status = caseData.parse_run.status
    if (status === 'queued' || status === 'running') {
      const timer = setTimeout(() => {
        fetchCaseDetail()
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [caseData?.parse_run?.status])

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const file = files[0]
    setUploading(true)
    setError(null)
    setSuccess(null)

    try {
      await apiClient.uploadDocument(orgId, caseId, file)
      setSuccess(`文件“${file.name}”已成功上传，正在执行后台安全解析...`)
      fetchCaseDetail()
    } catch (err: any) {
      if (err instanceof ApiError) {
        setError(err.detail || '文件上传失败')
      } else {
        setError('文件上传失败，请检查网络连接')
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleConfirmVersion = async (versionId: string) => {
    setConfirming(true)
    setError(null)
    try {
      await apiClient.confirmDocumentVersion(orgId, caseId, versionId)
      setSuccess('已成功确认文档解析版本！案件状态已推进为【文档就绪】。')
      fetchCaseDetail()
    } catch (err: any) {
      if (err instanceof ApiError) {
        setError(err.detail || '确认文档版本失败')
      } else {
        setError('确认失败，请稍后重试')
      }
    } finally {
      setConfirming(false)
    }
  }

  if (loading) {
    return (
      <div className="layout-container">
        <Header currentOrgName="案件详情" />
        <main className="main-content p-xl text-center text-secondary">正在加载案件详情...</main>
      </div>
    )
  }

  if (!caseData) {
    return (
      <div className="layout-container">
        <Header currentOrgName="案件详情" />
        <main className="main-content p-xl">
          <Alert type="error" message={error || '案件不存在或您无权访问'} />
          <Link to={`/organizations/${orgId}/cases`} className="btn btn-secondary mt-md">
            &larr; 返回案件列表
          </Link>
        </main>
      </div>
    )
  }

  // Parse paragraphs if available
  let paragraphs: ParagraphBlock[] = []
  if (caseData.document_version?.structure_json) {
    if (typeof caseData.document_version.structure_json === 'string') {
      try {
        paragraphs = JSON.parse(caseData.document_version.structure_json)
      } catch {
        paragraphs = []
      }
    } else if (Array.isArray(caseData.document_version.structure_json)) {
      paragraphs = caseData.document_version.structure_json as ParagraphBlock[]
    }
  }

  return (
    <WorkbenchLayout
      currentStep="intake"
      caseStatus={caseData.status}
      orgId={orgId}
      caseId={caseId}
      title={caseData.title}
      description={`技术领域：${caseData.technical_field}`}
      breadcrumbCurrent={caseData.case_number}
      error={error}
      success={success}
      onErrorClose={() => setError(null)}
      onSuccessClose={() => setSuccess(null)}
      headerActions={
        <>
          {caseData.status === 'draft' || caseData.status === 'document_ready' ? (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/features`}
              className="btn btn-primary btn-sm font-bold"
            >
              ⚡ 进入技术特征建模 &rarr;
            </Link>
          ) : caseData.status === 'evidence_ready' ? (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/search`}
              className="btn btn-primary btn-sm font-bold"
            >
              🔍 前往检索与候选初筛 &rarr;
            </Link>
          ) : caseData.status === 'assessment_ready' ? (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/comparisons`}
              className="btn btn-primary btn-sm font-bold"
            >
              📊 进入 Claim Chart 深度比对 &rarr;
            </Link>
          ) : caseData.status === 'in_review' || caseData.status === 'changes_requested' ? (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/review`}
              className="btn btn-primary btn-sm font-bold"
            >
              ⚖️ 独立复核审批 &rarr;
            </Link>
          ) : (
            <Link
              to={`/organizations/${orgId}/cases/${caseId}/delivery`}
              className="btn btn-primary btn-sm font-bold"
            >
              📦 客户交付与证书网关 &rarr;
            </Link>
          )}

          <Link to={`/organizations/${orgId}/cases`} className="btn btn-secondary btn-sm">
            &larr; 返回案件列表
          </Link>
        </>
      }
    >

        {/* Upload & Parsing Section */}
        <div className="grid-2-cols gap-md mb-md">
          {/* Upload Card */}
          <div className="card p-md">
            <h2 className="text-md font-bold mb-xs">交底书 / 申请文件上传</h2>
            <p className="text-xs text-secondary mb-md">
              支持 DOCX 或文字版 PDF 文件（单文件最大 30MB）。系统将自动执行安全哈希并提取段落结构。
            </p>

            <div className="upload-box p-md border rounded text-center">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".docx,.pdf"
                className="hidden"
                style={{ display: 'none' }}
                id="document-upload-input"
                disabled={uploading}
              />
              <label htmlFor="document-upload-input" className="btn btn-primary btn-sm pointer">
                {uploading ? '正在上传与校验...' : '选择 DOCX / PDF 文件'}
              </label>
              {caseData.document && (
                <div className="mt-sm text-xs text-secondary">
                  当前文件：<strong>{caseData.document.filename}</strong> (
                  {(caseData.document.file_size / 1024).toFixed(1)} KB)
                  <br />
                  <span className="font-mono text-xs">SHA-256: {caseData.document.sha256}</span>
                </div>
              )}
            </div>
          </div>

          {/* Parse Status Card */}
          <div className="card p-md">
            <h2 className="text-md font-bold mb-xs">文档解析状态</h2>
            {caseData.parse_run ? (
              <div className="parse-status-box">
                <div className="flex-row gap-sm mb-xs">
                  <span className="text-sm font-medium">任务状态：</span>
                  <StatusBadge status={caseData.parse_run.status} />
                </div>
                {caseData.parse_run.status === 'running' && (
                  <p className="text-xs text-primary animate-pulse">
                    Worker 正在解析文档标题、段落及表格结构...
                  </p>
                )}
                {caseData.parse_run.status === 'failed' && (
                  <p className="text-xs text-danger">
                    解析失败：{caseData.parse_run.error_summary}
                  </p>
                )}
                {caseData.parse_run.status === 'completed' && (
                  <p className="text-xs text-success">✓ 结构化段落解析完成</p>
                )}
                <div className="text-xs text-secondary mt-xs">
                  任务创建时间：{new Date(caseData.parse_run.created_at).toLocaleString()}
                </div>
              </div>
            ) : (
              <div className="p-md text-center text-secondary text-sm">
                尚未上传交底书文件。请先在左侧上传文件。
              </div>
            )}
          </div>
        </div>

        {/* Structured Document Preview */}
        {caseData.document_version && (
          <div className="card p-md mb-md">
            <div className="flex-between mb-md">
              <div>
                <h2 className="text-lg font-bold">结构化交底书原文预览</h2>
                <div className="text-xs text-secondary font-mono mt-xs">
                  版本: v{caseData.document_version.version_number} | SHA-256:{' '}
                  {caseData.document_version.sha256}
                </div>
              </div>

              <div>
                {caseData.document_version.is_confirmed ? (
                  <span className="badge badge-success text-sm p-xs">✓ 已确认基准版本</span>
                ) : (
                  <button
                    type="button"
                    className="btn btn-success btn-sm"
                    onClick={() => handleConfirmVersion(caseData.document_version!.id)}
                    disabled={confirming}
                  >
                    {confirming ? '正在确认...' : '确认文档解析版本并推进'}
                  </button>
                )}
              </div>
            </div>

            {/* Paragraphs List */}
            <div className="paragraphs-container border rounded p-md bg-subtle">
              {paragraphs.length === 0 ? (
                <pre className="text-sm p-sm">{caseData.document_version.parsed_text}</pre>
              ) : (
                <div className="flex-stack gap-sm">
                  {paragraphs.map((p) => (
                    <div key={p.id} className="paragraph-block p-sm border rounded bg-surface">
                      <div className="flex-row gap-xs mb-xs">
                        <span className="badge badge-neutral text-xs font-mono">{p.id}</span>
                        <span className="badge badge-neutral text-xs">{p.section}</span>
                      </div>
                      <div className="paragraph-text text-sm">{p.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Patent Drawings Gallery */}
        <DrawingsGallery orgId={orgId} caseId={caseId} />
    </WorkbenchLayout>
  )
}
