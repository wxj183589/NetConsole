import { promises as fs } from 'node:fs'
import { dirname, join } from 'node:path'

import type { UiPreferenceKey } from '../shared/bridge'

const STORE_VERSION = 1
const FILE_NAME = 'ui-preferences.json'

interface PersistedUiPreferences {
  version: typeof STORE_VERSION
  values: Partial<Record<UiPreferenceKey, unknown>>
}

export interface UiPreferenceStoreLike {
  get(key: UiPreferenceKey): Promise<unknown | null>
  set(key: UiPreferenceKey, value: unknown | null): Promise<void>
}

export class UiPreferenceStore implements UiPreferenceStoreLike {
  private readonly filePath: string
  private values: Partial<Record<UiPreferenceKey, unknown>> = {}
  private loadPromise: Promise<void> | undefined
  private writePromise: Promise<void> = Promise.resolve()

  constructor(userDataPath: string) {
    this.filePath = join(userDataPath, FILE_NAME)
  }

  async get(key: UiPreferenceKey): Promise<unknown | null> {
    await this.ensureLoaded()
    return this.values[key] ?? null
  }

  async set(key: UiPreferenceKey, value: unknown | null): Promise<void> {
    await this.ensureLoaded()
    if (value === null) delete this.values[key]
    else this.values[key] = value
    const snapshot: PersistedUiPreferences = { version: STORE_VERSION, values: { ...this.values } }
    this.writePromise = this.writePromise.catch(() => undefined).then(() => this.write(snapshot))
    await this.writePromise
  }

  private async ensureLoaded(): Promise<void> {
    this.loadPromise ??= this.load()
    await this.loadPromise
  }

  private async load(): Promise<void> {
    try {
      const parsed = JSON.parse(await fs.readFile(this.filePath, 'utf8')) as Partial<PersistedUiPreferences>
      if (parsed.version === STORE_VERSION && parsed.values && typeof parsed.values === 'object') {
        this.values = { ...parsed.values }
      }
    } catch {
      this.values = {}
    }
  }

  private async write(snapshot: PersistedUiPreferences): Promise<void> {
    const directory = dirname(this.filePath)
    const temporaryPath = `${this.filePath}.tmp-${process.pid}`
    await fs.mkdir(directory, { recursive: true })
    try {
      await fs.writeFile(temporaryPath, `${JSON.stringify(snapshot)}\n`, 'utf8')
      await fs.rename(temporaryPath, this.filePath)
    } catch (cause) {
      await fs.unlink(temporaryPath).catch(() => undefined)
      throw cause
    }
  }
}
