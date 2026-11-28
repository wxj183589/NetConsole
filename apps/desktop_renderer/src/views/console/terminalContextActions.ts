const URL_PATTERN = /\bhttps?:\/\/[^\s<>"']+/i

export function extractTerminalUrl(text: string): string {
  const match = text.match(URL_PATTERN)
  return match?.[0]?.replace(/[),.;!?]+$/, '') || ''
}

export function quotePastedLines(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => `'${line.replace(/'/g, "''")}'`)
    .join('\r')
}

export function isMultilinePaste(text: string): boolean {
  return /[\r\n]/.test(text)
}

export function describeTerminalPaste(text: string) {
  const lines = text.split(/\r\n?|\n/)
  return {
    lineCount: lines.length,
    hasEmptyLine: lines.some(line => !line.trim()),
    hasConfigCommand: lines.some(line => /^\s*(?:system-view|configure\s+terminal|undo|delete|reset|reboot|format|shutdown|erase|reload)\b/i.test(line)),
    preview: text.length > 2048 ? text.slice(0, 2048) + '…' : text,
  }
}
