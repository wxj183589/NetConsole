import { describe, expect, it } from 'vitest'

import source from './OnlineMrLocalControl.vue?raw'

describe('Online MR local control', () => {
  it('exposes local start, normal stop, force stop and restart recovery controls', () => {
    expect(source).toContain('本地 Online MR 采集')
    expect(source).toContain('启动本地采集')
    expect(source).toContain('正常停止并落盘')
    expect(source).toContain("executor: 'LOCAL'")
    expect(source).toContain('强制停止')
    expect(source).toContain('重启恢复')
    expect(source).toContain('forceStopOnlineMrControl')
    expect(source).toContain('recoverOnlineMrControl')
    expect(source).not.toMatch(/删除会话|删除采集包|Agent 启动|Agent 停止/)
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

  it('uses backend presets and the new fping defaults for fresh configs', () => {
    expect(source).toContain('getOnlineMrControlPresets')
    expect(source).toContain('pis_high_ping_acceptance')
    expect(source).toContain('interval_ms: 10')
    expect(source).toContain('timeout_ms: 100')
    expect(source).toContain('loss_warn_percent: 0.7')
  })

  it('exposes TCP rate limit without total-limit wording', () => {
    expect(source).toContain('tcp_rate_limit_mbps')
    expect(source).toContain('TCP 限速 Mbps')
    expect(source).not.toContain('TCP 总限速')
  })

  it('uses unified Radio by default and keeps per-collector advanced controls', () => {
    expect(source).toContain("radio_mode: 'unified'")
    expect(source).toContain('Radio ID')
    expect(source).toContain('分别设置 Radio')
    expect(source).toContain('高级：分别设置 Radio')
    expect(source).toContain('collector_radio_ids')
  })

  it('locks the authorized real-device traffic parameters', () => {
    expect(source).toContain('real_device_test')
    expect(source).toContain("config.fping.interval_ms = 1000")
    expect(source).toContain("config.fping.timeout_ms = 4000")
    expect(source).toContain("config.iperf.server_ip = '127.0.0.1'")
    expect(source).toContain("config.iperf.protocol = 'TCP'")
    expect(source).toContain('iPerf 固定 127.0.0.1、TCP、2M')
    expect(source).toContain("emit('refresh')")
  })
})
