import { describe, expect, it } from 'vitest'
import { consoleToolNeedsPassword, parseSendString, validateConsoleButtonBar } from './consoleButtonBar'

describe('Send String parser', () => {
  it('decodes supported escapes and preserves exact CR/LF bytes', () => {
    expect(parseSendString(String.raw`a\r\n\t\b\e\\z`)).toEqual({
      segments: [{ kind: 'write', text: 'a\r\n\t\b\x1b\\z' }],
      writeCount: 1,
    })
  })

  it('flushes bytes at each one-second pause', () => {
    expect(parseSendString(String.raw`first\r\psecond\n\p`)).toEqual({
      segments: [
        { kind: 'write', text: 'first\r' },
        { kind: 'pause', milliseconds: 1000 },
        { kind: 'write', text: 'second\n' },
        { kind: 'pause', milliseconds: 1000 },
      ],
      writeCount: 2,
    })
  })

  it.each([String.raw`bad\q`, 'trailing\\'])('rejects unsupported or incomplete escapes in %j', value => {
    expect(() => parseSendString(value)).toThrow(/转义/)
  })

  it('bounds text before parsing', () => {
    expect(parseSendString('display\\sclock\\r\\p250done').segments).toEqual([
      { kind: 'write', text: 'display clock\r' },
      { kind: 'pause', milliseconds: 250 },
      { kind: 'write', text: 'done' },
    ])
    expect(() => parseSendString('\\p60001')).toThrow('60000')
    expect(() => parseSendString('x'.repeat(65_537))).toThrow('65536')
  })
})

describe('button-bar schema', () => {
  const document = {
    version: 2,
    groups: [{
      id: 'h3c',
      name: 'H3C',
      buttons: [{
        id: 'version',
        name: '版本',
        action: 'SEND_STRING',
        text: String.raw`display version\r`,
        color: '#409eff',
        tooltip: '查看版本',
        disable_tooltip: false,
        order: 0,
        enabled: true,
        launch_with_session_context: false,
      }],
    }],
  }

  it('accepts the persisted API schema and keeps its data', () => {
    expect(validateConsoleButtonBar(document)).toEqual(document)
  })

  it('migrates version 1 buttons without changing their action or text', () => {
    const legacy = structuredClone(document)
    legacy.version = 1
    const { launch_with_session_context: _launchWithSessionContext, ...legacyButton } = legacy.groups[0]!.buttons[0]!
    legacy.groups[0]!.buttons[0] = legacyButton as typeof legacy.groups[0]['buttons'][number]
    expect(validateConsoleButtonBar(legacy)).toMatchObject({
      version: 2,
      groups: [{ buttons: [{ action: 'SEND_STRING', text: String.raw`display version\r`, launch_with_session_context: false }] }],
    })
  })

  it('rejects unknown actions rather than implying their support', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'SHELL'
    expect(() => validateConsoleButtonBar(input)).toThrow('不支持的按钮动作')
  })

  it('accepts only registered Menu Function actions', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'MENU_FUNCTION'
    input.groups[0]!.buttons[0]!.text = 'clear-screen'
    expect(validateConsoleButtonBar(input)).toEqual(input)
    input.groups[0]!.buttons[0]!.text = 'run-arbitrary-code'
    expect(() => validateConsoleButtonBar(input)).toThrow('不支持的菜单功能')
  })

  it('accepts bounded Run Script JSON and rejects malformed scripts', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'RUN_SCRIPT'
    input.groups[0]!.buttons[0]!.text = JSON.stringify({ version: 1, steps: [{ type: 'SEND_STRING', text: String.raw`display version\r` }] })
    expect(validateConsoleButtonBar(input)).toEqual(input)
    input.groups[0]!.buttons[0]!.text = '{'
    expect(() => validateConsoleButtonBar(input)).toThrow('有效 JSON')
  })

  it('limits Launch Application buttons to registered External Tool ids', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'LAUNCH_APPLICATION'
    input.groups[0]!.buttons[0]!.text = '7c890030-3a3f-4d6b-b58e-7624d21daff9'
    expect(validateConsoleButtonBar(input)).toEqual(input)
    input.groups[0]!.buttons[0]!.text = 'C:\\arbitrary.exe'
    expect(() => validateConsoleButtonBar(input)).toThrow('已登记的外部程序')
  })

  it('rejects duplicate identifiers and schema versions', () => {
    const duplicate = structuredClone(document)
    duplicate.groups[0]!.buttons[0]!.id = 'h3c'
    expect(() => validateConsoleButtonBar(duplicate)).toThrow('无效或重复')
    expect(() => validateConsoleButtonBar({ ...document, version: 3 })).toThrow('版本必须为 1 或 2')
  })
})

describe('Launch Application password prompt', () => {
  it('prompts only when a registered argument template requests a password', () => {
    expect(consoleToolNeedsPassword(['-ssh', '{host}', '{username}', '{password}'])).toBe(true)
    expect(consoleToolNeedsPassword(['-ssh', '{host}', '{username}'])).toBe(false)
  })
})
