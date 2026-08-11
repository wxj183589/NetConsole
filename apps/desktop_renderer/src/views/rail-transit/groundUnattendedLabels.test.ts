import { describe, expect, it } from 'vitest'

import {
  groundEventLabel,
  groundOperationStageLabel,
  groundSeverityLabel,
  groundStatusLabel,
  groundTransitionContextLabel,
} from './groundUnattendedLabels'

describe('ground unattended Chinese labels', () => {
  it('maps stable backend codes without leaking unknown codes into main views', () => {
    expect(groundStatusLabel('MAINLINE')).toBe('正线在线')
    expect(groundStatusLabel('READY')).toBe('归档完成')
    expect(groundEventLabel('mesh_activelink_switch')).toBe('WMESH 主链路切换')
    expect(groundSeverityLabel('critical')).toBe('严重')
    expect(groundOperationStageLabel('STOPPING_SYSLOG')).toBe('正在停止 Syslog 接收')
    expect(groundStatusLabel('OPEN')).toBe('正在写入')
    expect(groundStatusLabel('WAITING_FIRST_LOG')).toBe('等待首条日志')
    expect(groundTransitionContextLabel('AFTER_AP_TRANSITION')).toBe('AP 切换后')
    expect(groundStatusLabel('BOTH_MATCHED')).toBe('两端已解析')
    expect(groundStatusLabel('OLD_ONLY_MATCHED')).toBe('仅原 AP 已解析')
    expect(groundStatusLabel('NEW_ONLY_MATCHED')).toBe('仅当前 AP 已解析')
    expect(groundStatusLabel('BOTH_NOT_FOUND')).toBe('两端未解析')
    expect(groundStatusLabel('OLD_CONFLICT')).toBe('原 AP 身份冲突')
    expect(groundStatusLabel('NEW_CONFLICT')).toBe('当前 AP 身份冲突')
    expect(groundStatusLabel('BOTH_CONFLICT')).toBe('两端 AP 身份冲突')
    expect(groundStatusLabel('INVALID_MAC')).toBe('MAC 格式异常')
    expect(groundStatusLabel('NO_AP_ENDPOINT')).toBe('存在无主链路端点')
    expect(groundTransitionContextLabel('')).toBe('否')
    expect(groundStatusLabel('FUTURE_INTERNAL_CODE')).toBe('未知状态')
  })
})
