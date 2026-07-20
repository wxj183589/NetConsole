import type { UiPreferenceKey } from '../../../desktop_electron/src/shared/bridge'

const STORAGE_PREFIX = 'netconsole:ui-preference:v1:'

function storageKey(key: UiPreferenceKey): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(key)}`
}

function localStorageOrUndefined(): Storage | undefined {
  return typeof localStorage === 'undefined' ? undefined : localStorage
}

function readLocal<T>(key: UiPreferenceKey, fallback: T): T {
  const storage = localStorageOrUndefined()
  if (!storage) return fallback
  try {
    const raw = storage.getItem(storageKey(key))
    if (raw === null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function readUiPreference<T>(key: UiPreferenceKey, fallback: T): T {
  return readLocal(key, fallback)
}

export async function loadUiPreference<T>(key: UiPreferenceKey, fallback: T): Promise<T> {
  const bridge = typeof window === 'undefined' ? undefined : window.netconsoleDesktop
  if (bridge?.getUiPreference) {
    try {
      const value = await bridge.getUiPreference(key)
      return value === null ? fallback : value as T
    } catch {
      return readLocal(key, fallback)
    }
  }
  return readLocal(key, fallback)
}

export async function saveUiPreference(key: UiPreferenceKey, value: unknown): Promise<void> {
  const storage = localStorageOrUndefined()
  try { storage?.setItem(storageKey(key), JSON.stringify(value)) } catch { /* fallback persistence is best effort */ }
  const bridge = typeof window === 'undefined' ? undefined : window.netconsoleDesktop
  if (bridge?.setUiPreference) await bridge.setUiPreference(key, value)
}

export async function clearUiPreference(key: UiPreferenceKey): Promise<void> {
  const storage = localStorageOrUndefined()
  try { storage?.removeItem(storageKey(key)) } catch { /* fallback persistence is best effort */ }
  const bridge = typeof window === 'undefined' ? undefined : window.netconsoleDesktop
  if (bridge?.setUiPreference) await bridge.setUiPreference(key, null)
}
