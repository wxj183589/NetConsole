import { describe, expect, it, vi } from 'vitest'
import { TerminalSync } from '../src/main/terminal-sync'

const idA = 'a'.repeat(32)
const idB = 'b'.repeat(32)
const ownerUrl = 'https://desktop.test/console'
const detachedUrl = (id: string) => `${ownerUrl}?terminal_session=${id}`

describe('desktop terminal synchronization', () => {
  it('isolates unknown and unselected windows, then drops closed members', () => {
    let ids = [idA, idB]
    const sendOwner = vi.fn()
    const sendDetached = vi.fn()
    const sync = new TerminalSync({
      owner: sender => sender === 'owner',
      detached: sender => ids.includes(String(sender)) ? String(sender) : undefined,
      ids: () => ids,
      sendOwner,
      sendDetached,
    })
    const ready = { action: 'ready', ready: true }
    const input = { action: 'input', kind: 'keys', data: 'text' }
    expect(() => sync.request(ready, idA, detachedUrl(idB))).toThrow()
    expect(() => sync.request(input, 'other-workspace', ownerUrl)).toThrow()
    sync.request(ready, idA, detachedUrl(idA))
    sync.request(ready, idB, detachedUrl(idB))
    sync.request({ action: 'select', ids: [idA] }, 'owner', ownerUrl)
    sendDetached.mockClear()
    sync.request(input, 'owner', ownerUrl)
    expect(sendDetached.mock.calls).toEqual([[idA, { type: 'input', kind: 'keys', data: 'text' }]])
    expect(() => sync.request(input, idB, detachedUrl(idB))).toThrow()
    sync.request(input, idA, detachedUrl(idA))
    expect(sendOwner).toHaveBeenLastCalledWith({ type: 'input', origin: idA, kind: 'keys', data: 'text' })
    ids = [idB]
    sync.changed(idA)
    sendDetached.mockClear()
    sync.request(input, 'owner', ownerUrl)
    expect(sendDetached).not.toHaveBeenCalled()
  })
})
