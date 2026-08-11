// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest'

import { onTaskCenterOpenRequested, requestTaskCenterOpen } from './events'

describe('task center open events', () => {
  it('opens the root task center without depending on the Electron bridge', () => {
    const listener = vi.fn()
    const remove = onTaskCenterOpenRequested(listener)

    requestTaskCenterOpen({ taskId: 'task-1', module: 'devices' })

    expect(listener).toHaveBeenCalledWith({ taskId: 'task-1', module: 'devices' })
    remove()
    requestTaskCenterOpen({ taskId: 'task-2' })
    expect(listener).toHaveBeenCalledOnce()
  })
})
