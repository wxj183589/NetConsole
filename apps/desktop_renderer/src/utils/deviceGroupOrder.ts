const GROUP_SEPARATOR_RE = /[\s\-_\u2010-\u2015]+/g

const BUSINESS_GROUP_RANK: Record<string, number> = {
  cocc: 0,
  bocc: 1,
  '车站': 2,
  '车载mr': 3,
  '车载sw': 4,
  '车载3sw': 4,
  '车载交换机': 4,
}

export function canonicalDeviceGroupName(value: string): string {
  const text = String(value || '').trim()
  const compact = text.replace(GROUP_SEPARATOR_RE, '').toLocaleLowerCase()
  if (compact === 'cocc') return 'COCC'
  if (compact === 'bocc') return 'BOCC'
  if (text === '车站') return '车站'
  if (compact === '车载mr') return '车载-MR'
  if (['车载sw', '车载3sw', '车载交换机'].includes(compact)) return '车载-SW'
  return text
}

export function compareDeviceGroupNames(left: string, right: string): number {
  const leftText = String(left || '').trim()
  const rightText = String(right || '').trim()
  const leftCompact = leftText.replace(GROUP_SEPARATOR_RE, '').toLocaleLowerCase()
  const rightCompact = rightText.replace(GROUP_SEPARATOR_RE, '').toLocaleLowerCase()
  const leftRank = BUSINESS_GROUP_RANK[leftCompact] ?? 5
  const rightRank = BUSINESS_GROUP_RANK[rightCompact] ?? 5
  if (leftRank !== rightRank) return leftRank - rightRank
  return leftText.localeCompare(rightText, 'zh-CN', { numeric: true, sensitivity: 'base' })
}

export function sortDeviceGroupNames(values: readonly string[]): string[] {
  return [...values].sort(compareDeviceGroupNames)
}
