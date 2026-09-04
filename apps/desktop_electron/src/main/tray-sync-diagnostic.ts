export interface TraySyncDiagnosticState {
  backendSiteId?: string
  rendererSiteId?: string
  traySiteId?: string
}

/**
 * Formats a read-only startup diagnostic. These IDs are observations, not
 * another current-site state or cache.
 */
export function formatTraySyncDiagnostic(state: TraySyncDiagnosticState): string {
  return [
    '[TraySync]',
    `backend_site_id=${sanitizeDiagnosticId(state.backendSiteId)}`,
    `renderer_site_id=${sanitizeDiagnosticId(state.rendererSiteId)}`,
    `tray_site_id=${sanitizeDiagnosticId(state.traySiteId)}`,
  ].join(' ')
}

function sanitizeDiagnosticId(value: string | undefined): string {
  return (value ?? '').trim().replace(/[^a-z0-9_-]/g, '')
}
