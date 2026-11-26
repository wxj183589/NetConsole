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
