export const BUSINESS_TIME_ZONE = 'Asia/Shanghai'

type DateTimeInput = Date | string | null | undefined

/**
 * 任务中心时间统一按 UTC 持久化。历史无偏移字符串沿用后端的 UTC 解析契约，
 * 必须显式附加 UTC，不能让浏览器按本机时区猜测。
 */
export function parseUtcDateTime(value: DateTimeInput): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : new Date(value.getTime())
  }
  if (typeof value !== 'string') return null
  const text = value.trim()
  if (!text) return null

  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)
  const normalized = hasOffset
    ? text
    : `${text.replace(' ', 'T')}Z`
  const timestamp = Date.parse(normalized)
  return Number.isNaN(timestamp) ? null : new Date(timestamp)
}

export function formatBusinessDateTime(
  value: DateTimeInput,
  timeZone = BUSINESS_TIME_ZONE,
): string {
  const date = parseUtcDateTime(value)
  if (!date) return '--'
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      calendar: 'gregory',
      numberingSystem: 'latn',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(date)
    const values = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]))
    return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second}`
  } catch {
    return '--'
  }
}

export function formatTaskDateTime(value: DateTimeInput): string {
  return formatBusinessDateTime(value)
}

export function taskDateTimeTitle(value: DateTimeInput): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined
  const parsed = parseUtcDateTime(value)
  if (!parsed) return undefined
  const text = value.trim()
  return /Z$/i.test(text) || !/(?:[+-]\d{2}:?\d{2})$/i.test(text)
    ? `UTC ${text}`
    : `原始时间 ${text}`
}
