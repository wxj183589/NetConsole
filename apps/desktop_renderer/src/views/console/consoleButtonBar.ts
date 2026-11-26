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
  launch_with_session_context: boolean
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
  version: 2
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
    throw new Error('发送字符串不能超过 65536 个字符')
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
      throw new Error(`发送字符串在第 ${index} 位包含未完成的转义符`)
    }
    if (escape === 'p') {
      flush()
      segments.push({ kind: 'pause', milliseconds: 1000 })
      index += 1
      continue
    }

    const decoded = sendStringEscapes[escape]
    if (decoded === undefined) {
      throw new Error(`发送字符串在第 ${index} 位包含不支持的转义符 \\${escape}`)
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
    throw new Error(`${label} 标识无效或重复`)
  }
  ids.add(value)
}

/** Validates imported or API-provided data without silently repairing it. */
export function validateConsoleButtonBar(value: unknown): ConsoleButtonBarDocument {
  if (!isRecord(value) || ![1, 2].includes(Number(value.version)) || Object.keys(value).length !== 2) {
    throw new Error('按钮栏配置版本必须为 1 或 2')
  }
  const sourceVersion = Number(value.version)
  if (!Array.isArray(value.groups) || value.groups.length < 1 || value.groups.length > MAX_GROUPS) {
    throw new Error(`按钮栏必须包含 1 至 ${MAX_GROUPS} 个分组`)
  }

  const ids = new Set<string>()
  const groups = value.groups.map((rawGroup, groupIndex): ConsoleButtonGroup => {
    if (!isRecord(rawGroup) || Object.keys(rawGroup).length !== 3 || !Array.isArray(rawGroup.buttons)) {
      throw new Error(`第 ${groupIndex + 1} 个分组结构无效`)
    }
    if (rawGroup.buttons.length > MAX_BUTTONS_PER_GROUP) {
      throw new Error(`第 ${groupIndex + 1} 个分组的按钮不能超过 ${MAX_BUTTONS_PER_GROUP} 个`)
    }

    assertId(rawGroup.id, ids, `Group ${groupIndex + 1} id`)
    if (typeof rawGroup.name !== 'string' || rawGroup.name.length < 1 || rawGroup.name.length > 80) {
      throw new Error(`第 ${groupIndex + 1} 个分组名称须为 1 至 80 个字符`)
    }

    const buttons = rawGroup.buttons.map((rawButton, buttonIndex): ConsoleMappedButton => {
      const label = `第 ${groupIndex + 1} 个分组的第 ${buttonIndex + 1} 个按钮`
      const fields = ['id', 'name', 'action', 'text', 'color', 'tooltip', 'disable_tooltip', 'order', 'enabled']
      const expectedFields = sourceVersion === 1 ? fields : [...fields, 'launch_with_session_context']
      if (!isRecord(rawButton) || Object.keys(rawButton).length !== expectedFields.length || expectedFields.some(field => !(field in rawButton))) {
        throw new Error(`${label}结构无效`)
      }
      assertId(rawButton.id, ids, `${label} id`)
      if (typeof rawButton.name !== 'string' || rawButton.name.length < 1 || rawButton.name.length > 80) {
        throw new Error(`${label}名称须为 1 至 80 个字符`)
      }
      if (typeof rawButton.text !== 'string' || rawButton.text.length > MAX_TEXT_LENGTH) {
        throw new Error(`${label}文本不能超过 ${MAX_TEXT_LENGTH} 个字符`)
      }
      const launchWithSessionContext = sourceVersion === 1
        ? rawButton.action === 'LAUNCH_APPLICATION'
        : rawButton.launch_with_session_context
      if (typeof launchWithSessionContext !== 'boolean') {
        throw new Error(`${label}的会话参数开关无效`)
      }
      if (rawButton.action === 'SEND_STRING') parseSendString(rawButton.text)
      else if (rawButton.action === 'MENU_FUNCTION') {
        if (!(MENU_FUNCTIONS as readonly string[]).includes(rawButton.text)) {
          throw new Error(`${label}使用了不支持的菜单功能`)
        }
      } else if (rawButton.action === 'LAUNCH_APPLICATION') {
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(rawButton.text)) {
          throw new Error(`${label}必须引用已登记的外部程序标识`)
        }
      } else if (rawButton.action === 'RUN_SCRIPT') {
        parseConsoleRunScriptJson(rawButton.text)
      } else throw new Error(`${label}使用了不支持的按钮动作`)
      if (typeof rawButton.color !== 'string' || !HEX_COLOR.test(rawButton.color)) {
        throw new Error(`${label}颜色须为六位十六进制值`)
      }
      if (typeof rawButton.tooltip !== 'string' || rawButton.tooltip.length > 500) {
        throw new Error(`${label}提示文本不能超过 500 个字符`)
      }
      if (typeof rawButton.disable_tooltip !== 'boolean' || typeof rawButton.enabled !== 'boolean') {
        throw new Error(`${label}的启用及提示开关无效`)
      }
      if (!Number.isInteger(rawButton.order) || Number(rawButton.order) < 0 || Number(rawButton.order) > 10_000) {
        throw new Error(`${label}顺序须为 0 至 10000 的整数`)
      }
      return { ...rawButton, launch_with_session_context: launchWithSessionContext } as ConsoleMappedButton
    })

    return { id: rawGroup.id, name: rawGroup.name, buttons }
  })

  return { version: 2, groups }
}

export function consoleToolNeedsPassword(arguments_: string[]): boolean {
  return arguments_.some(argument => argument.includes('{password}'))
}
