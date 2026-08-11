import { describe, expect, it } from 'vitest'

import source from './TrafficRunHistory.vue?raw'

describe('Traffic run history table contract', () => {
  it('uses the shared table without changing task actions', () => {
    expect(source).toContain('table-id="traffic-run-history"')
    expect(source).toContain(':columns="columns"')
    expect(source).not.toContain('<el-table')
    expect(source).toContain("$emit('select', row)")
    expect(source).toContain("$emit('task', row)")
    expect(source).toContain("$emit('cancel', row)")
    expect(source).toContain("$emit('retry', row)")
  })
})
