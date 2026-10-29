import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cancelVehicleMrOnlineTask,
  exportVehicleMrHistory,
  exportVehicleMrMappingTemplate,
  getVehicleMrOnlineDetail,
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

    await listVehicleMrOnline({ query: '01', overall_status: 'BOTH_ONLINE', unmatched_only: true })
    await listVehicleMrMappings()
    await listVehicleMrControllers()
    await listVehicleMrEvents('train-1')
    await getVehicleMrOnlineDetail('train-1')
    await refreshVehicleMrOnline('ac-uuid-1')
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
      '/api/rail-transit/train-online/trains?query=01&overall_status=BOTH_ONLINE&unmatched_only=true',
      '/api/rail-transit/train-online/mappings',
      '/api/rail-transit/train-online/controllers',
      '/api/rail-transit/train-online/trains/train-1/events?limit=200',
      '/api/rail-transit/train-online/trains/train-1',
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
    expect(JSON.parse(fetchMock.mock.calls[5][1].body)).toEqual({ controller_id: 'ac-uuid-1', include_switch_history: false })
    expect(JSON.parse(fetchMock.mock.calls[7][1].body).explicit_confirmation).toBe(true)
  })

  it('serializes multi-value status filters as repeated query keys', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await listVehicleMrOnline({ overall_status: ['BOTH_ONLINE', 'BOTH_OFFLINE'], data_status: ['FRESH', 'NO_DATA'] })
    await listVehicleMrEvents('train-1', { car_end_label: ['TC1', 'TC2'], event_status: ['在线', '离线'] })

    const trainUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost')
    expect(trainUrl.searchParams.getAll('overall_status')).toEqual(['BOTH_ONLINE', 'BOTH_OFFLINE'])
    expect(trainUrl.searchParams.getAll('data_status')).toEqual(['FRESH', 'NO_DATA'])
    const eventUrl = new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost')
    expect(eventUrl.searchParams.getAll('car_end_label')).toEqual(['TC1', 'TC2'])
    expect(eventUrl.searchParams.getAll('event_status')).toEqual(['在线', '离线'])
  })
})
