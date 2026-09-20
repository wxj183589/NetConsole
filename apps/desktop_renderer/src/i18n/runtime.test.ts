import { afterEach, describe, expect, it } from 'vitest'

import { setAppLocale, t, taskTriggerSourceLabel } from './runtime'

describe('Desktop Renderer runtime i18n', () => {
  afterEach(() => setAppLocale('zh_CN'))

  it('uses Desktop Renderer terminology in the English shell', () => {
    setAppLocale('en_US')

    expect(t('shell.console')).toBe('NetConsole')
    expect(t('shell.build_mismatch')).toBe(
      'The Desktop Renderer resources do not match the backend version. Rebuild the Desktop Renderer resources.',
    )
  })

  it('localizes task trigger sources and falls back safely for unknown values', () => {
    setAppLocale('zh_CN')
    expect(taskTriggerSourceLabel('api')).toBe('API 调用')
    expect(taskTriggerSourceLabel('scheduler')).toBe('调度器')
    expect(taskTriggerSourceLabel('retry')).toBe('重试')
    expect(taskTriggerSourceLabel('recovery')).toBe('恢复')
    expect(taskTriggerSourceLabel('unknown')).toBe('未知')
    expect(taskTriggerSourceLabel('future-trigger')).toBe('未知')

    setAppLocale('en_US')
    expect(taskTriggerSourceLabel('api')).toBe('API request')
    expect(taskTriggerSourceLabel('future-trigger')).toBe('Unknown')
  })
})
