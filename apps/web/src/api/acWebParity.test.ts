import { describe, expect, it, vi } from 'vitest'

import { deleteAcFitAps, exportAcExtensions, getAcExternalTerminalOptions, getAcOmniPeekPreview, getAcWebTask, importAcFitApMetadata, openAcFitApExternalTerminal, recoverAcWebTasks, saveAcFitApMetadata, startAcLocalRebuild, startAcOmniPeekExport, startAcOmniPeekPreview, startAcResourceRefresh } from './acWebParity'

describe('AC Web parity API client', () => {
  it('submits only the local rebuild target and exposes task recovery', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ task_id: 'task-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await startAcLocalRebuild('optical', 'ac-1')
    await startAcResourceRefresh('fit-ap', 'ac-1')
    await deleteAcFitAps('ac-1', ['ap-1'])
    await importAcFitApMetadata(new File(['metadata'], 'metadata.csv', { type: 'text/csv' }))
    await saveAcFitApMetadata('ac-1', 'ap-1', { site_name: 'Web站', mileage: 'ZDK1+200', location_note: '站台', direction: '上行' })
    await exportAcExtensions('station-a', 'ac-1')
    await getAcWebTask('task-1')
    await recoverAcWebTasks()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/ac-management/local-rebuild/optical')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ac_id: 'ac-1' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/ac-management/refresh/fit-ap')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ ac_id: 'ac-1', ap_id: '' })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/ac-management/fit-aps/delete')
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ ac_id: 'ac-1', ap_ids: ['ap-1'], explicit_confirmation: true })
    expect(fetchMock.mock.calls[3][0]).toBe('/api/ac-management/fit-aps/metadata/import')
    expect(fetchMock.mock.calls[3][1].body).toBeInstanceOf(FormData)
    expect(fetchMock.mock.calls[4][0]).toBe('/api/ac-management/aps/ap-1/metadata')
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ ac_id: 'ac-1', site_name: 'Web站', mileage: 'ZDK1+200', location_note: '站台', direction: '上行' })
    expect(fetchMock.mock.calls[5][0]).toBe('/api/ac-management/extensions/export?search=station-a&ac_id=ac-1')
    expect(fetchMock.mock.calls[5][1].method).toBe('POST')
    expect(fetchMock.mock.calls[6][0]).toBe('/api/ac-management/web-tasks/task-1')
    expect(fetchMock.mock.calls[7][0]).toBe('/api/ac-management/web-tasks/recover')
  })

  it('submits only current AC/AP scope for OmniPeek and semantic terminal type', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const config = {
      line_name: '测试线', include_ac_fit_ap: true, include_ap_extensions: true, include_device_mr: false,
      export_trackside_physical: true, export_trackside_r1: true, export_trackside_r2: true,
      export_onboard_physical: true, export_onboard_r1: true, export_onboard_r2: true,
      onboard_radio_mode: 'auto' as const, enable_h3c_derivation: true, colors: {},
    }

    await startAcOmniPeekPreview('ac-1', ['ap-1', 'ap-2'], config)
    await getAcOmniPeekPreview('preview-1')
    await startAcOmniPeekExport('ac-1', [], { ...config, selected_item_keys: [], excluded_item_keys: [], force_export_keys: [] })
    await getAcExternalTerminalOptions()
    await openAcFitApExternalTerminal('ap-1', 'ac-1', 'securecrt')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/ac-management/fit-aps/omnipeek/preview')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ac_id: 'ac-1', ap_ids: ['ap-1', 'ap-2'], ...config })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/ac-management/fit-aps/omnipeek/preview/preview-1')
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ ac_id: 'ac-1', ap_ids: [], ...config, selected_item_keys: [], excluded_item_keys: [], force_export_keys: [] })
    expect(fetchMock.mock.calls[3][0]).toBe('/api/ac-management/fit-aps/external-terminal/options')
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ ac_id: 'ac-1', terminal_type: 'securecrt' })
    expect(fetchMock.mock.calls[4][1].body).not.toContain('executable')
    expect(fetchMock.mock.calls[4][1].body).not.toContain('arguments')
    expect(fetchMock.mock.calls[4][1].body).not.toContain('protocol')
    expect(fetchMock.mock.calls[4][1].body).not.toContain('port')
    expect(fetchMock.mock.calls[4][1].body).not.toContain('username')
    expect(fetchMock.mock.calls[4][1].body).not.toContain('password')
  })
})
