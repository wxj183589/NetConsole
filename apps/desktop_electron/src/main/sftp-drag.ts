import { randomUUID } from 'node:crypto'
import { mkdir, mkdtemp, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { validateBackendDownloadRequest } from '../shared/validation'
import type { BackendDownloadManager } from './backend-download'
import type { GrantedPathRegistry } from './path-access'

export class SftpDragManager {
  private prepared = new Map<string, { owner: unknown; files: string[]; root: string; timer: ReturnType<typeof setTimeout> }>()
  constructor(private root: string, private downloads: BackendDownloadManager, private paths: GrantedPathRegistry) {}

  async prepare(value: unknown, owner: unknown): Promise<{ dragId: string }> {
    if (!Array.isArray(value) || !value.length || value.length > 32 || this.prepared.size >= 8) throw new Error('拖出文件数量超过限制')
    const requests = value.map(item => {
      const request = validateBackendDownloadRequest(item)
      if (!/^\/api\/terminal\/sftp\/transfers\/[a-f0-9]{32}\/file$/.test(request.apiPath) || request.destinationPath || request.expectedSha256 === undefined || request.expectedSizeBytes === undefined) throw new Error('拖出只允许已校验 SFTP 文件')
      return request
    })
    await mkdir(this.root, { recursive: true })
    const directory = await mkdtemp(resolve(this.root, 'drag-'))
    const files: string[] = []
    try {
      for (const [index, request] of requests.entries()) {
        const folder = resolve(directory, String(index))
        await mkdir(folder)
        const file = resolve(folder, request.suggestedName)
        const destinationPath = await this.paths.grantSavePath(file)
        const result = await this.downloads.download({ ...request, destinationPath })
        if (result.status !== 'saved') throw new Error(result.error || '拖出文件下载失败')
        files.push(file)
      }
      const dragId = randomUUID()
      const timer = setTimeout(() => { void this.discard(dragId) }, 10 * 60_000)
      timer.unref()
      this.prepared.set(dragId, { owner, files, root: directory, timer })
      return { dragId }
    } catch (error) { await rm(directory, { recursive: true, force: true }); throw error }
  }

  start(id: unknown, owner: unknown, start: (files: string[]) => void) {
    if (typeof id !== 'string') throw new Error('拖放标识无效')
    const value = this.prepared.get(id)
    if (!value || value.owner !== owner) throw new Error('拖放授权已失效')
    start(value.files)
    // Native drag is a handoff, never evidence that Explorer committed the copy.
  }

  private async discard(id: string) {
    const value = this.prepared.get(id)
    if (!value) return
    this.prepared.delete(id)
    clearTimeout(value.timer)
    await rm(value.root, { recursive: true, force: true })
  }

  async shutdown() { await Promise.allSettled([...this.prepared.keys()].map(id => this.discard(id))) }
}
