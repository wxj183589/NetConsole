import { describe, expect, it } from 'vitest'

import source from './AgentListView.vue?raw'

describe('Agent list table contract', () => {
  it('uses shared tables for agents, tools, tasks and packages', () => {
    for (const tableId of ['agent-list', 'agent-tool-status', 'agent-remote-tasks', 'agent-remote-packages']) {
      expect(source).toContain(`table-id="${tableId}"`)
    }
    expect(source).toContain(':columns="agentColumns"')
    expect(source).toContain(':columns="toolColumns"')
    expect(source).toContain(':columns="remoteTaskColumns"')
    expect(source).toContain(':columns="packageColumns"')
    expect(source).not.toContain('<el-table')
  })

  it('keeps long paths and errors explicitly left aligned', () => {
    expect(source).toContain("alignmentReason: 'path'")
    expect(source).toContain("alignmentReason: 'long-text'")
  })

  it('keeps a successful task detail or log tail when its paired request fails', () => {
    expect(source).toContain('await Promise.allSettled([')
    expect(source).toContain('if (detail.status === \'fulfilled\') selectedTask.value = detail.value')
    expect(source).toContain('if (logs.status === \'fulfilled\') taskLogs.value = logs.value.lines')
    expect(source).toContain('部分远端任务数据刷新失败，已保留最后成功数据')
    expect(source).toContain('v-if="taskDetailError"')
    expect(source).not.toContain('const [detail, logs] = await Promise.all([')
  })
})
