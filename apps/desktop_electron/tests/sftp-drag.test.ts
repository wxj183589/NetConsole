import { createHash } from 'node:crypto'
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { describe, it, expect, vi } from 'vitest'
import { SftpDragManager } from '../src/main/sftp-drag'
import { BackendDownloadManager } from '../src/main/backend-download'
import { GrantedPathRegistry } from '../src/main/path-access'

describe('SFTP native file handoff', () => {
  it('prepares verified real files, binds sender, and cleans its staging on shutdown', async () => {
    const root = await mkdtemp(resolve(tmpdir(), 'sftp-native-drag-'))
    const paths = new GrantedPathRegistry()
    const payload = Buffer.from('中文配置')
    const manager = new BackendDownloadManager({
      backend: { getRuntimeInfo: () => ({ baseUrl: 'http://127.0.0.1:18199', apiToken: 'a'.repeat(48) }) },
      dialog: { showSaveDialog: vi.fn() }, window: {}, pathRegistry: paths,
      fetchImpl: vi.fn(async () => new Response(payload)),
    })
    const drag = new SftpDragManager(root, manager, paths)
    const owner = {}
    try {
      const request = { apiPath: `/api/terminal/sftp/transfers/${'a'.repeat(32)}/file`, suggestedName: '中文.cfg', expectedSizeBytes: payload.length, expectedSha256: createHash('sha256').update(payload).digest('hex') }
      const prepared = await drag.prepare([request, { ...request, suggestedName: '目录.zip' }], owner)
      expect(() => drag.start(prepared.dragId, {}, () => undefined)).toThrow('授权')
      let files: string[] = []
      drag.start(prepared.dragId, owner, value => { files = value })
      expect(files).toHaveLength(2)
      for (const file of files) expect(await readFile(file)).toEqual(payload)
      await expect(drag.prepare([{ ...request, destinationPath: 'D:/arbitrary.cfg' }], owner)).rejects.toThrow()
      await expect(drag.prepare([{ ...request, expectedSha256: 'f'.repeat(64) }], owner)).rejects.toThrow()
      await drag.shutdown()
      expect(await readdir(root)).toEqual([])
    } finally { await drag.shutdown(); await manager.shutdown(); await rm(root, { recursive: true, force: true }) }
  })
})
