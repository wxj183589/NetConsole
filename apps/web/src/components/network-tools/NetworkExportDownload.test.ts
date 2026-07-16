import { describe, expect, it } from 'vitest'

import toolboxSource from './NetworkToolboxPanel.vue?raw'
import wirelessSource from './WirelessScanPanel.vue?raw'

describe('network export artifact download', () => {
  it.each([
    ['toolbox', toolboxSource],
    ['wireless', wirelessSource],
  ])('keeps the %s export task in the shared task source when save is cancelled', (_name, source) => {
    const download = source.indexOf('await downloadBackendResource')

    expect(download).toBeGreaterThan(-1)
    expect(source).not.toContain('localStorage')
    expect(source).not.toContain('downloadedExportTaskId')
  })
})
