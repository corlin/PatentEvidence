import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { SessionProvider } from '../src/context/SessionContext'
import { Router } from '../src/router/Router'
import { ProductFeaturesWorkbenchView } from '../src/views/ProductFeaturesWorkbenchView'
import type { ProductFeatureSet } from '../src/types/api'

// SYNTHETIC data for UI tests.
const draft: ProductFeatureSet = {
  id: 'set-1',
  case_id: 'case-1',
  description_id: 'desc-1',
  version_number: 1,
  status: 'draft',
  parent_set_id: null,
  splitter_version: 'product-splitter/1',
  confirmed_at: null,
  features: [
    { code: 'P1', text: '液冷板由铝合金挤压成型。', spans: [[3, 15]], origin: 'split' },
    { code: 'P2', text: '冷却液流道呈蛇形布置；', spans: [[19, 30]], origin: 'split' },
    { code: 'P3', text: '入口与出口位于同一侧。', spans: [[30, 41]], origin: 'split' },
  ],
  warnings: ['P9 is 130 characters: may contain several features; split during review'],
}

const renderView = () =>
  render(
    <Router>
      <SessionProvider>
        <ProductFeaturesWorkbenchView orgId="org-1" caseId="case-1" />
      </SessionProvider>
    </Router>
  )

describe('Product features workbench (ADR 0010)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(apiClient, 'getSession').mockResolvedValue({
      identity_id: 'user-1',
      email: 'agent@test.com',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      mfa_recent: true,
    })
  })

  it('saves the description and shows the generated candidates with warnings', async () => {
    vi.spyOn(apiClient, 'listProductDescriptions').mockResolvedValue({ items: [] })
    vi.spyOn(apiClient, 'listProductFeatureSets').mockResolvedValue({ items: [] })
    const add = vi.spyOn(apiClient, 'addProductDescription').mockResolvedValue({ id: 'desc-1', version_number: 1 })
    const create = vi.spyOn(apiClient, 'createProductFeatureDraft').mockResolvedValue(draft)
    renderView()
    await waitFor(() => expect(screen.getByText('尚无特征。填写产品描述并生成候选特征。')).toBeDefined())

    fireEvent.change(screen.getByLabelText('产品描述正文'), { target: { value: '1. 液冷板由铝合金挤压成型。' } })
    fireEvent.click(screen.getByRole('button', { name: '保存描述并生成候选特征' }))

    await waitFor(() => expect(screen.getByTestId('feature-P1')).toBeDefined())
    expect(add).toHaveBeenCalledWith('org-1', 'case-1', '1. 液冷板由铝合金挤压成型。')
    expect(create).toHaveBeenCalledWith('org-1', 'case-1', 'desc-1')
    expect(screen.getByLabelText('拆分提示').textContent).toContain('split during review')
  })

  it('enables merge only with two selected features and sends their codes', async () => {
    vi.spyOn(apiClient, 'listProductDescriptions').mockResolvedValue({ items: [] })
    vi.spyOn(apiClient, 'listProductFeatureSets').mockResolvedValue({
      items: [{ id: 'set-1', version_number: 1, status: 'draft', description_id: 'desc-1', parent_set_id: null, confirmed_at: null, feature_count: 3 }],
    })
    vi.spyOn(apiClient, 'getProductFeatureSet').mockResolvedValue(draft)
    const merge = vi.spyOn(apiClient, 'mergeProductFeatures').mockResolvedValue({ ...draft, features: draft.features.slice(0, 2) })
    renderView()
    await waitFor(() => expect(screen.getByTestId('feature-P2')).toBeDefined())

    const mergeButton = screen.getByRole('button', { name: /合并所选/ }) as HTMLButtonElement
    expect(mergeButton.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('选择 P2 以合并'))
    expect(mergeButton.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('选择 P3 以合并'))
    expect(mergeButton.disabled).toBe(false)
    fireEvent.click(mergeButton)
    await waitFor(() => expect(merge).toHaveBeenCalledWith('org-1', 'case-1', 'set-1', ['P2', 'P3']))
  })

  it('confirms only through the dialog that states the set becomes immutable', async () => {
    vi.spyOn(apiClient, 'listProductDescriptions').mockResolvedValue({ items: [] })
    vi.spyOn(apiClient, 'listProductFeatureSets').mockResolvedValue({
      items: [{ id: 'set-1', version_number: 1, status: 'draft', description_id: 'desc-1', parent_set_id: null, confirmed_at: null, feature_count: 3 }],
    })
    vi.spyOn(apiClient, 'getProductFeatureSet').mockResolvedValue(draft)
    const confirm = vi.spyOn(apiClient, 'confirmProductFeatureSet').mockResolvedValue({ ...draft, status: 'confirmed', confirmed_at: '2026-10-04T08:00:00Z' })
    renderView()
    await waitFor(() => expect(screen.getByTestId('feature-P1')).toBeDefined())

    fireEvent.click(screen.getByRole('button', { name: '确认特征集' }))
    expect(confirm).not.toHaveBeenCalled()
    expect(screen.getByText(/将不可修改、不可删除/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: '确认并锁定' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledWith('org-1', 'case-1', 'set-1'))
    await waitFor(() => expect(screen.getByText(/该特征集已确认，不可修改/)).toBeDefined())
  })

  it('shows a confirmed set read-only and offers a revision', async () => {
    const confirmed = { ...draft, status: 'confirmed' as const, confirmed_at: '2026-10-04T08:00:00Z' }
    vi.spyOn(apiClient, 'listProductDescriptions').mockResolvedValue({ items: [] })
    vi.spyOn(apiClient, 'listProductFeatureSets').mockResolvedValue({
      items: [{ id: 'set-1', version_number: 1, status: 'confirmed', description_id: 'desc-1', parent_set_id: null, confirmed_at: confirmed.confirmed_at, feature_count: 3 }],
    })
    vi.spyOn(apiClient, 'getProductFeatureSet').mockResolvedValue(confirmed)
    const revise = vi.spyOn(apiClient, 'reviseProductFeatureSet').mockResolvedValue({ ...draft, id: 'set-2', version_number: 2, parent_set_id: 'set-1' })
    renderView()
    await waitFor(() => expect(screen.getByTestId('feature-P1')).toBeDefined())

    expect(screen.queryByRole('button', { name: '编辑' })).toBeNull()
    expect(screen.queryByLabelText('选择 P1 以合并')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '创建修订' }))
    await waitFor(() => expect(revise).toHaveBeenCalledWith('org-1', 'case-1', 'set-1'))
  })
})
