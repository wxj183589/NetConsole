import { describe, expect, it } from 'vitest'

import source from './CarNetworkDiagnosticView.vue?raw'

describe('car network diagnostic view', () => {
  it('redirects legacy entry to the formal train communication page', () => {
    expect(source).toContain("router.replace('/rail-transit/train-communication')")
    expect(source).toContain('onMounted')
    expect(source).not.toContain('startCarNetworkDiagnostic')
    expect(source).not.toContain('getCarNetworkDiagnosticTask')
    expect(source).not.toContain('recoverCarNetworkDiagnostics')
    expect(source).not.toContain('CarNetworkPointTableDialog')
    expect(source).not.toContain('table-id="car-network-diagnostic-trains"')
    expect(source).not.toContain('table-id="car-network-diagnostic-result"')
  })
})
