import { currentAppLocale } from './runtime'

const messages: Record<string, [string, string]> = {
  title: ['网络服务日志', 'Network service logs'],
  service: ['服务', 'Service'],
  level: ['日志级别', 'Log level'],
  allLevels: ['全部级别', 'All levels'],
  keyword: ['搜索日志', 'Search logs'],
  start: ['开始时间', 'Start time'],
  end: ['结束时间', 'End time'],
  live: ['实时刷新', 'Live refresh'],
  history: ['轮转历史', 'Rotated history'],
  refresh: ['刷新', 'Refresh'],
  time: ['时间', 'Time'],
  message: ['消息', 'Message'],
  tail: ['当前日志尾部', 'Current log tail'],
  tailHelp: ['筛选范围为当前服务日志末尾，最多 150 行。轮转历史不包含在本查询中。', 'Filters apply to the current service log tail, up to 150 lines. Rotated history is outside this query.'],
  historyHelp: ['查询当前及两份轮转日志的尾部，最多 1500 行，每文件最多读取 250 KiB。时间段不会扩大保留范围。', 'Queries the current and two rotated log tails, up to 1500 lines and 250 KiB per file. Time filters do not expand retention.'],
  empty: ['暂无匹配日志', 'No matching logs'],
  select: ['请选择服务', 'Select a service'],
  failed: ['读取服务日志失败', 'Could not read service logs'],
}

export function serviceLogLabel(key: string): string {
  return messages[key]?.[currentAppLocale() === 'en_US' ? 1 : 0] ?? key
}
