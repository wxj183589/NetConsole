import { describe, expect, it, vi } from 'vitest'

import { rollbackAcExtension } from './acWebParity'
import { rollbackRailTransitImport } from './railTransitBaseData'

describe('rollback authority API clients', () => {
  it('passes operation-specific capabilities to both rollback endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await rollbackAcExtension('audit/1')
    await rollbackRailTransitImport('operation/1')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      explicit_confirmation: true,
      authorization_token: 'AC_EXTENSION_ROLLBACK_AUTHORIZED',
    })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      explicit_confirmation: true,
      authorization_token: 'BASE_DATA_ROLLBACK_AUTHORIZED',
    })
  })
})
