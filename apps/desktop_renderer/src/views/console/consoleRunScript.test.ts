import { describe, expect, it } from 'vitest'
import { parseConsoleRunScriptJson, validateConsoleRunScript } from './consoleRunScript'

describe('Console Run Script DSL', () => {
  it('validates bounded SEND_STRING and WAIT steps', () => {
    expect(validateConsoleRunScript({
      version: 1,
      steps: [
        { type: 'SEND_STRING', text: String.raw`display version\r\pdisplay clock\r` },
        { type: 'WAIT', milliseconds: 500 },
      ],
    })).toEqual({
      version: 1,
      steps: [
        { type: 'SEND_STRING', text: String.raw`display version\r\pdisplay clock\r`, segments: [
          { kind: 'write', text: 'display version\r' },
          { kind: 'pause', milliseconds: 1000 },
          { kind: 'write', text: 'display clock\r' },
        ] },
        { type: 'WAIT', milliseconds: 500 },
      ],
      totalWaitMilliseconds: 1500,
    })
  })

  it('parses JSON and delegates Send String escapes to the shared parser', () => {
    const script = parseConsoleRunScriptJson(JSON.stringify({
      version: 1,
      steps: [{ type: 'SEND_STRING', text: String.raw`display version\r` }],
    }))
    expect(script.steps[0]).toMatchObject({ type: 'SEND_STRING', segments: [{ kind: 'write', text: 'display version\r' }] })
    expect(() => parseConsoleRunScriptJson('{')).toThrow('valid JSON')
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'SEND_STRING', text: String.raw`bad\q` }] })).toThrow('unsupported escape')
  })

  it('rejects unknown actions, extra fields, and unsupported schema versions', () => {
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'JAVASCRIPT', source: 'alert(1)' }] })).toThrow('unsupported action')
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'WAIT', milliseconds: 10, callback: 'x' }] })).toThrow('only type and milliseconds')
    expect(() => validateConsoleRunScript({ version: 2, steps: [{ type: 'WAIT', milliseconds: 10 }] })).toThrow('version 1')
  })

  it('enforces step, per-wait, and cumulative wait bounds', () => {
    expect(() => validateConsoleRunScript({ version: 1, steps: Array.from({ length: 101 }, () => ({ type: 'WAIT', milliseconds: 1 })) })).toThrow('1 to 100')
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'WAIT', milliseconds: 60_001 }] })).toThrow('from 1 to 60000')
    expect(() => validateConsoleRunScript({ version: 1, steps: Array.from({ length: 11 }, () => ({ type: 'WAIT', milliseconds: 60_000 })) })).toThrow('total wait')
    expect(() => validateConsoleRunScript({ version: 1, steps: [] })).toThrow('1 to 100')
  })
})
