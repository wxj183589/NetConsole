function finiteNumber(value: number | null | undefined): number | null {
  return value === null || value === undefined || !Number.isFinite(value) ? null : value
}

function trimNumber(value: number, digits = 2): string {
  return (Number.isInteger(value) ? String(value) : value.toFixed(digits))
    .replace(/\.0+$/, '')
    .replace(/(\.\d*?)0+$/, '$1')
}

/** 原始设备 RSSI 是无单位的信号值，不把它猜测成 dBm。 */
export function formatRssiValue(value: number | null | undefined): string {
  const normalized = finiteNumber(value)
  return normalized === null ? '无数据' : trimNumber(normalized, 0)
}

/** 只有 DTO/字段明确表达物理功率时才使用 dBm。 */
export function formatDbmValue(value: number | null | undefined): string {
  const normalized = finiteNumber(value)
  return normalized === null ? '无数据' : `${trimNumber(normalized, 0)} dBm`
}
