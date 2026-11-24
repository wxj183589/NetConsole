import { describe, expect, it, vi } from 'vitest'

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('./client', () => ({
  apiRequest: apiRequestMock,
}))

import { getTrainCommunicationSummary, listTrainCommunications } from './trainCommunication'

describe('Online MR inventory API', () => {
  it('reads shared train and MR inventory under the Online MR namespace', async () => {
    await getTrainCommunicationSummary()
    await listTrainCommunications({ train: '01', page: 2, page_size: 50 })
    expect(apiRequestMock).toHaveBeenNthCalledWith(1, '/api/rail-transit/online-mr/inventory/summary')
    expect(apiRequestMock).toHaveBeenNthCalledWith(2, '/api/rail-transit/online-mr/inventory/trains?train=01&page=2&page_size=50')
  })
})
