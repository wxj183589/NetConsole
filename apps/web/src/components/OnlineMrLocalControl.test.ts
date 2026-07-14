import { describe, expect, it } from 'vitest'

import source from './OnlineMrLocalControl.vue?raw'

describe('Online MR local control', () => {
  it('exposes only local normal start and stop controls', () => {
    expect(source).toContain('本地 Online MR 采集')
    expect(source).toContain('启动本地采集')
    expect(source).toContain('正常停止并落盘')
    expect(source).toContain("executor: 'LOCAL'")
    expect(source).not.toMatch(/强制停止|删除会话|删除采集包|Agent 启动|Agent 停止/)
    expect(source).not.toMatch(/username|password|command|output_dir|database_path|agent_url/)
  })

  it('polls status and unmount only clears polling', () => {
    expect(source).toContain('active.value ? 1_500 : 5_000')
    expect(source).toContain('getOnlineMrControlStatus')
    expect(source).toContain('getOnlineMrControlOperation')
    expect(source).toContain('onBeforeUnmount')
    expect(source).toContain('clearTimer()')
    expect(source).not.toContain('onBeforeUnmount(stop')
  })

  it('shows disabled, terminal package and acceptance states', () => {
    expect(source).toContain('Web 本地控制默认关闭')
    expect(source).toContain('正在等待 Traffic flush')
    expect(source).toContain('package_path_reference')
    expect(source).toContain('复制验收命令')
  })
})
