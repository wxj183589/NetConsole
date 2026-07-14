import { describe, expect, it } from 'vitest'

import { activeTaskStatuses, taskStatusLabel, taskStatusType } from './taskStatus'

describe('task status helpers', () => {
  it('covers active and terminal states', () => {
    expect(activeTaskStatuses).toContain('RUNNING')
    expect(taskStatusLabel('COMPLETED')).toBe('已完成')
    expect(taskStatusType('FAILED')).toBe('danger')
    expect(taskStatusType('STOPPING')).toBe('warning')
    expect(taskStatusLabel('QUEUED')).toBe('排队中')
    expect(taskStatusLabel('UNKNOWN')).toBe('未知')
  })
})
