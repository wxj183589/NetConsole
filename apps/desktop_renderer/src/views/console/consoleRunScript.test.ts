import { describe, expect, it } from 'vitest'
import { parseConsoleRunScriptJson, resolveConsoleScriptSteps, validateConsoleRunScript } from './consoleRunScript'

describe('Console Run Script DSL', () => {
  it('previews literal session variables and includes only matching command steps', () => {
    const script = validateConsoleRunScript({ version: 1, steps: [
      { type: 'SEND_STRING', text: String.raw`ping {{address}}\r`, when_protocol: 'SSH' },
      { type: 'SEND_STRING', text: String.raw`display clock\r`, when_protocol: 'SERIAL' },
    ] })
    const steps = resolveConsoleScriptSteps(script, { protocol: 'SSH', address: '192.0.2.1', port: '22' })
    expect(steps).toEqual([{
      type: 'SEND_STRING', text: String.raw`ping 192.0.2.1\r`, when_protocol: 'SSH',
      segments: [{ kind: 'write', text: 'ping 192.0.2.1\r' }],
    }])
    expect(() => resolveConsoleScriptSteps(script, { protocol: 'SSH', address: '192.0.2.1\r', port: '22' })).toThrow('不支持的字符')
  })
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
    expect(() => parseConsoleRunScriptJson('{')).toThrow('有效 JSON')
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'SEND_STRING', text: String.raw`bad\q` }] })).toThrow('不支持的转义符')
  })

  it('rejects unknown actions, extra fields, and unsupported schema versions', () => {
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'JAVASCRIPT', source: 'alert(1)' }] })).toThrow('不支持的动作')
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'WAIT', milliseconds: 10, callback: 'x' }] })).toThrow('只能包含动作类型')
    expect(() => validateConsoleRunScript({ version: 2, steps: [{ type: 'WAIT', milliseconds: 10 }] })).toThrow('版本 1')
  })

  it('enforces step, per-wait, and cumulative wait bounds', () => {
    expect(() => validateConsoleRunScript({ version: 1, steps: Array.from({ length: 101 }, () => ({ type: 'WAIT', milliseconds: 1 })) })).toThrow('1 至 100')
    expect(() => validateConsoleRunScript({ version: 1, steps: [{ type: 'WAIT', milliseconds: 60_001 }] })).toThrow('1 至 60000')
    expect(() => validateConsoleRunScript({ version: 1, steps: Array.from({ length: 11 }, () => ({ type: 'WAIT', milliseconds: 60_000 })) })).toThrow('累计等待时间')
    expect(() => validateConsoleRunScript({ version: 1, steps: [] })).toThrow('1 至 100')
  })
})
