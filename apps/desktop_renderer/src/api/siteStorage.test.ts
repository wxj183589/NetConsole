import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('./client', () => ({ apiRequest: apiRequestMock }))

import {
  applySiteRetention,
  getLatestSiteRetention,
  scanSiteRetention,
} from './siteStorage'

describe('site storage retention API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiRequestMock.mockResolvedValue({})
  })

  it('uses encoded site ids and server-issued scan tokens', async () => {
    await scanSiteRetention('line/12')
    await getLatestSiteRetention('line/12')
    await applySiteRetention('line/12', 'a'.repeat(64), ['candidate-1'])

    expect(apiRequestMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/sites/line%2F12/retention/scan',
      { method: 'POST' },
    )
    expect(apiRequestMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/sites/line%2F12/retention/latest',
    )
    expect(apiRequestMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/sites/line%2F12/retention/apply',
      {
        method: 'POST',
        body: JSON.stringify({
          scan_token: 'a'.repeat(64),
          candidate_ids: ['candidate-1'],
          confirmed: true,
        }),
      },
    )
  })
})
