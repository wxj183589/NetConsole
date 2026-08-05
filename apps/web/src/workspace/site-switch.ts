export const BEFORE_SITE_SWITCH_EVENT = 'netconsole:before-site-switch'
export const SITE_CONTEXT_CHANGED_EVENT = 'netconsole:site-context-changed'

export function notifySiteContextChanged(): void {
  window.dispatchEvent(new CustomEvent(SITE_CONTEXT_CHANGED_EVENT))
}

export class SiteSwitchCancelled extends Error {
  constructor() {
    super('SITE_SWITCH_CANCELLED')
    this.name = 'SiteSwitchCancelled'
  }
}

export function notifyBeforeSiteSwitch(targetSiteId: string): boolean {
  return window.dispatchEvent(new CustomEvent(BEFORE_SITE_SWITCH_EVENT, {
    detail: { targetSiteId },
    cancelable: true,
  }))
}

export interface SiteSwitchTarget {
  siteId: string
  displayName: string
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
  coordinator.onSwitchingChanged?.(true)
  try {
    await coordinator.preflight(target.siteId)
    const focusQuery = new URLSearchParams({
      section: 'site-storage',
      site_focus: `site-switch-${Date.now()}`,
    })
    checkpoint = await coordinator.prepareWorkspace(
      target.siteId,
      `/settings?${focusQuery}`,
    )
    await coordinator.activate(target.siteId)
    await coordinator.restart(target.siteId)
    return 'completed'
  } catch (cause) {
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
