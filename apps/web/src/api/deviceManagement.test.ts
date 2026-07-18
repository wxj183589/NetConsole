import { afterEach, describe, expect, it, vi } from 'vitest'

import { getDeviceDetailSection, getDeviceEditProfile, getDeviceInterfaceDetail, getDeviceOverview } from './deviceManagement'

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
      status: 'up',
    })

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/device-management/devices/device%2F1/overview',
      '/api/device-management/devices/device%2F1/interfaces?page=2&page_size=20&search=Gigabit&status=up',
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
})
