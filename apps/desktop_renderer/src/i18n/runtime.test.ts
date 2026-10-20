import { afterEach, describe, expect, it } from 'vitest'

import {
  acActionPlanReasonLabel,
  acActionPlanReconciliationLabel,
  acActionPlanStatusLabel,
  setAppLocale,
  t,
  taskTriggerSourceLabel,
} from './runtime'

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

  it('localizes AC action-plan states and diagnostics without exposing protocol codes', () => {
    setAppLocale('zh_CN')
    expect(acActionPlanStatusLabel('COMPLETED')).toBe('已完成')
    expect(acActionPlanStatusLabel('EXECUTING')).toBe('执行中')
    expect(acActionPlanStatusLabel('UNKNOWN_OR_UNVERIFIED')).toBe('结果无法核验')
    expect(acActionPlanReconciliationLabel('VERIFIED_TERMINAL')).toBe('已根据任务记录核验执行结果')
    expect(acActionPlanReasonLabel('TASK_HISTORY_CLEANED')).toBe('任务历史已清理，无法核实原执行结果')
    expect(acActionPlanReasonLabel('TASK_SITE_MISMATCH')).toBe('任务归属局点不一致，无法确认结果')
    expect(acActionPlanReasonLabel('future-code')).toBe('原因无法核验')

    setAppLocale('en_US')
    expect(acActionPlanStatusLabel('FAILED')).toBe('Failed')
    expect(acActionPlanReconciliationLabel('VERIFIED_TERMINAL')).toBe('Execution result verified from task record')
    expect(acActionPlanReasonLabel('TASK_SITE_MISMATCH')).toBe('Task belongs to a different site; the result cannot be confirmed')
    expect(acActionPlanStatusLabel('future-code')).toBe('Unknown status')
  })
})
