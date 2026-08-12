import { describe, expect, it } from 'vitest'

import { startupStageLabel } from '../src/main/startup-progress-page'

describe('startup progress stage labels', () => {
  it.each([
    ['paths_resolved', '正在准备数据环境'],
    ['instance_lock_acquired', '正在检查运行状态'],
    ['storage_manifest_ready', '正在检查数据兼容性'],
    ['active_site_database_ready', '正在读取当前局点'],
    ['application_built', '正在初始化核心服务'],
    ['listener_ready', '本地核心服务已启动'],
    ['backend.health_ready', '本地服务已就绪'],
  ])('maps real stage %s to a user-facing label', (stage, label) => {
    expect(startupStageLabel(stage)).toBe(label)
  })

  it('does not expose an internal stage as a fallback label', () => {
    expect(startupStageLabel('unexpected_internal_stage')).toBe('正在初始化本地核心服务')
  })
})
