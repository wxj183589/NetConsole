export interface SubnetStatusHost {
  ip: string
  host_number: number
  in_range: boolean
  status: 'disabled' | 'idle' | 'online' | 'offline' | 'timeout' | 'error'
  detail: Record<string, unknown>
}

export function buildSubnetStatusGrid(cidr: string, usableOnly: boolean, rows: Record<string, unknown>[]): SubnetStatusHost[] {
  const [address, prefixText = '32'] = cidr.trim().split('/')
  const addressValue = ipv4Value(address)
  const prefix = Number(prefixText)
  if (addressValue === null || !Number.isInteger(prefix) || prefix < 24 || prefix > 32) return []
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0
  const network = (addressValue & mask) >>> 0
  const broadcast = (network | (~mask >>> 0)) >>> 0
  const visualBase = network & 0xffffff00
  const resultByIp = new Map(rows.map((row) => [String(row.target || row.resolved_ip || ''), row]))
  return Array.from({ length: 255 }, (_, index) => {
    const value = (visualBase + index + 1) >>> 0
    const ip = ipv4Text(value)
    const inRange = value >= network && value <= broadcast && (!usableOnly || prefix >= 31 || (value !== network && value !== broadcast))
    const detail = resultByIp.get(ip) || { target: ip, status: inRange ? 'idle' : 'disabled' }
    return { ip, host_number: index + 1, in_range: inRange, status: inRange ? resultStatus(detail.status) : 'disabled', detail }
  })
}

function resultStatus(value: unknown): SubnetStatusHost['status'] {
  const status = String(value || '')
  if (status === 'online') return 'online'
  if (status === 'timeout') return 'timeout'
  if (status === 'offline') return 'offline'
  if (['failed', 'unreachable', 'dns_failed', 'error'].includes(status)) return 'error'
  return 'idle'
}

function ipv4Value(value: string): number | null {
  const parts = value.split('.').map(Number)
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return null
  return (((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0)
}

function ipv4Text(value: number): string {
  return [value >>> 24, (value >>> 16) & 255, (value >>> 8) & 255, value & 255].join('.')
}
