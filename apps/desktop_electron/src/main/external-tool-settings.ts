import { DESKTOP_SESSION_HEADER } from '../shared/bridge'

export interface ExternalToolSystemSettings {
  legacyIpopPath: string
  terminalPaths: {
    securecrt: string
    xshell: string
    putty: string
  }
}

interface BackendRuntimeProvider {
  getRuntimeInfo(): { baseUrl: string; apiToken: string }
}

export async function readExternalToolSystemSettings(
  backend: BackendRuntimeProvider,
  fetchImpl: typeof fetch = fetch,
): Promise<ExternalToolSystemSettings> {
  const runtime = backend.getRuntimeInfo()
  const base = new URL(runtime.baseUrl)
  if (
    base.protocol !== 'http:'
    || base.hostname !== '127.0.0.1'
    || !base.port
    || base.pathname !== '/'
    || base.username
    || base.password
  ) {
    throw new Error('untrusted backend')
  }
  const response = await fetchImpl(new URL('/api/settings', base.origin), {
    headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
    redirect: 'error',
  })
  if (!response.ok) throw new Error(`settings request failed: HTTP ${response.status}`)
  const body = await response.json() as {
    values?: {
      ipop_path?: unknown
      terminal_paths?: {
        securecrt?: unknown
        xshell?: unknown
        putty?: unknown
      }
    }
  }
  const values = body.values
  const terminalPaths = values?.terminal_paths
  return {
    legacyIpopPath: settingPath(values?.ipop_path),
    terminalPaths: {
      securecrt: settingPath(terminalPaths?.securecrt),
      xshell: settingPath(terminalPaths?.xshell),
      putty: settingPath(terminalPaths?.putty),
    },
  }
}

function settingPath(value: unknown): string {
  if (typeof value !== 'string' || value.length > 32_767 || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new TypeError('system settings path is invalid')
  }
  return value.trim()
}
