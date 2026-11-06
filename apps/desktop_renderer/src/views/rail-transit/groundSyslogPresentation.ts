/** Hide presentation-only fields without mutating parsed/raw source objects. */
export function syslogVisibleDetails(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(syslogVisibleDetails)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).filter(([key]) =>
      !key.toLowerCase().includes('peer_mac') && !['mr_role', 'endpoint'].includes(key.toLowerCase()),
    ).map(([key, item]) => [key, syslogVisibleDetails(item)]))
  }
  return value
}
