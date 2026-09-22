import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from '../src/services/apiClient'
import { AssessmentDiffPanel } from '../src/components/AssessmentDiffPanel'
import type { AssessmentVersionDiff } from '../src/types/api'

const baseDiff: AssessmentVersionDiff = {
  from_version: 1,
  to_version: 2,
  from_payload_sha256: 'a'.repeat(64),
  to_payload_sha256: 'b'.repeat(64),
  rules_version: { from: 'assessment-rules-v3', to: 'assessment-rules-v3' },
  rules_version_changed: false,
  prompt_changes: [],
  blockers: {
    added: ['对比文件 CN3A 缺申请日与优先权日'],
    removed: ['引证未定位：D1/F2'],
    retained: ['存在系统建议的文献组合'],
  },
  flags: { added: [], removed: [], retained: [] },
  findings: {
    added: [
      {
        risk_kind: 'novelty',
        level: 'high_novelty_risk',
        basis: [{ doc_id: 'D2', feature_code: 'F2' }],
        requires_human_confirmation: true,
        reasoning: 'D2 单独公开了 F2',
        rules_version: 'assessment-rules-v3',
      },
    ],
    removed: [],
    retained: [],
  },
  evidence: {
    scalars: { source_coverage: { from: 0.5, to: 1 }, level: { from: 'insufficient', to: 'sufficient' } },
    lists: { missing_anchors: { added: [], removed: ['D1/F2'], retained: [] } },
  },
  three_step: {
    closest_prior_art: { from: 'D1', to: 'D2' },
    actual_technical_problem: null,
    distinguishing_features: { added: ['F3'], removed: [], retained: ['F2'] },
    present_in_both: true,
  },
  entity_observations: { added: [], removed: [], retained: [] },
  priority_changed: false,
  requires_human_confirmation: true,
  diff_rules_version: 'assessment-diff-v1',
  notes: [
    '本对比只涉及两个已冻结版本的内容，不推断输入档案的变化：档案可变且未版本化，无法忠实重建生成各版本时的输入',
    '「不再出现」不等于「已解决」：该阻塞项可能因数据变化而不再被触发，也可能换了表述仍然存在，须人工核对',
  ],
}

describe('Pre-assessment version diff', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('states up front that the diff does not infer what the input was', async () => {
    vi.spyOn(apiClient, 'diffAssessmentVersions').mockResolvedValue({ diff: baseDiff })

    render(<AssessmentDiffPanel orgId="org-1" caseId="case-1" versionNumber={2} versionNumbers={[2, 1]} />)

    await waitFor(() => {
      expect(screen.getByText(/不推断输入档案的变化/)).toBeDefined()
    })
  })

  it('labels disappeared blockers as no longer present rather than resolved', async () => {
    vi.spyOn(apiClient, 'diffAssessmentVersions').mockResolvedValue({ diff: baseDiff })

    render(<AssessmentDiffPanel orgId="org-1" caseId="case-1" versionNumber={2} versionNumbers={[2, 1]} />)

    await waitFor(() => {
      expect(screen.getByText(/不再出现的阻塞项/)).toBeDefined()
    })
    expect(screen.getByText('引证未定位：D1/F2')).toBeDefined()
    expect(screen.getByText(/不等于「已解决」/)).toBeDefined()
    expect(screen.queryByText('已解决的阻塞项')).toBeNull()
  })

  it('defaults to comparing against the previous version', async () => {
    const diff = vi
      .spyOn(apiClient, 'diffAssessmentVersions')
      .mockResolvedValue({ diff: baseDiff })

    render(
      <AssessmentDiffPanel orgId="org-1" caseId="case-1" versionNumber={2} versionNumbers={[3, 2, 1]} />
    )

    await waitFor(() => {
      expect(diff).toHaveBeenCalledWith('org-1', 'case-1', 2, 1)
    })
  })

  it('explains that there is nothing to compare against with a single version', () => {
    render(<AssessmentDiffPanel orgId="org-1" caseId="case-1" versionNumber={1} versionNumbers={[1]} />)

    expect(screen.getByText(/暂无可对比的对象/)).toBeDefined()
    expect(apiClient.diffAssessmentVersions).not.toHaveBeenCalled()
  })

  it('reloads the diff when another comparison target is picked', async () => {
    const diff = vi
      .spyOn(apiClient, 'diffAssessmentVersions')
      .mockResolvedValue({ diff: baseDiff })

    render(
      <AssessmentDiffPanel orgId="org-1" caseId="case-1" versionNumber={3} versionNumbers={[3, 2, 1]} />
    )

    await waitFor(() => {
      expect(diff).toHaveBeenCalledWith('org-1', 'case-1', 3, 2)
    })

    fireEvent.change(screen.getByLabelText('对比版本'), { target: { value: '1' } })

    await waitFor(() => {
      expect(diff).toHaveBeenLastCalledWith('org-1', 'case-1', 3, 1)
    })
  })

  it('shows the rules version change so differences are not mistaken for data changes', async () => {
    vi.spyOn(apiClient, 'diffAssessmentVersions').mockResolvedValue({
      diff: {
        ...baseDiff,
        rules_version: { from: 'assessment-rules-v2', to: 'assessment-rules-v3' },
        rules_version_changed: true,
        notes: ['两版规则版本不同（assessment-rules-v2 → assessment-rules-v3），差异可能来自规则本身，而非案件数据变化'],
      },
    })

    render(<AssessmentDiffPanel orgId="org-1" caseId="case-1" versionNumber={2} versionNumbers={[2, 1]} />)

    await waitFor(() => {
      expect(screen.getByText(/差异可能来自规则本身/)).toBeDefined()
    })
    expect(screen.getByText('assessment-rules-v2')).toBeDefined()
  })
})
