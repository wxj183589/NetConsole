import { describe, expect, it, vi } from 'vitest'

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('./client', () => ({
  apiRequest: apiRequestMock,
}))

import { getTrainCommunicationCheck, startTrainCommunicationCheck } from './trainCommunication'

describe('train communication API', () => {
  it('uses the formal diagnostics endpoints', () => {
    startTrainCommunicationCheck('train-1')
    getTrainCommunicationCheck('task-1')

    expect(apiRequestMock).toHaveBeenNthCalledWith(1, '/api/rail-transit/train-communication/trains/train-1/diagnostics', { method: 'POST' })
    expect(apiRequestMock).toHaveBeenNthCalledWith(2, '/api/rail-transit/train-communication/diagnostics/task-1')
  })
})
