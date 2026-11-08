import { describe, expect, it } from 'vitest'
import { syslogVisibleDetails } from './groundSyslogPresentation'

describe('Syslog visible parsed details', () => {
  it('hides endpoint and Peer MAC fields recursively while preserving source and raw text', () => {
    const source = { mr_role: 'CT', peer_mac: 'abcd', details: [{ previous_peer_mac: 'ef01', endpoint: 'CW', peer_name: 'AP-1' }], raw_text: 'peer_mac abcd CT' }
    const before = JSON.stringify(source)
    expect(syslogVisibleDetails(source)).toEqual({ details: [{ peer_name: 'AP-1' }], raw_text: 'peer_mac abcd CT' })
    expect(JSON.stringify(source)).toBe(before)
  })
})
