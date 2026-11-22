import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  closeTerminalSession,
  createTerminalSession,
  createTerminalProfileFolder,
  connectTerminalProfile,
  getTerminalHistoryEvents,
  issueTerminalTicket,
  listTerminalHistory,
  listTerminalProfiles,
  quickConnectTerminalSession,
  reconnectTerminalSession,
  terminalExportDownloadRequest,
} from './terminal'

describe('terminal API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses scoped session lifecycle endpoints and encodes identifiers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await createTerminalSession('device/1', 'SSH', 132, 40)
    await issueTerminalTicket('session/1')
    await reconnectTerminalSession('session/1')
    await closeTerminalSession('session/1')

    expect(fetchMock.mock.calls.map((call) => [call[0], call[1]?.method || 'GET'])).toEqual([
      ['/api/terminal/sessions', 'POST'],
      ['/api/terminal/sessions/session%2F1/ticket', 'POST'],
      ['/api/terminal/sessions/session%2F1/reconnect', 'POST'],
      ['/api/terminal/sessions/session%2F1', 'DELETE'],
    ])
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      device_uuid: 'device/1', protocol: 'SSH', cols: 132, rows: 40,
    })
  })

  it('keeps quick connections and saved profiles on dedicated terminal endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)

    await quickConnectTerminalSession({
      name: 'LAB-SW', host: '192.0.2.10', port: 22, protocol: 'SSH',
      username: 'operator', password: 'secret', encoding: 'gb18030',
      vendor: 'H3C', device_type: 'SW', folder_id: '', favorite: true,
      save_profile: true, remember_password: true,
    })
    await listTerminalProfiles()
    await connectTerminalProfile('profile/1', 'override')
    await createTerminalProfileFolder('核心交换机')

    expect(fetchMock.mock.calls.map((call) => [call[0], call[1]?.method || 'GET'])).toEqual([
      ['/api/terminal/sessions/quick-connect', 'POST'],
      ['/api/terminal/profiles', 'GET'],
      ['/api/terminal/profiles/profile%2F1/connect', 'POST'],
      ['/api/terminal/profile-folders', 'POST'],
    ])
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      host: '192.0.2.10', password: 'secret', save_profile: true, remember_password: true,
    })
  })

  it('keeps history pagination and user-file export contracts explicit', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) })
    vi.stubGlobal('fetch', fetchMock)

    await listTerminalHistory('LAB SW', 25)
    await getTerminalHistoryEvents('abc/123', 40, 500)

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/terminal/history?keyword=LAB+SW&limit=25',
      '/api/terminal/history/abc%2F123/events?offset=40&limit=500',
    ])
    expect(terminalExportDownloadRequest('abc/123', 'jsonl')).toEqual({
      apiPath: '/api/terminal/history/abc%2F123/export/jsonl',
      suggestedName: 'terminal-abc-123.jsonl',
    })
  })
})
