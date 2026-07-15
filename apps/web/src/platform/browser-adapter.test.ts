import { describe, expect, it } from 'vitest'

import { createBrowserAdapter } from './browser-adapter'

describe('browser platform adapter', () => {
  it('keeps browser mode independent and returns safe desktop fallbacks', async () => {
    const adapter = createBrowserAdapter('/backend/')

    expect(await adapter.getRuntimeConfig()).toEqual({ apiBaseUrl: '/backend', apiToken: '' })
    expect(await adapter.selectFile()).toEqual({ cancelled: true, paths: [] })
    expect(await adapter.selectDirectory()).toEqual({ cancelled: true })
    expect(await adapter.chooseSavePath({ suggestedName: 'report.xlsx' })).toEqual({ cancelled: true })
    await expect(adapter.openPath('C:\\report.xlsx')).resolves.toMatchObject({ success: false })
  })
})
