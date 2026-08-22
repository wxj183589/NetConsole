import { describe, expect, it, vi } from 'vitest'

import { prepareWarmBackendHandoff, type WarmHandoffBackend } from '../src/main/backend-handoff'

function backend(name: string, events: string[]): WarmHandoffBackend {
  return {
    start: vi.fn(async () => {
      events.push(`${name}:ready`)
      return { baseUrl: `http://127.0.0.1:${name === 'old' ? 8100 : 8200}`, apiToken: `${name}-token` }
    }),
    stop: vi.fn(async () => { events.push(`${name}:stopped`) }),
  }
}

describe('prepareWarmBackendHandoff', () => {
  it('keeps the current Backend alive until the candidate is ready, verified, and committed', async () => {
    const events: string[] = []
    const current = backend('old', events)
    const candidate = backend('new', events)

    const result = await prepareWarmBackendHandoff({
      current,
      candidate,
      verify: async () => { events.push('new:verified') },
      commit: async () => { events.push('new:committed') },
    })

    expect(events).toEqual(['new:ready', 'new:verified', 'new:committed'])
    expect(current.stop).not.toHaveBeenCalled()
    expect(result.active).toBe(candidate)
    expect(result.retired).toBe(current)
  })

  it('stops only the candidate when verification fails', async () => {
    const events: string[] = []
    const current = backend('old', events)
    const candidate = backend('new', events)

    await expect(prepareWarmBackendHandoff({
      current,
      candidate,
      verify: async () => { throw new Error('wrong site') },
      commit: async () => { events.push('unexpected commit') },
    })).rejects.toThrow('wrong site')

    expect(events).toEqual(['new:ready', 'new:stopped'])
    expect(current.stop).not.toHaveBeenCalled()
  })

  it('rolls back a partial commit before stopping the candidate', async () => {
    const events: string[] = []
    const current = backend('old', events)
    const candidate = backend('new', events)

    await expect(prepareWarmBackendHandoff({
      current,
      candidate,
      verify: async () => { events.push('new:verified') },
      commit: async () => {
        events.push('new:commit-started')
        throw new Error('cookie write failed')
      },
      rollback: async () => { events.push('old:restored') },
    })).rejects.toThrow('cookie write failed')

    expect(events).toEqual([
      'new:ready',
      'new:verified',
      'new:commit-started',
      'old:restored',
      'new:stopped',
    ])
    expect(current.stop).not.toHaveBeenCalled()
  })
})
