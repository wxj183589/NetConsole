import { describe, expect, it, vi } from 'vitest'

import {
  TaskNotificationController,
  type TaskNotificationLike,
} from '../src/main/task-notification'

const payload = {
  eventId: 'task-1:FAILED:3',
  taskId: 'task-1',
  title: '配置采集失败',
  body: 'SSH 认证失败',
  kind: 'failure' as const,
}

describe('TaskNotificationController', () => {
  it('shows one native notification and activates the matching task on click', async () => {
    let click: (() => void) | undefined
    const notification: TaskNotificationLike = {
      on: vi.fn((_event, listener) => { click = listener }),
      show: vi.fn(),
    }
    const activateTask = vi.fn()
    const controller = new TaskNotificationController({
      createNotification: vi.fn(() => notification),
      activateTask,
      logger: vi.fn(),
    })

    expect(controller.show(payload)).toEqual({ success: true })
    expect(controller.show(payload)).toEqual({ success: true })
    expect(notification.show).toHaveBeenCalledOnce()

    click?.()
    expect(activateTask).toHaveBeenCalledWith('task-1')
  })

  it('fails closed when native notifications are unavailable', () => {
    const controller = new TaskNotificationController({
      createNotification: () => { throw new Error('unsupported') },
      activateTask: vi.fn(),
      logger: vi.fn(),
    })

    expect(controller.show(payload)).toEqual({ success: false, error: '系统通知不可用' })
  })

  it('deduplicates background requests when any managed window is focused', () => {
    const createNotification = vi.fn()
    const logger = vi.fn()
    const controller = new TaskNotificationController({
      createNotification,
      activateTask: vi.fn(),
      isApplicationFocused: () => true,
      logger,
    })

    expect(controller.show(payload)).toEqual({ success: true })
    expect(controller.show(payload)).toEqual({ success: true })
    expect(createNotification).not.toHaveBeenCalled()
    expect(logger).toHaveBeenCalledWith('ELECTRON_TASK_NOTIFICATION_FOREGROUND_SKIPPED')
    expect(logger).toHaveBeenCalledWith('ELECTRON_TASK_NOTIFICATION_DUPLICATE_SKIPPED')
  })
})
