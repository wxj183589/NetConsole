import { promises as fs } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { afterEach, describe, expect, it } from 'vitest'

import { UiPreferenceStore } from '../src/main/ui-preferences'

const temporaryRoots: string[] = []

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map((root) => fs.rm(root, { recursive: true, force: true })))
})

describe('UI preference store', () => {
  it('persists only through the injected userData root and reloads after a new store', async () => {
    const root = await fs.mkdtemp(join(tmpdir(), 'netconsole-ui-preferences-'))
    temporaryRoots.push(root)
    const first = new UiPreferenceStore(root)
    await first.set('mesh-analysis-airload.show-switch-points', true)

    const second = new UiPreferenceStore(root)
    await expect(second.get('mesh-analysis-airload.show-switch-points')).resolves.toBe(true)
    expect(await fs.readFile(join(root, 'ui-preferences.json'), 'utf8')).toContain('show-switch-points')
  })

  it('removes one preference without affecting the remaining entries', async () => {
    const root = await fs.mkdtemp(join(tmpdir(), 'netconsole-ui-preferences-'))
    temporaryRoots.push(root)
    const store = new UiPreferenceStore(root)
    await store.set('mesh-analysis-rssi.show-switch-points', false)
    await store.set('mesh-analysis-rssi.show-location-band', true)
    await store.set('mesh-analysis-rssi.show-switch-points', null)

    await expect(store.get('mesh-analysis-rssi.show-switch-points')).resolves.toBeNull()
    await expect(store.get('mesh-analysis-rssi.show-location-band')).resolves.toBe(true)
  })
})
