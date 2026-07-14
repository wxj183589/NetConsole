import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  configArtifactUrl,
  getConfigTask,
  listConfigDevices,
  submitConfigCollection,
} from './configCollection'

afterEach(() => vi.restoreAllMocks())

describe('config collection api client', () => {
  it('builds filtered device requests without credentials or paths', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 50, total_pages: 1, groups: [] }), { status: 200 }),
    )

    await listConfigDevices({ search: 'SW 01', group_filter: '__ungrouped__', page: 2, page_size: 20 })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/config-collection/devices?search=SW+01&group_filter=__ungrouped__&page=2&page_size=20',
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
    expect(fetchMock.mock.calls[0][0]).not.toContain('password')
  })

  it('submits only the read-only collection action', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([]), { status: 202 }),
    )

    await submitConfigCollection([7, 8])

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ action: 'fetch', device_ids: [7, 8] })
    expect(String(fetchMock.mock.calls[0][1]?.body)).not.toContain('save')
  })

  it('keeps task ids encoded and artifact urls opaque', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'config-web/1' }), { status: 200 }),
    )

    await getConfigTask('config-web/1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/config-collection/tasks/config-web%2F1')
    expect(configArtifactUrl('snapshot-7')).toBe('/api/config-collection/artifacts/snapshot-7')
    expect(configArtifactUrl('../secrets.txt')).toContain('%2F')
  })
})
