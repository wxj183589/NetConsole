import { afterEach, describe, expect, it, vi } from 'vitest'

import { getBatchRefresh, getDeviceDetailSection, getDeviceEditProfile, getDeviceInterfaceDetail, getDeviceOverview, previewDeviceImport } from './deviceManagement'

describe('device detail API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps overview and paginated section requests separate', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await getDeviceOverview('device/1')
    await getDeviceDetailSection('device/1', 'interfaces', {
      page: 2,
      page_size: 20,
      search: 'Gigabit',
      status: 'PHYSICAL_DOWN',
      admin_status: 'up',
      physical_status: 'down',
      protocol_status: 'down',
      media_type: 'optical',
      sort_by: 'description',
      sort_order: 'desc',
    })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/device-management/devices/device%2F1/overview',
      '/api/device-management/devices/device%2F1/interfaces?page=2&page_size=20&search=Gigabit&status=PHYSICAL_DOWN&admin_status=up&physical_status=down&protocol_status=down&media_type=optical&sort_by=description&sort_order=desc',
    ])
  })

  it('uses the formal interface detail path-segment route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await getDeviceInterfaceDetail('device/1', 'GigabitEthernet 1/0/1', controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/device-management/devices/device%2F1/interfaces/GigabitEthernet%201%2F0%2F1',
      expect.objectContaining({ credentials: 'same-origin', signal: controller.signal }),
    )
  })

  it('loads the narrow edit profile route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await getDeviceEditProfile('device/1', controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/device-management/devices/device%2F1/edit-profile',
      expect.objectContaining({ credentials: 'same-origin', signal: controller.signal }),
    )
  })

  it('keeps optical severity and task status transport enums separate', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await getDeviceDetailSection('device-1', 'optical', { page: 1, page_size: 20, status: 'warning' })
    await getDeviceDetailSection('device-1', 'tasks', { page: 1, page_size: 20, status: 'RUNNING' })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/device-management/devices/device-1/transceivers?page=1&page_size=20&severity=warning',
      '/api/device-management/devices/device-1/tasks?page=1&page_size=20&status=RUNNING',
    ])
  })

  it('queries a batch refresh by its opaque encoded id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await getBatchRefresh('batch/1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/device-management/batch-refreshes/batch%2F1',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('sends the explicit site-IP match strategy and update mode with import preview', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['设备名称,主用地址\nA,192.0.2.1'], 'devices.csv', { type: 'text/csv' })

    await previewDeviceImport(file, 'SITE_PRIMARY_IP', 'UPDATE_ONLY')

    const options = fetchMock.mock.calls[0][1] as RequestInit
    const body = options.body as FormData
    expect(fetchMock.mock.calls[0][0]).toBe('/api/device-management/imports/preview')
    expect(body.get('file')).toBe(file)
    expect(body.get('match_strategy')).toBe('SITE_PRIMARY_IP')
    expect(body.get('write_mode')).toBe('UPDATE_ONLY')
  })
})
