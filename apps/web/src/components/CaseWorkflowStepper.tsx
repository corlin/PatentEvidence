import React from 'react'
import { Link } from '../router/Router'
import type { CaseStatus } from '../types/api'

export type CaseStepKey =
  | 'intake'
  | 'features'
  | 'search'
  | 'comparisons'
  | 'reports'
  | 'review'
  | 'delivery'

interface StepConfig {
  key: CaseStepKey
  label: string
  pathSuffix: string
  isDone: (status: CaseStatus) => boolean
}

const STEPS: StepConfig[] = [
  {
    key: 'intake',
    label: '文档交底与附图',
    pathSuffix: '',
    isDone: (s) => s !== 'draft',
  },
  {
    key: 'features',
    label: '权利要求建模',
    pathSuffix: '/features',
    isDone: (s) => !['draft', 'document_ready'].includes(s),
  },
  {
    key: 'search',
    label: '检索与候选初筛',
    pathSuffix: '/search',
    isDone: (s) => !['draft', 'document_ready', 'evidence_ready'].includes(s),
  },
  {
    key: 'comparisons',
    label: 'Claim Chart 比对',
    pathSuffix: '/comparisons',
    isDone: (s) => !['draft', 'document_ready', 'evidence_ready', 'assessment_ready'].includes(s),
  },
  {
    key: 'reports',
    label: '证据封存与报告',
    pathSuffix: '/reports',
    isDone: (s) => ['in_review', 'changes_requested', 'approved', 'delivered', 'completed'].includes(s),
  },
  {
    key: 'review',
    label: '独立专业复核',
    pathSuffix: '/review',
    isDone: (s) => ['approved', 'delivered'].includes(s),
  },
  {
    key: 'delivery',
    label: '交付与归档网关',
    pathSuffix: '/delivery',
    isDone: (s) => s === 'delivered',
  },
]

interface CaseWorkflowStepperProps {
  orgId: string
  caseId: string
  currentStep: CaseStepKey
  caseStatus?: CaseStatus
}

export const CaseWorkflowStepper: React.FC<CaseWorkflowStepperProps> = ({
  orgId,
  caseId,
  currentStep,
  caseStatus = 'draft',
}) => {
  return (
    <div className="workflow-stepper-container">
      <nav className="workflow-stepper-nav" aria-label="案件处理全生命周期流程导航">
        {STEPS.map((step, idx) => {
          const isActive = step.key === currentStep
          const isDone = step.isDone(caseStatus)
          const targetUrl = `/organizations/${orgId}/cases/${caseId}${step.pathSuffix}`

          const statusClass = isActive
            ? 'active'
            : isDone
            ? 'completed'
            : 'pending'

          return (
            <React.Fragment key={step.key}>
              <Link
                to={targetUrl}
                className={`workflow-step-node ${statusClass}`}
                title={`跳转至: ${step.label}`}
              >
                <span className="workflow-step-badge">
                  {isDone && !isActive ? '✓' : idx + 1}
                </span>
                <span>{step.label}</span>
              </Link>

              {idx < STEPS.length - 1 && (
                <span className="workflow-step-arrow">&rarr;</span>
              )}
            </React.Fragment>
          )
        })}
      </nav>
    </div>
  )
}
