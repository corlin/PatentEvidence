import React, { useEffect, useMemo, useState } from 'react'
import { apiClient } from '../services/apiClient'
import type { CaseDrawing, ReferenceMark } from '../types/api'
import { Modal } from './Modal'
import { Alert } from './Alert'

export function naturalSortMarks(marks: ReferenceMark[]): ReferenceMark[] {
  return [...marks].sort((a, b) => {
    const numA = parseInt(a.mark.replace(/[^0-9]/g, '')) || 0
    const numB = parseInt(b.mark.replace(/[^0-9]/g, '')) || 0
    return numA !== numB ? numA - numB : a.mark.localeCompare(b.mark)
  })
}

interface LinterIssue {
  type: string
  severity: 'warning' | 'info'
  mark: string
  message: string
}

function lintMarksInClient(drawings: CaseDrawing[]): LinterIssue[] {
  const issues: LinterIssue[] = []
  const markOccurrences: Record<string, { fig: string; name: string }[]> = {}

  for (const d of drawings) {
    for (const rm of d.reference_marks || []) {
      if (rm.mark && rm.name) {
        if (!markOccurrences[rm.mark]) markOccurrences[rm.mark] = []
        markOccurrences[rm.mark].push({ fig: d.figure_label, name: rm.name })
      }
    }
  }

  for (const [mk, items] of Object.entries(markOccurrences)) {
    const names = Array.from(new Set(items.map(i => i.name)))
    if (names.length > 1) {
      issues.push({
        type: 'naming_drift',
        severity: 'warning',
        mark: mk,
        message: `附图标记 ${mk} 在不同图纸中存在用词偏差（${items.slice(0, 3).map(i => `${i.fig}: ${i.name}`).join('；')}）`,
      })
    }
  }

  return issues
}

export const ReferenceMarkBadge: React.FC<{
  mark: ReferenceMark
  size?: 'sm' | 'md'
}> = ({ mark, size = 'md' }) => {
  const isClaim = Boolean(mark.is_claim_feature)
  const isIndep = Boolean(mark.is_independent)
  const claimNums = mark.claim_numbers || []
  const firstClaimNum = claimNums[0]

  let badgeClass = 'badge badge-subtle text-xs'
  let tagClass = 'badge-claim-tag'
  let tagText = '权'

  if (isClaim) {
    if (isIndep) {
      badgeClass += ' badge-claim-independent'
      tagClass = 'badge-claim-tag-independent'
      tagText = firstClaimNum ? `独权${firstClaimNum}` : '独权'
    } else {
      badgeClass += ' badge-claim-dependent'
      tagClass = 'badge-claim-tag-dependent'
      tagText = firstClaimNum ? `从权${firstClaimNum}` : '从权'
    }
  }

  const claimDesc = isClaim
    ? ` 【${isIndep ? '独立权利要求' : '从属权利要求'}${claimNums.length ? ` (第 ${claimNums.join(', ')} 条)` : ''}保护特征】`
    : ''

  const style =
    size === 'sm'
      ? { fontSize: '11px', padding: '2px 6px' }
      : { fontSize: '11px', padding: '4px 8px' }

  return (
    <span
      className={badgeClass}
      style={style}
      title={`附图标记 ${mark.mark}: ${mark.name}${claimDesc}`}
    >
      {isClaim && (
        <span className={tagClass} title={claimDesc || '权利要求核心保护特征'}>
          {tagText}
        </span>
      )}
      <strong className="text-primary">{mark.mark}</strong> {mark.name}
    </span>
  )
}

interface DrawingsGalleryProps {
  orgId: string
  caseId: string
  readOnly?: boolean
}

export const DrawingsGallery: React.FC<DrawingsGalleryProps> = ({
  orgId,
  caseId,
  readOnly = false,
}) => {
  const [drawings, setDrawings] = useState<CaseDrawing[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [reExtracting, setReExtracting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Lightbox view state
  const [selectedDrawing, setSelectedDrawing] = useState<CaseDrawing | null>(null)
  const [zoomLevel, setZoomLevel] = useState<number>(1)
  const [markFilter, setMarkFilter] = useState<string>('')
  const [onlyClaims, setOnlyClaims] = useState<boolean>(false)

  // Edit metadata modal state
  const [editingDrawing, setEditingDrawing] = useState<CaseDrawing | null>(null)
  const [editForm, setEditForm] = useState<{
    figure_label: string
    figure_title: string
    reference_marks: ReferenceMark[]
  }>({ figure_label: '', figure_title: '', reference_marks: [] })

  // Add custom drawing modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [addForm, setAddForm] = useState<{
    figure_label: string
    figure_title: string
    marks_text: string
  }>({ figure_label: '附图', figure_title: '', marks_text: '' })

  // Patent Linter Drawer state
  const [isLinterDrawerOpen, setIsLinterDrawerOpen] = useState<boolean>(false)
  const linterIssues = useMemo(() => lintMarksInClient(drawings), [drawings])

  const fetchDrawings = async () => {
    try {
      setLoading(true)
      const res = await apiClient.listCaseDrawings(orgId, caseId)
      setDrawings(res.items || [])
      setError(null)
    } catch (err: any) {
      setError(err.message || '加载附图列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDrawings()
  }, [orgId, caseId])

  const { sortedMarks, claimMarksCount, filteredMarks } = useMemo(() => {
    if (!selectedDrawing?.reference_marks?.length) {
      return { sortedMarks: [], claimMarksCount: 0, filteredMarks: [] }
    }
    const sorted = naturalSortMarks(selectedDrawing.reference_marks)
    const claimCount = sorted.filter(m => m.is_claim_feature).length
    const base = onlyClaims ? sorted.filter(m => m.is_claim_feature) : sorted
    const filterTrimmed = markFilter.trim().toLowerCase()
    const filtered = filterTrimmed
      ? base.filter(
          m =>
            m.mark.toLowerCase().includes(filterTrimmed) ||
            m.name.toLowerCase().includes(filterTrimmed)
        )
      : base
    return { sortedMarks: sorted, claimMarksCount: claimCount, filteredMarks: filtered }
  }, [selectedDrawing, markFilter, onlyClaims])

  const handleReExtract = async () => {
    setReExtracting(true)
    setError(null)
    setSuccess(null)
    try {
      const res = await apiClient.reExtractCaseDrawings(orgId, caseId)
      setDrawings(res.items || [])
      setSuccess(`附图提取完成！共识别并收录 ${res.items?.length || 0} 张说明书附图。`)
    } catch (err: any) {
      setError(err.message || '重新提取附图失败')
    } finally {
      setReExtracting(false)
    }
  }

  const handleOpenEdit = (drawing: CaseDrawing) => {
    setEditingDrawing(drawing)
    setEditForm({
      figure_label: drawing.figure_label,
      figure_title: drawing.figure_title,
      reference_marks: [...drawing.reference_marks],
    })
  }

  const handleSaveEdit = async () => {
    if (!editingDrawing) return
    try {
      const res = await apiClient.updateCaseDrawing(orgId, caseId, editingDrawing.id, {
        figure_label: editForm.figure_label,
        figure_title: editForm.figure_title,
        reference_marks: editForm.reference_marks,
      })
      setDrawings(drawings.map((d) => (d.id === editingDrawing.id ? res.drawing : d)))
      setEditingDrawing(null)
      setSuccess(`已更新 ${res.drawing.figure_label} 的元数据`)
    } catch (err: any) {
      setError(err.message || '保存附图元数据失败')
    }
  }

  const handleDelete = async (drawing: CaseDrawing) => {
    if (!confirm(`确定要删除 ${drawing.figure_label} 吗？`)) return
    try {
      await apiClient.deleteCaseDrawing(orgId, caseId, drawing.id)
      setDrawings(drawings.filter((d) => d.id !== drawing.id))
      if (selectedDrawing?.id === drawing.id) setSelectedDrawing(null)
      setSuccess(`已删除 ${drawing.figure_label}`)
    } catch (err: any) {
      setError(err.message || '删除附图失败')
    }
  }

  const handleAddDrawingSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile) {
      setError('请选择要上传的附图图片')
      return
    }

    const parsedMarks: ReferenceMark[] = []
    if (addForm.marks_text.trim()) {
      const lines = addForm.marks_text.split('\n')
      for (const line of lines) {
        const parts = line.split(/[:：、\s-—]+/)
        if (parts.length >= 2 && parts[0].trim()) {
          parsedMarks.push({ mark: parts[0].trim(), name: parts.slice(1).join(' ').trim() })
        }
      }
    }

    try {
      const res = await apiClient.createCaseDrawing(orgId, caseId, {
        filename: uploadFile.name,
        figure_label: addForm.figure_label.trim() || '附图',
        figure_title: addForm.figure_title.trim(),
        reference_marks: parsedMarks,
        file: uploadFile,
      })
      setDrawings([...drawings, res.drawing])
      setIsAddModalOpen(false)
      setUploadFile(null)
      setAddForm({ figure_label: '附图', figure_title: '', marks_text: '' })
      setSuccess(`成功添加 ${res.drawing.figure_label}！`)
    } catch (err: any) {
      setError(err.message || '上传附图失败')
    }
  }

  return (
    <div className="drawings-gallery-section card p-lg mt-md border rounded bg-surface">
      <div className="flex-between mb-md">
        <div>
          <h3 className="text-lg font-bold flex-row items-center gap-xs">
            <span>🖼️ 说明书附图资产库</span>
            <span className="badge badge-primary text-xs">{drawings.length} 张附图</span>
          </h3>
          <p className="text-xs text-secondary mt-xs">
            交底书与申请文档中提取的结构图、拓扑图与流程图，支持图文联动与 Claim Chart 深度对照
          </p>
        </div>

        {!readOnly && (
          <div className="flex-row gap-xs">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleReExtract}
              disabled={reExtracting}
            >
              {reExtracting ? '正在深度提取附图...' : '🔄 重新提取附图'}
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setIsAddModalOpen(true)}
            >
              + 手动添加附图
            </button>
          </div>
        )}
      </div>

      {error && <Alert type="error" message={error} onClose={() => setError(null)} />}
      {success && <Alert type="success" message={success} onClose={() => setSuccess(null)} />}

      {/* Patent Compliance Linter Bar */}
      {!loading && drawings.length > 0 && (
        <div className="mb-sm">
          {linterIssues.length > 0 ? (
            <div
              className="linter-banner linter-warning flex-between items-center"
              onClick={() => setIsLinterDrawerOpen(!isLinterDrawerOpen)}
              title="点击展开/收起审查合规建议"
            >
              <span>
                <strong>⚠️ 附图规范体检提示</strong>：检测到 {linterIssues.length} 处跨图用词或标记一致性建议
              </span>
              <button
                type="button"
                className="btn btn-xs btn-secondary"
                style={{ fontSize: '11px', padding: '1px 6px' }}
              >
                {isLinterDrawerOpen ? '收起详情 ▲' : '查看详情 ▼'}
              </button>
            </div>
          ) : (
            <div className="linter-banner linter-success">
              <span>✓ 全案附图标记与权项跨图对照一致，未发现用词漂移</span>
            </div>
          )}

          {isLinterDrawerOpen && linterIssues.length > 0 && (
            <div className="linter-drawer">
              <div className="font-bold mb-xs">审查员/合规核对建议：</div>
              <ul style={{ margin: 0, paddingLeft: '18px' }}>
                {linterIssues.map((issue, idx) => (
                  <li key={idx} className="mb-xs">
                    {issue.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="p-lg text-center text-secondary text-sm">正在加载附图资产...</div>
      ) : drawings.length === 0 ? (
        <div className="p-xl text-center border-dashed rounded text-secondary bg-subtle">
          <p className="text-sm">暂未提取到附图资产</p>
          <p className="text-xs mt-xs">
            点击上方【🔄 重新提取附图】或【+ 手动添加附图】即可收录专利图元
          </p>
        </div>
      ) : (
        <div className="grid-3-cols mt-sm">
          {drawings.map((drawing) => {
            const fileUrl = apiClient.getCaseDrawingFileUrl(orgId, caseId, drawing.id)
            return (
              <div
                key={drawing.id}
                className="drawing-card"
              >
                {/* 1. Thumbnail Image Container */}
                <div
                  className="drawing-thumbnail-container"
                  onClick={() => {
                    setSelectedDrawing(drawing)
                    setZoomLevel(1)
                    setMarkFilter('')
                  }}
                  title="点击放大查看高清原图"
                >
                  <img
                    src={fileUrl}
                    alt={drawing.figure_label}
                    loading="lazy"
                  />
                  <div className="absolute top-2 right-2 flex-row gap-xs">
                    {drawing.page_number && (
                      <span className="badge badge-neutral text-xs opacity-90">
                        P.{drawing.page_number}
                      </span>
                    )}
                    {drawing.is_manually_added && (
                      <span className="badge badge-warning text-xs opacity-90">人工增补</span>
                    )}
                  </div>
                </div>

                {/* 2. Figure Title and Hash */}
                <div className="drawing-info">
                  <div className="flex-between items-center">
                    <strong className="text-sm text-primary">{drawing.figure_label}</strong>
                    <span className="text-xs text-secondary font-mono">
                      {drawing.sha256 ? drawing.sha256.substring(0, 8) + '...' : ''}
                    </span>
                  </div>
                  <p className="text-xs text-secondary truncate" title={drawing.figure_title}>
                    {drawing.figure_title || '（未命名附图）'}
                  </p>

                  {/* 3. Reference Marks Chips */}
                  {drawing.reference_marks && drawing.reference_marks.length > 0 && (
                    <div className="reference-marks-chips">
                      {naturalSortMarks(drawing.reference_marks).slice(0, 4).map((m, idx) => (
                        <ReferenceMarkBadge key={idx} mark={m} size="sm" />
                      ))}
                      {drawing.reference_marks.length > 4 && (
                        <span className="badge badge-neutral text-xs">
                          +{drawing.reference_marks.length - 4}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* 4. Action Buttons */}
                {!readOnly && (
                  <div className="drawing-actions">
                    <button
                      type="button"
                      className="btn-link text-xs text-primary"
                      onClick={() => {
                        setSelectedDrawing(drawing)
                        setZoomLevel(1)
                        setMarkFilter('')
                      }}
                    >
                      🔍 查看大图
                    </button>
                    <div className="flex-row gap-xs">
                      <button
                        type="button"
                        className="btn-link text-xs text-secondary hover-text-primary"
                        onClick={() => handleOpenEdit(drawing)}
                        title="编辑图名与附图标记"
                      >
                        ✏️ 编辑
                      </button>
                      <button
                        type="button"
                        className="btn-link text-xs text-danger"
                        onClick={() => handleDelete(drawing)}
                        title="删除该附图"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* --- Lightbox Modal (Split Workbench) --- */}
      {selectedDrawing && (
        <Modal
          isOpen={true}
          size="xl"
          onClose={() => setSelectedDrawing(null)}
          title={`${selectedDrawing.figure_label} - ${selectedDrawing.figure_title || '高清原图'}`}
        >
          <div className="lightbox-workbench">
            {/* Left Column: Canvas & Zoom Bar */}
            <div className="lightbox-canvas-pane">
              <div className="flex-between items-center p-xs bg-subtle rounded text-xs">
                <div className="flex-row gap-xs items-center">
                  <span className="font-semibold text-secondary">
                    缩放: {Math.round(zoomLevel * 100)}%
                  </span>
                  <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={() => setZoomLevel((z) => Math.max(0.25, z - 0.25))}
                    title="缩小"
                  >
                    -
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={() => setZoomLevel((z) => Math.min(4, z + 0.25))}
                    title="放大"
                  >
                    +
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={() => setZoomLevel(1)}
                    title="恢复 100%"
                  >
                    重置
                  </button>
                </div>

                <a
                  href={apiClient.getCaseDrawingFileUrl(orgId, caseId, selectedDrawing.id)}
                  download={`${selectedDrawing.figure_label}.png`}
                  className="btn btn-primary btn-xs"
                >
                  ⬇️ 下载图纸
                </a>
              </div>

              {/* High-res Image Display Container */}
              <div className="lightbox-canvas-container">
                <img
                  src={apiClient.getCaseDrawingFileUrl(orgId, caseId, selectedDrawing.id)}
                  alt={selectedDrawing.figure_label}
                  style={{
                    transform: `scale(${zoomLevel})`,
                    transformOrigin: 'center center',
                    transition: 'transform 0.15s ease',
                    maxWidth: zoomLevel === 1 ? '100%' : 'none',
                    maxHeight: zoomLevel === 1 ? '66vh' : 'none',
                    objectFit: 'contain',
                  }}
                />
              </div>
            </div>

            {/* Right Column: Reference Marks & Inspection Panel */}
            <div className="lightbox-sidebar-pane">
              <div>
                <div className="text-sm font-bold text-primary mb-xs">
                  {selectedDrawing.figure_label}
                </div>
                <div className="text-xs text-secondary mb-xs">
                  {selectedDrawing.figure_title || '说明书附图'}
                </div>
                <div className="text-xs font-mono text-muted truncate" title={selectedDrawing.sha256}>
                  SHA: {selectedDrawing.sha256.slice(0, 16)}...
                </div>
              </div>

              <div className="border-t my-xs"></div>

              {/* Reference Marks Section */}
              {selectedDrawing.reference_marks && selectedDrawing.reference_marks.length > 0 ? (
                <div className="flex-stack gap-xs" style={{ flex: 1, minHeight: 0 }}>
                  <div className="flex-between items-center">
                    <span className="text-xs font-bold text-secondary">
                      附图标记清单 ({selectedDrawing.reference_marks.length} 项
                      {markFilter.trim() || onlyClaims ? ` · 匹配 ${filteredMarks.length}` : ''})
                    </span>
                  </div>

                  {/* Quick filter pills */}
                  {claimMarksCount > 0 && (
                    <div className="flex-row gap-xs mb-xs">
                      <button
                        type="button"
                        className={`btn btn-xs ${!onlyClaims ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ fontSize: '11px', padding: '2px 8px' }}
                        onClick={() => setOnlyClaims(false)}
                      >
                        全部 ({sortedMarks.length})
                      </button>
                      <button
                        type="button"
                        className={`btn btn-xs ${onlyClaims ? 'btn-primary' : 'btn-secondary'}`}
                        style={{
                          fontSize: '11px',
                          padding: '2px 8px',
                          borderColor: '#f59e0b',
                          color: onlyClaims ? '#fff' : '#b45309',
                          backgroundColor: onlyClaims ? '#d97706' : 'rgba(245, 158, 11, 0.1)',
                        }}
                        onClick={() => setOnlyClaims(true)}
                      >
                        ⭐ 权利要求特征 ({claimMarksCount})
                      </button>
                    </div>
                  )}

                  <input
                    type="text"
                    className="form-input text-xs py-xs px-sm w-full"
                    placeholder="🔍 快速搜索部件或标号..."
                    value={markFilter}
                    onChange={e => setMarkFilter(e.target.value)}
                  />

                  <div className="lightbox-marks-scroll border rounded p-xs bg-surface">
                    {filteredMarks.map((m, idx) => (
                      <ReferenceMarkBadge key={idx} mark={m} />
                    ))}
                    {filteredMarks.length === 0 && (
                      <div className="text-xs text-muted py-md text-center w-full">
                        未找到匹配的附图标记
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-xs text-muted py-md text-center">
                  本图暂无提取的附图标记
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}

      {/* --- Edit Metadata Modal --- */}
      {editingDrawing && (
        <Modal
          isOpen={true}
          onClose={() => setEditingDrawing(null)}
          title={`编辑附图元数据 - ${editingDrawing.figure_label}`}
        >
          <div className="form-stack">
            <div className="form-group">
              <label className="form-label">附图标签 (图号)</label>
              <input
                type="text"
                className="input-text"
                value={editForm.figure_label}
                onChange={(e) => setEditForm({ ...editForm, figure_label: e.target.value })}
                placeholder="例如：图 1、图 2A、摘要附图"
              />
            </div>

            <div className="form-group">
              <label className="form-label">附图标题 / 说明</label>
              <input
                type="text"
                className="input-text"
                value={editForm.figure_title}
                onChange={(e) => setEditForm({ ...editForm, figure_title: e.target.value })}
                placeholder="例如：系统整体架构拓扑图"
              />
            </div>

            <div className="form-group">
              <label className="form-label">
                附图标记与部件名称对应关系 ({editForm.reference_marks.length} 项)
              </label>
              <div className="flex-stack gap-xs">
                {editForm.reference_marks.map((mark, idx) => (
                  <div key={idx} className="flex-row gap-xs items-center">
                    <input
                      type="text"
                      className="input-text"
                      style={{ width: '80px' }}
                      value={mark.mark}
                      placeholder="编号"
                      onChange={(e) => {
                        const updated = [...editForm.reference_marks]
                        updated[idx].mark = e.target.value
                        setEditForm({ ...editForm, reference_marks: updated })
                      }}
                    />
                    <input
                      type="text"
                      className="input-text"
                      style={{ flex: 1 }}
                      value={mark.name}
                      placeholder="部件/模块名称"
                      onChange={(e) => {
                        const updated = [...editForm.reference_marks]
                        updated[idx].name = e.target.value
                        setEditForm({ ...editForm, reference_marks: updated })
                      }}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary btn-xs text-danger"
                      onClick={() => {
                        const updated = editForm.reference_marks.filter((_, i) => i !== idx)
                        setEditForm({ ...editForm, reference_marks: updated })
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn btn-secondary btn-xs mt-xs"
                  onClick={() =>
                    setEditForm({
                      ...editForm,
                      reference_marks: [...editForm.reference_marks, { mark: '', name: '' }],
                    })
                  }
                >
                  + 添加一行标记
                </button>
              </div>
            </div>

            <div className="modal-actions mt-md">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setEditingDrawing(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveEdit}
              >
                保存元数据
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* --- Add Custom Drawing Modal --- */}
      {isAddModalOpen && (
        <Modal
          isOpen={true}
          onClose={() => setIsAddModalOpen(false)}
          title="手动收录 / 添加说明书附图"
        >
          <form onSubmit={handleAddDrawingSubmit} className="form-stack">
            <div className="form-group">
              <label className="form-label">选择附图图片文件 *</label>
              <input
                type="file"
                className="input-text"
                accept="image/png,image/jpeg,image/webp,image/svg+xml"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                required
              />
              <p className="text-xs text-secondary mt-xs">支持 PNG, JPG, WebP, SVG 格式图片</p>
            </div>

            <div className="form-group">
              <label className="form-label">附图标签 (图号) *</label>
              <input
                type="text"
                className="input-text"
                value={addForm.figure_label}
                onChange={(e) => setAddForm({ ...addForm, figure_label: e.target.value })}
                placeholder="例如：图 1、图 2B"
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">附图标题 / 说明</label>
              <input
                type="text"
                className="input-text"
                value={addForm.figure_title}
                onChange={(e) => setAddForm({ ...addForm, figure_title: e.target.value })}
                placeholder="例如：机器人末端夹爪结构分解图"
              />
            </div>

            <div className="form-group">
              <label className="form-label">附图标记快速录入 (每行一条)</label>
              <textarea
                className="input-text"
                rows={3}
                value={addForm.marks_text}
                onChange={(e) => setAddForm({ ...addForm, marks_text: e.target.value })}
                placeholder="例如：&#10;10: 机器人臂组件&#10;14: 末端手部&#10;16: 夹爪手指"
              />
            </div>

            <div className="modal-actions mt-md">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setIsAddModalOpen(false)}
              >
                取消
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
              >
                上传并收录
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
