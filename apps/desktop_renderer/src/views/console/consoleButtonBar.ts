import { parseConsoleRunScriptJson } from './consoleRunScript'

export type SendStringSegment =
  | { kind: 'write'; text: string }
  | { kind: 'pause'; milliseconds: 1000 }

export type SendStringParseResult = {
  segments: SendStringSegment[]
  writeCount: number
}

export type ConsoleMappedButton = {
  id: string
  name: string
  action: 'SEND_STRING' | 'MENU_FUNCTION' | 'LAUNCH_APPLICATION' | 'RUN_SCRIPT'
  text: string
  color: string
  tooltip: string
  disable_tooltip: boolean
  order: number
  enabled: boolean
}

export type ConsoleButtonGroup = {
  id: string
  name: string
  buttons: ConsoleMappedButton[]
}

/** Matches the persisted Backend quick-button document contract. */
export type ConsoleButtonBarDocument = {
  version: 1
  groups: ConsoleButtonGroup[]
}

const MAX_BUTTONS_PER_GROUP = 200
const MAX_GROUPS = 32
const MAX_TEXT_LENGTH = 65_536
const BUTTON_ID = /^[\w-]{1,80}$/
const HEX_COLOR = /^#[0-9a-f]{6}$/i
export const MENU_FUNCTIONS = [
  'find',
  'select-all',
  'clear-scrollback',
  'clear-screen',
  'clear-all',
] as const

const sendStringEscapes: Record<string, string> = {
  r: '\r',
  n: '\n',
  t: '\t',
  b: '\b',
  e: '\x1b',
  '\\': '\\',
}

/**
 * Parses SecureCRT-style Send String escapes without changing the configured
 * text. A pause flushes preceding bytes and waits for one second before the
 * following segment. The Backend dispatcher remains responsible for sending.
 */
export function parseSendString(value: string): SendStringParseResult {
  if (value.length > MAX_TEXT_LENGTH) {
    throw new Error('Send String exceeds 65536 characters')
  }

  const segments: SendStringSegment[] = []
  let pending = ''
  let writeCount = 0

  const flush = () => {
    if (!pending) return
    segments.push({ kind: 'write', text: pending })
    pending = ''
    writeCount += 1
  }

  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]!
    if (character !== '\\') {
      pending += character
      continue
    }

    const escape = value[index + 1]
    if (escape === undefined) {
      throw new Error(`Send String ends with an incomplete escape at position ${index}`)
    }
    if (escape === 'p') {
      flush()
      segments.push({ kind: 'pause', milliseconds: 1000 })
      index += 1
      continue
    }

    const decoded = sendStringEscapes[escape]
    if (decoded === undefined) {
      throw new Error(`Send String contains unsupported escape \\${escape} at position ${index}`)
    }
    pending += decoded
    index += 1
  }

  flush()
  return { segments, writeCount }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function assertId(value: unknown, ids: Set<string>, label: string): asserts value is string {
  if (typeof value !== 'string' || !BUTTON_ID.test(value) || ids.has(value)) {
    throw new Error(`${label} must be unique and match ${BUTTON_ID.source}`)
  }
  ids.add(value)
}

/** Validates imported or API-provided data without silently repairing it. */
export function validateConsoleButtonBar(value: unknown): ConsoleButtonBarDocument {
  if (!isRecord(value) || value.version !== 1 || Object.keys(value).length !== 2) {
    throw new Error('Button bar document must use schema version 1')
  }
  if (!Array.isArray(value.groups) || value.groups.length < 1 || value.groups.length > MAX_GROUPS) {
    throw new Error(`Button bar must contain 1 to ${MAX_GROUPS} groups`)
  }

  const ids = new Set<string>()
  const groups = value.groups.map((rawGroup, groupIndex): ConsoleButtonGroup => {
    if (!isRecord(rawGroup) || Object.keys(rawGroup).length !== 3 || !Array.isArray(rawGroup.buttons)) {
      throw new Error(`Group ${groupIndex + 1} has an invalid structure`)
    }
    if (rawGroup.buttons.length > MAX_BUTTONS_PER_GROUP) {
      throw new Error(`Group ${groupIndex + 1} exceeds ${MAX_BUTTONS_PER_GROUP} buttons`)
    }

    assertId(rawGroup.id, ids, `Group ${groupIndex + 1} id`)
    if (typeof rawGroup.name !== 'string' || rawGroup.name.length < 1 || rawGroup.name.length > 80) {
      throw new Error(`Group ${groupIndex + 1} name must contain 1 to 80 characters`)
    }

    const buttons = rawGroup.buttons.map((rawButton, buttonIndex): ConsoleMappedButton => {
      const label = `Group ${groupIndex + 1}, button ${buttonIndex + 1}`
      const fields = ['id', 'name', 'action', 'text', 'color', 'tooltip', 'disable_tooltip', 'order', 'enabled']
      if (!isRecord(rawButton) || Object.keys(rawButton).length !== fields.length || fields.some(field => !(field in rawButton))) {
        throw new Error(`${label} has an invalid structure`)
      }
      assertId(rawButton.id, ids, `${label} id`)
      if (typeof rawButton.name !== 'string' || rawButton.name.length < 1 || rawButton.name.length > 80) {
        throw new Error(`${label} name must contain 1 to 80 characters`)
      }
      if (typeof rawButton.text !== 'string' || rawButton.text.length > MAX_TEXT_LENGTH) {
        throw new Error(`${label} text exceeds ${MAX_TEXT_LENGTH} characters`)
      }
      if (rawButton.action === 'SEND_STRING') parseSendString(rawButton.text)
      else if (rawButton.action === 'MENU_FUNCTION') {
        if (!(MENU_FUNCTIONS as readonly string[]).includes(rawButton.text)) {
          throw new Error(`${label} uses an unsupported menu function`)
        }
      } else if (rawButton.action === 'LAUNCH_APPLICATION') {
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(rawButton.text)) {
          throw new Error(`${label} must reference a registered External Tool id`)
        }
      } else if (rawButton.action === 'RUN_SCRIPT') {
        parseConsoleRunScriptJson(rawButton.text)
      } else throw new Error(`${label} uses an unsupported action`)
      if (typeof rawButton.color !== 'string' || !HEX_COLOR.test(rawButton.color)) {
        throw new Error(`${label} color must be a six-digit hexadecimal color`)
      }
      if (typeof rawButton.tooltip !== 'string' || rawButton.tooltip.length > 500) {
        throw new Error(`${label} tooltip exceeds 500 characters`)
      }
      if (typeof rawButton.disable_tooltip !== 'boolean' || typeof rawButton.enabled !== 'boolean') {
        throw new Error(`${label} enabled and disable_tooltip must be booleans`)
      }
      if (!Number.isInteger(rawButton.order) || Number(rawButton.order) < 0 || Number(rawButton.order) > 10_000) {
        throw new Error(`${label} order must be an integer from 0 to 10000`)
      }
      return rawButton as ConsoleMappedButton
    })

    return { id: rawGroup.id, name: rawGroup.name, buttons }
  })

  return { version: 1, groups }
}
