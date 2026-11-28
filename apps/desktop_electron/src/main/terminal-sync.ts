import { validateTerminalSyncRequest } from '../shared/terminal-sync'
import type { TerminalSyncEvent, TerminalSyncTarget } from '../shared/bridge'

export class TerminalSync {
  private readonly ready = new Set<string>()
  private selected: string[] = []

  constructor(private readonly options: {
    owner: (sender: unknown) => boolean
    detached: (sender: unknown) => string | undefined
    ids: () => string[]
    sendOwner: (event: TerminalSyncEvent) => void
    sendDetached: (id: string, event: TerminalSyncEvent) => void
  }) {}

  changed(id: string): void {
    if (!this.options.ids().includes(id)) {
      this.ready.delete(id)
      this.selected = this.selected.filter(item => item !== id)
    }
    this.options.sendOwner({ type: 'targets', targets: this.targets() })
  }

  disconnected(id: string): void {
    this.ready.delete(id)
    this.select(this.selected.filter(item => item !== id))
    this.changed(id)
  }

  clear(): void {
    this.select([])
  }

  request(value: unknown, sender: unknown, url: string): TerminalSyncTarget[] {
    const request = validateTerminalSyncRequest(value)
    const detached = this.options.detached(sender)
    const target = new URL(url)
    if (detached) {
      if (target.pathname !== '/console' || target.searchParams.get('terminal_session') !== detached) {
        throw new Error('独立终端同步请求无效')
      }
      if (request.action === 'input' && this.selected.includes(detached)) {
        const event = { type: 'input' as const, kind: request.kind, data: request.data, origin: detached }
        this.options.sendOwner(event)
        for (const id of this.selected) this.options.sendDetached(id, event)
        return []
      }
      if (request.action !== 'ready') throw new Error('独立终端同步请求无效')
      if (request.ready) this.ready.add(detached)
      else { this.disconnected(detached); return [] }
      this.changed(detached)
      return []
    }
    if (!this.options.owner(sender) || target.searchParams.has('terminal_session') || request.action === 'ready') {
      throw new Error('当前窗口无法管理终端同步')
    }
    if (target.pathname !== '/console' && request.action !== 'list' && !(request.action === 'select' && !request.ids.length)) {
      throw new Error('当前页面无法发送终端同步输入')
    }
    if (request.action === 'select') this.select(request.ids.filter(id => this.ready.has(id)))
    if (request.action === 'input') {
      for (const id of this.selected) this.options.sendDetached(id, { type: 'input', kind: request.kind, data: request.data })
    }
    return this.targets()
  }

  private select(ids: string[]): void {
    this.selected = ids
    for (const id of this.options.ids()) this.options.sendDetached(id, { type: 'member', selected: ids.includes(id) })
  }

  private targets(): TerminalSyncTarget[] {
    return this.options.ids().map(id => ({ id, ready: this.ready.has(id) }))
  }
}
