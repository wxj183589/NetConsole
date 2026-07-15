import { apiRequest } from './client'
import type { AcActionPlan, AcExtensionPage, AcExtensionPreview, AcWebTask } from '../types/acWebParity'

const root = '/api/ac-management'

function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value))
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function listAcExtensions(page = 1, pageSize = 50, search = ''): Promise<AcExtensionPage> {
  return apiRequest<AcExtensionPage>(`${root}/extensions${query({ page, page_size: pageSize, search })}`)
}

export function previewAcExtension(file: File): Promise<AcExtensionPreview> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<AcExtensionPreview>(`${root}/extensions/import-preview`, { method: 'POST', body: form })
}

export function applyAcExtension(preview: AcExtensionPreview, explicitConfirmation = true): Promise<{
  audit_id: string
  status: string
  preview_id: string
}> {
  return apiRequest(`${root}/extensions/import-apply`, {
    method: 'POST',
    body: JSON.stringify({ preview_id: preview.preview_id, preview_digest: preview.preview_digest, explicit_confirmation: explicitConfirmation }),
  })
}

export function rollbackAcExtension(auditId: string): Promise<{ audit_id: string; status: string; restored_rows: number }> {
  return apiRequest(`${root}/extensions/audits/${encodeURIComponent(auditId)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ explicit_confirmation: true }),
  })
}

export function startAcRefresh(kind: 'ac' | 'fit-ap' | 'optical' | 'trackside-plan' | 'trackside-business', acId = ''): Promise<AcWebTask> {
  const path = kind === 'trackside-business' ? `${root}/trackside-business/refresh` : `${root}/refresh/${kind}`
  return apiRequest<AcWebTask>(path, { method: 'POST', body: JSON.stringify({ ac_id: acId }) })
}

export function createAcActionPlan(targetId: string, actionId: string): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans`, { method: 'POST', body: JSON.stringify({ target_id: targetId, action_id: actionId }) })
}

export function confirmAcActionPlan(plan: AcActionPlan): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans/${encodeURIComponent(plan.plan_id)}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ plan_digest: plan.plan_digest, confirm_token: plan.confirm_token }),
  })
}

export function executeAcActionPlan(planId: string): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans/${encodeURIComponent(planId)}/execute`, { method: 'POST' })
}
