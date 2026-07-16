import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelVehicleMrOnlineTask,
  getVehicleMrOnlineTask,
  listVehicleMrEvents,
  listVehicleMrMappings,
  listVehicleMrOnline,
  recoverVehicleMrOnlineTasks,
  refreshVehicleMrApMapping,
  refreshVehicleMrOnline,
  saveVehicleMrMappings,
} from './vehicleMrOnline'

describe('vehicle MR online API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps CT/TC query, mapping writes and task lifecycle in the train-online boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await listVehicleMrOnline({ query: '01' })
    await listVehicleMrMappings()
    await listVehicleMrEvents('train-1')
    await refreshVehicleMrOnline()
    await refreshVehicleMrApMapping('train-1')
    await saveVehicleMrMappings([])
    await getVehicleMrOnlineTask('task-1')
    await cancelVehicleMrOnlineTask('task-1')
    await recoverVehicleMrOnlineTasks()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/train-online/trains?query=01',
      '/api/rail-transit/train-online/mappings',
      '/api/rail-transit/train-online/trains/train-1/events?limit=200',
      '/api/rail-transit/train-online/refresh',
      '/api/rail-transit/train-online/ap-mapping/refresh?train_id=train-1',
      '/api/rail-transit/train-online/mappings',
      '/api/rail-transit/train-online/tasks/task-1',
      '/api/rail-transit/train-online/tasks/task-1/cancel',
      '/api/rail-transit/train-online/tasks/recover',
    ])
  })
})
