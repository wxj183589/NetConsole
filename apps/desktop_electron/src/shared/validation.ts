import type {
  ChooseSavePathOptions,
  FileFilter,
  RendererReadyReport,
  SelectFileOptions,
} from './bridge'

const MAX_FILTERS = 20
const MAX_EXTENSIONS = 32
const FILTER_NAME_MAX = 80
const EXTENSION_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/
const INVALID_FILE_NAME_RE = /[\u0000-\u001f<>:"/\\|?*]/

export function validateSelectFileOptions(value: unknown): SelectFileOptions {
  if (value === undefined) return {}
  const record = asRecord(value, 'file selection options')
  rejectUnknownKeys(record, ['filters', 'multiple'])
  if (record.multiple !== undefined && typeof record.multiple !== 'boolean') {
    throw new TypeError('multiple must be a boolean')
  }
  return {
    ...(record.filters === undefined ? {} : { filters: validateFilters(record.filters) }),
    ...(record.multiple === undefined ? {} : { multiple: record.multiple }),
  }
}

export function validateChooseSavePathOptions(value: unknown): ChooseSavePathOptions {
  const record = asRecord(value, 'save path options')
  rejectUnknownKeys(record, ['suggestedName', 'filters'])
  if (typeof record.suggestedName !== 'string') {
    throw new TypeError('suggestedName must be a string')
  }
  const suggestedName = record.suggestedName.trim()
  if (
    !suggestedName
    || suggestedName.length > 180
    || suggestedName === '.'
    || suggestedName === '..'
    || INVALID_FILE_NAME_RE.test(suggestedName)
  ) {
    throw new TypeError('suggestedName must be a safe file name')
  }
  return {
    suggestedName,
    ...(record.filters === undefined ? {} : { filters: validateFilters(record.filters) }),
  }
}

export function validateBridgePath(value: unknown): string {
  if (typeof value !== 'string') throw new TypeError('path must be a string')
  const candidate = value.trim()
  if (!candidate || candidate.length > 32_767 || /[\u0000-\u001f]/.test(candidate)) {
    throw new TypeError('path is invalid')
  }
  return candidate
}

export function validateRendererReadyReport(value: unknown): RendererReadyReport {
  const record = asRecord(value, 'renderer ready report')
  rejectUnknownKeys(record, ['healthOk'])
  if (typeof record.healthOk !== 'boolean') throw new TypeError('healthOk must be a boolean')
  return { healthOk: record.healthOk }
}

function validateFilters(value: unknown): FileFilter[] {
  if (!Array.isArray(value) || value.length > MAX_FILTERS) {
    throw new TypeError(`filters must contain at most ${MAX_FILTERS} entries`)
  }
  return value.map((item) => {
    const record = asRecord(item, 'file filter')
    rejectUnknownKeys(record, ['name', 'extensions'])
    if (
      typeof record.name !== 'string'
      || !record.name.trim()
      || record.name.trim().length > FILTER_NAME_MAX
    ) {
      throw new TypeError('filter name is invalid')
    }
    if (
      !Array.isArray(record.extensions)
      || record.extensions.length === 0
      || record.extensions.length > MAX_EXTENSIONS
      || record.extensions.some((extension) => typeof extension !== 'string' || !EXTENSION_RE.test(extension))
    ) {
      throw new TypeError('filter extensions are invalid')
    }
    return {
      name: record.name.trim(),
      extensions: [...record.extensions] as string[],
    }
  })
}

function asRecord(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`)
  }
  return value as Record<string, unknown>
}

function rejectUnknownKeys(record: Record<string, unknown>, allowed: string[]): void {
  const unknown = Object.keys(record).filter((key) => !allowed.includes(key))
  if (unknown.length) throw new TypeError(`unsupported field: ${unknown[0]}`)
}
