import { describe, expect, it } from 'vitest'

import {
  BUSINESS_TIME_ZONE,
  formatBusinessDateTime,
  formatTaskDateTime,
  parseUtcDateTime,
  taskDateTimeTitle,
} from './dateTime'

describe('business date time formatting', () => {
  it('uses the configured business timezone for UTC values', () => {
    expect(formatTaskDateTime('2026-08-06T15:31:15.538Z')).toBe('2026-08-06 23:31:15')
    expect(BUSINESS_TIME_ZONE).toBe('Asia/Shanghai')
  })

  it('does not apply a second offset to values that already contain one', () => {
    expect(formatBusinessDateTime('2026-08-06T23:31:15+08:00')).toBe('2026-08-06 23:31:15')
  })

  it('handles day and year boundaries', () => {
    expect(formatBusinessDateTime('2026-08-06T18:30:00Z')).toBe('2026-08-07 02:30:00')
    expect(formatBusinessDateTime('2026-12-31T18:30:00Z')).toBe('2027-01-01 02:30:00')
  })

  it('accepts Date and Python-style ISO values without showing milliseconds', () => {
    expect(formatBusinessDateTime(new Date('2026-08-06T15:31:15.538Z'))).toBe('2026-08-06 23:31:15')
    expect(formatBusinessDateTime('2026-08-06 15:31:15.538+00:00')).toBe('2026-08-06 23:31:15')
  })

  it('treats historical task values without a timezone as UTC', () => {
    expect(parseUtcDateTime('2026-08-06T15:31:15')).toEqual(new Date('2026-08-06T15:31:15Z'))
    expect(formatBusinessDateTime('2026-08-06T15:31:15')).toBe('2026-08-06 23:31:15')
  })

  it('returns a stable empty placeholder for missing or invalid values', () => {
    expect(formatBusinessDateTime(null)).toBe('--')
    expect(formatBusinessDateTime(undefined)).toBe('--')
    expect(formatBusinessDateTime('')).toBe('--')
    expect(formatBusinessDateTime('not-a-date')).toBe('--')
    expect(formatBusinessDateTime(new Date('invalid'))).toBe('--')
  })

  it('can expose the original UTC value only as diagnostic title text', () => {
    expect(taskDateTimeTitle('2026-08-06T15:31:15.538Z')).toBe('UTC 2026-08-06T15:31:15.538Z')
    expect(taskDateTimeTitle('2026-08-06T23:31:15+08:00')).toBe('原始时间 2026-08-06T23:31:15+08:00')
    expect(taskDateTimeTitle('')).toBeUndefined()
    expect(taskDateTimeTitle('not-a-date')).toBeUndefined()
  })
})
