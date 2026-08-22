export const BEFORE_SITE_SWITCH_EVENT = 'netconsole:before-site-switch'
export const SITE_CONTEXT_CHANGED_EVENT = 'netconsole:site-context-changed'
export const SITE_SWITCH_METADATA_EVENT = 'netconsole:site-switch-metadata'

export interface BeforeSiteSwitchDetail {
  targetSiteId: string
  waitUntil(promise: Promise<boolean>): void
}

export function notifySiteContextChanged(): void {
  window.dispatchEvent(new CustomEvent(SITE_CONTEXT_CHANGED_EVENT))
}

export class SiteSwitchCancelled extends Error {
  constructor() {
    super('SITE_SWITCH_CANCELLED')
    this.name = 'SiteSwitchCancelled'
  }
}

export async function notifyBeforeSiteSwitch(targetSiteId: string): Promise<boolean> {
  const deferredChecks: Promise<boolean>[] = []
  const event = new CustomEvent<BeforeSiteSwitchDetail>(BEFORE_SITE_SWITCH_EVENT, {
    detail: {
      targetSiteId,
      waitUntil: (promise) => { deferredChecks.push(Promise.resolve(promise)) },
    },
    cancelable: true,
  })
  if (!window.dispatchEvent(event)) return false
  return (await Promise.all(deferredChecks)).every(Boolean)
}

export interface SiteSwitchTarget {
  siteId: string
  displayName: string
}

export interface SiteSwitchMetadataDetail extends SiteSwitchTarget {
  state: 'loading' | 'rollback'
}

function notifySiteSwitchMetadata(target: SiteSwitchTarget, state: SiteSwitchMetadataDetail['state']): void {
  window.dispatchEvent(new CustomEvent<SiteSwitchMetadataDetail>(SITE_SWITCH_METADATA_EVENT, {
    detail: { ...target, state },
  }))
}

export interface SiteSwitchCoordinator {
  isBlocked(): boolean
  confirm(target: SiteSwitchTarget): Promise<boolean>
  preflight(targetSiteId: string): Promise<void>
  prepareWorkspace(targetSiteId: string, settingsRouteFullPath: string): Promise<unknown>
  activate(targetSiteId: string): Promise<void>
  restart(targetSiteId: string): Promise<void>
  restoreWorkspace(checkpoint: unknown): Promise<void>
  onSwitchingChanged?(switching: boolean): void
}

export type SiteSwitchResult = 'completed' | 'cancelled' | 'blocked'

function siteSwitchStage(name: string, startedAt: number, targetSiteId: string): number {
  const now = performance.now()
  console.info('SITE_SWITCH_PROFILE', {
    target_site_id: targetSiteId,
    stage: name,
    duration_ms: Math.round((now - startedAt) * 100) / 100,
  })
  return now
}

/**
 * The Settings panel and a tray-originated request must share the same
 * confirmation, preflight, workspace snapshot, activation, and rollback path.
 */
export async function coordinateSiteSwitch(
  target: SiteSwitchTarget,
  coordinator: SiteSwitchCoordinator,
): Promise<SiteSwitchResult> {
  if (coordinator.isBlocked()) return 'blocked'
  if (!await coordinator.confirm(target)) return 'cancelled'

  let checkpoint: unknown
  let metadataPublished = false
  let stageStartedAt = performance.now()
  coordinator.onSwitchingChanged?.(true)
  try {
    notifySiteSwitchMetadata(target, 'loading')
    metadataPublished = true
    stageStartedAt = siteSwitchStage('metadata_visible', stageStartedAt, target.siteId)
    const focusQuery = new URLSearchParams({
      section: 'site-storage',
      site_focus: `site-switch-${Date.now()}`,
    })
    checkpoint = await coordinator.prepareWorkspace(
      target.siteId,
      `/settings?${focusQuery}`,
    )
    stageStartedAt = siteSwitchStage('metadata_workspace', stageStartedAt, target.siteId)
    await coordinator.preflight(target.siteId)
    stageStartedAt = siteSwitchStage('preflight', stageStartedAt, target.siteId)
    await coordinator.activate(target.siteId)
    stageStartedAt = siteSwitchStage('activate', stageStartedAt, target.siteId)
    await coordinator.restart(target.siteId)
    siteSwitchStage('backend_handoff', stageStartedAt, target.siteId)
    return 'completed'
  } catch (cause) {
    if (metadataPublished) notifySiteSwitchMetadata(target, 'rollback')
    if (cause instanceof SiteSwitchCancelled) return 'cancelled'
    if (checkpoint) {
      try {
        await coordinator.restoreWorkspace(checkpoint)
      } catch {
        // Preserve the activation or managed Backend restart error.
      }
    }
    throw cause
  } finally {
    coordinator.onSwitchingChanged?.(false)
  }
}
