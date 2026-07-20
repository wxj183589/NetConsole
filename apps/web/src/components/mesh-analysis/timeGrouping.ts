/** Builds deterministic alternating classes for equal-sample-time rows. */
export function buildMeshTimeGroupClasses<Row extends object>(
  rows: readonly Row[],
  getTime: (value: Row) => unknown,
): ReadonlyMap<Row, string> {
  const groups = new Map<string, number>()
  const result = new Map<Row, string>()
  const keyFor = (value: Row): string => {
    const time = getTime(value)
    return time == null || time === '' ? '__missing__' : String(time)
  }
  for (const item of rows) {
    const itemKey = keyFor(item)
    if (!groups.has(itemKey)) groups.set(itemKey, groups.size)
    result.set(item, `mesh-time-group-${(groups.get(itemKey) ?? 0) % 2}`)
  }
  return result
}
