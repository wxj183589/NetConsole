import { describe, expect, it } from 'vitest'

import toolboxSource from './NetworkToolboxPanel.vue?raw'
import wirelessSource from './WirelessScanPanel.vue?raw'

describe('network export download recovery', () => {
  it.each([
    ['toolbox', toolboxSource],
    ['wireless', wirelessSource],
  ])('does not consume the %s export task when save is cancelled', (_name, source) => {
    const download = source.indexOf('await downloadBackendResource')
    const consumed = source.indexOf('downloadedExportTaskId =', download)

    expect(download).toBeGreaterThan(-1)
    expect(source).toContain("if (result.status === 'cancelled') return")
    expect(consumed).toBeGreaterThan(download)
    expect(source.indexOf('localStorage.removeItem(EXPORT_TASK_KEY)', download)).toBeGreaterThan(download)
  })
})
