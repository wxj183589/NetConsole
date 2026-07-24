const CONTROL_CHARACTER_RE = /[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/
const LOCAL_PATH_RE = /^(?:[A-Za-z]:[\\/]|\\\\|file:)/i
const PATH_TRAVERSAL_RE = /(?:^|[\\/])\.\.?($|[\\/])/

export function normalizeOpaqueIdentifier(value: unknown, maxLength = 512): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  if (
    !normalized
    || normalized.length > maxLength
    || CONTROL_CHARACTER_RE.test(normalized)
    || LOCAL_PATH_RE.test(normalized)
    || PATH_TRAVERSAL_RE.test(normalized)
  ) {
    return null
  }
  return normalized
}

export function normalizeMeshSessionIdentifier(value: unknown): string | null {
  return normalizeOpaqueIdentifier(value, 512)
}

export function meshSessionPathSegment(value: unknown): string {
  const normalized = normalizeMeshSessionIdentifier(value)
  if (!normalized) throw new TypeError('分析会话标识无效')
  return encodeURIComponent(normalized)
}
