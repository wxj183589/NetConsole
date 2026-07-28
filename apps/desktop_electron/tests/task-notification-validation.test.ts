import { describe, expect, it } from 'vitest'

import {
  validateTaskNotificationPayload,
  validateTaskTrayStatus,
} from '../src/shared/validation'

describe('task notification bridge validation', () => {
  it('accepts only the bounded notification DTO', () => {
    expect(validateTaskNotificationPayload({
      eventId: 'task-1:COMPLETED:2026-07-28T20:00:00',
      taskId: 'task-1',
      title: '批量更新已完成',
      body: '成功 27，失败 3',
      kind: 'warning',
    })).toEqual({
      eventId: 'task-1:COMPLETED:2026-07-28T20:00:00',
      taskId: 'task-1',
      title: '批量更新已完成',
      body: '成功 27，失败 3',
      kind: 'warning',
    })

    expect(() => validateTaskNotificationPayload({
      eventId: 'task-1',
      taskId: 'task-1',
      title: '完成',
      body: '结果',
      kind: 'success',
      route: '/tasks',
    })).toThrow('unsupported field: route')
    expect(() => validateTaskNotificationPayload({
      eventId: 'task-1',
      taskId: '../task-1',
      title: '完成',
      body: '结果',
      kind: 'success',
    })).toThrow('taskId is invalid')
  })

  it('accepts only bounded aggregate tray counts', () => {
    expect(validateTaskTrayStatus({ active: 2, failed: 1, warning: 3 })).toEqual({
      active: 2,
      failed: 1,
      warning: 3,
    })
    expect(() => validateTaskTrayStatus({ active: 1000, failed: 0, warning: 0 })).toThrow(
      'task tray active is invalid',
    )
    expect(() => validateTaskTrayStatus({ active: 1, failed: 0, warning: 0, tasks: [] })).toThrow(
      'unsupported field: tasks',
    )
  })
})
