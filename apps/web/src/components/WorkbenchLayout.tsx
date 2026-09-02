import React from 'react'
import { Header } from './Header'
import { Link } from '../router/Router'
import { CaseWorkflowStepper, CaseStepKey } from './CaseWorkflowStepper'
import { Alert } from './Alert'
import type { CaseStatus } from '../types/api'

export interface WorkbenchLayoutProps {
  currentStep: CaseStepKey
  caseStatus?: CaseStatus
  orgId: string
  caseId: string
  title: string
  description?: string
  breadcrumbCurrent: string
  headerActions?: React.ReactNode
  error?: string | null
  success?: string | null
  onErrorClose?: () => void
  onSuccessClose?: () => void
  children: React.ReactNode
}

export const WorkbenchLayout: React.FC<WorkbenchLayoutProps> = ({
  currentStep,
  caseStatus,
  orgId,
  caseId,
  title,
  description,
  breadcrumbCurrent,
  headerActions,
  error,
  success,
  onErrorClose,
  onSuccessClose,
  children,
}) => {
  return (
    <div className="layout-container">
      <Header />

      <main className="main-content">
        <div className="breadcrumb text-xs text-secondary mb-xs">
          <Link to={`/organizations/${orgId}/cases`}>案件列表</Link> &gt;{' '}
          <Link to={`/organizations/${orgId}/cases/${caseId}`}>案件详情</Link> &gt; {breadcrumbCurrent}
        </div>

        {/* Page Header */}
        <div className="page-header flex-between mb-md">
          <div>
            <h1 className="page-title text-2xl font-bold">{title}</h1>
            {description && <p className="text-secondary text-sm">{description}</p>}
          </div>
          {headerActions && <div className="actions flex-row gap-sm">{headerActions}</div>}
        </div>

        {/* Lifecycle Stepper */}
        <CaseWorkflowStepper
          currentStep={currentStep}
          caseStatus={caseStatus}
          orgId={orgId}
          caseId={caseId}
        />

        {/* Alerts */}
        {error && <Alert type="error" message={error} onClose={onErrorClose} />}
        {success && <Alert type="success" message={success} onClose={onSuccessClose} />}

        {children}
      </main>
    </div>
  )
}
