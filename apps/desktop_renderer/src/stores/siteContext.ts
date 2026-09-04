import { ref } from 'vue'

import { getActiveSite, type SiteRecord } from '../api/siteStorage'

export type SiteContextState = 'loading' | 'switching' | 'ready' | 'error'

export interface SiteContext {
  siteId: string
  displayName: string
  revision: string
}

export const activeSiteContext = ref<SiteContext | null>(null)
export const siteContextState = ref<SiteContextState>('loading')

let refreshGeneration = 0
let refreshPromise: Promise<SiteContext | null> | null = null

export function siteContextFromRecord(value: unknown): SiteContext | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const siteId = String(record.site_id || record.siteId || '').trim()
  if (!siteId) return null
  return {
    siteId,
    displayName: String(record.display_name || record.site_name || record.displayName || '').trim(),
    revision: String(
      record.revision
      || record.switch_revision
      || record.runtime_revision
      || record.registry_revision
      || '',
    ).trim(),
  }
}

export function setActiveSiteContext(value: unknown): SiteContext | null {
  const context = siteContextFromRecord(value)
  if (!context) return null
  activeSiteContext.value = context
  siteContextState.value = 'ready'
  return context
}

export function markSiteContextSwitching(): void {
  siteContextState.value = 'switching'
}

export function markSiteContextRollback(): void {
  siteContextState.value = activeSiteContext.value ? 'ready' : 'error'
}

export function clearSiteContext(state: SiteContextState = 'loading'): void {
  refreshGeneration += 1
  activeSiteContext.value = null
  siteContextState.value = state
}

export function getSiteContextSnapshot(): SiteContext | null {
  return activeSiteContext.value ? { ...activeSiteContext.value } : null
}

export async function refreshSiteContext(): Promise<SiteContext | null> {
  if (refreshPromise) return refreshPromise
  const generation = ++refreshGeneration
  siteContextState.value = 'loading'
  const request = getActiveSite()
    .then((record: SiteRecord) => {
      const context = siteContextFromRecord(record)
      if (generation === refreshGeneration) {
        activeSiteContext.value = context
        // An empty active-site response is a valid "not selected" state;
        // reserve error for a failed request.
        siteContextState.value = 'ready'
      }
      return context
    })
    .catch((cause) => {
      if (generation === refreshGeneration) {
        activeSiteContext.value = null
        siteContextState.value = 'error'
      }
      throw cause
    })
    .finally(() => {
      if (refreshPromise === request) refreshPromise = null
    })
  refreshPromise = request
  return request
}
