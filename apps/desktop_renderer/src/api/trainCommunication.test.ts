import { describe, expect, it, vi } from 'vitest'

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('./client', () => ({
  apiRequest: apiRequestMock,
}))

import { getTrainCommunicationCheck, listOnlineTrainCommunications, startTrainCommunicationCheck } from './trainCommunication'

describe('train communication API', () => {
  it('uses the formal online train and diagnostics endpoints', () => {
    listOnlineTrainCommunications(1, 200)
    startTrainCommunicationCheck('train-1')
    getTrainCommunicationCheck('task-1')

    expect(apiRequestMock).toHaveBeenNthCalledWith(1, '/api/rail-transit/train-communication/online?page=1&page_size=200')
    expect(apiRequestMock).toHaveBeenNthCalledWith(2, '/api/rail-transit/train-communication/trains/train-1/diagnostics', { method: 'POST' })
    expect(apiRequestMock).toHaveBeenNthCalledWith(3, '/api/rail-transit/train-communication/diagnostics/task-1')
  })
})
