export const BEFORE_SITE_SWITCH_EVENT = 'netconsole:before-site-switch'

export function notifyBeforeSiteSwitch(targetSiteId: string): void {
  window.dispatchEvent(new CustomEvent(BEFORE_SITE_SWITCH_EVENT, {
    detail: { targetSiteId },
  }))
}
