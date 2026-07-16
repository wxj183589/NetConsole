import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelVehicleMrOnlineTask,
  exportVehicleMrHistory,
  exportVehicleMrMappingTemplate,
  getVehicleMrOnlineTask,
  listVehicleMrEvents,
  listVehicleMrControllers,
  listVehicleMrMappings,
  listVehicleMrOnline,
  recoverVehicleMrOnlineTasks,
  refreshVehicleMrApMapping,
  refreshVehicleMrOnline,
  saveVehicleMrMappings,
  startVehicleMrCollection,
  stopVehicleMrCollection,
} from './vehicleMrOnline'

describe('vehicle MR online API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps CT/TC query, mapping writes and task lifecycle in the train-online boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await listVehicleMrOnline({ query: '01' })
    await listVehicleMrMappings()
    await listVehicleMrControllers()
    await listVehicleMrEvents('train-1')
    await refreshVehicleMrOnline()
    await refreshVehicleMrApMapping('train-1')
    await saveVehicleMrMappings([])
    await getVehicleMrOnlineTask('task-1')
    await cancelVehicleMrOnlineTask('task-1')
    await recoverVehicleMrOnlineTasks()
    await startVehicleMrCollection(7, 10)
    await stopVehicleMrCollection('task-2')
    await exportVehicleMrHistory('train-1', { station: '站点A' })
    await exportVehicleMrMappingTemplate()

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/rail-transit/train-online/trains?query=01',
      '/api/rail-transit/train-online/mappings',
      '/api/rail-transit/train-online/controllers',
      '/api/rail-transit/train-online/trains/train-1/events?limit=200',
      '/api/rail-transit/train-online/refresh',
      '/api/rail-transit/train-online/ap-mapping/refresh?train_id=train-1',
      '/api/rail-transit/train-online/mappings',
      '/api/rail-transit/train-online/tasks/task-1',
      '/api/rail-transit/train-online/tasks/task-1/cancel',
      '/api/rail-transit/train-online/tasks/recover',
      '/api/rail-transit/train-online/collection/start',
      '/api/rail-transit/train-online/collection/task-2/stop',
      '/api/rail-transit/train-online/history/export',
      '/api/rail-transit/train-online/mappings/template/export',
    ])
    expect(JSON.parse(fetchMock.mock.calls[6][1].body).explicit_confirmation).toBe(true)
  })
})
