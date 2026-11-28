import { describe, expect, it } from 'vitest'
import { describeTerminalPaste, extractTerminalUrl, isMultilinePaste, quotePastedLines } from './terminalContextActions'

describe('terminal context action helpers', () => {
  it('extracts HTTP links and trims terminal punctuation', () => {
    expect(extractTerminalUrl('See https://example.test/path?q=1, for details')).toBe('https://example.test/path?q=1')
    expect(extractTerminalUrl('ssh://example.test')).toBe('')
  })

  it('quotes every pasted line and escapes embedded single quotes', () => {
    expect(quotePastedLines("display version\r\nsay 'hello'")).toBe("'display version'\r'say ''hello'''")
    expect(quotePastedLines('single line')).toBe("'single line'")
  })

  it('detects multiline clipboard content', () => {
    expect(isMultilinePaste('one\ntwo')).toBe(true)
    expect(isMultilinePaste('one')).toBe(false)
  })

  it('checks lines beyond the preview for empty lines and configuration commands', () => {
    const text = 'x'.repeat(2500) + '\r\n \nreboot\rdisplay clock'
    expect(describeTerminalPaste(text)).toEqual({
      lineCount: 4, hasEmptyLine: true, hasConfigCommand: true, preview: 'x'.repeat(2048) + '…',
    })
  })
})
