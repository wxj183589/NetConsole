import { describe, expect, it } from 'vitest'
import { parseSendString, validateConsoleButtonBar } from './consoleButtonBar'

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
    expect(() => parseSendString(value)).toThrow(/escape/)
  })

  it('bounds text before parsing', () => {
    expect(() => parseSendString('x'.repeat(65_537))).toThrow('65536')
  })
})

describe('button-bar schema', () => {
  const document = {
    version: 1,
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
      }],
    }],
  }

  it('accepts the persisted API schema and keeps its data', () => {
    expect(validateConsoleButtonBar(document)).toEqual(document)
  })

  it('rejects unknown actions rather than implying their support', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'SHELL'
    expect(() => validateConsoleButtonBar(input)).toThrow('unsupported action')
  })

  it('accepts only registered Menu Function actions', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'MENU_FUNCTION'
    input.groups[0]!.buttons[0]!.text = 'clear-screen'
    expect(validateConsoleButtonBar(input)).toEqual(input)
    input.groups[0]!.buttons[0]!.text = 'run-arbitrary-code'
    expect(() => validateConsoleButtonBar(input)).toThrow('unsupported menu function')
  })

  it('accepts bounded Run Script JSON and rejects malformed scripts', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'RUN_SCRIPT'
    input.groups[0]!.buttons[0]!.text = JSON.stringify({ version: 1, steps: [{ type: 'SEND_STRING', text: String.raw`display version\r` }] })
    expect(validateConsoleButtonBar(input)).toEqual(input)
    input.groups[0]!.buttons[0]!.text = '{'
    expect(() => validateConsoleButtonBar(input)).toThrow('valid JSON')
  })

  it('limits Launch Application buttons to registered External Tool ids', () => {
    const input = structuredClone(document)
    input.groups[0]!.buttons[0]!.action = 'LAUNCH_APPLICATION'
    input.groups[0]!.buttons[0]!.text = '7c890030-3a3f-4d6b-b58e-7624d21daff9'
    expect(validateConsoleButtonBar(input)).toEqual(input)
    input.groups[0]!.buttons[0]!.text = 'C:\\arbitrary.exe'
    expect(() => validateConsoleButtonBar(input)).toThrow('registered External Tool')
  })

  it('rejects duplicate identifiers and schema versions', () => {
    const duplicate = structuredClone(document)
    duplicate.groups[0]!.buttons[0]!.id = 'h3c'
    expect(() => validateConsoleButtonBar(duplicate)).toThrow('unique')
    expect(() => validateConsoleButtonBar({ ...document, version: 2 })).toThrow('version 1')
  })
})
