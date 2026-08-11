import { describe, expect, it } from 'vitest'

import { displayInterfaceName } from './interfaceName'

describe('displayInterfaceName', () => {
  it.each([
    ['GigabitEthernet2/0/1', 'GE2/0/1'],
    ['GigabitEthernet 2/0/1', 'GE2/0/1'],
    ['Ten-GigabitEthernet1/0/1', 'XGE1/0/1'],
    ['XGigabitEthernet1/0/2', 'XGE1/0/2'],
    ['Twenty-FiveGigE1/0/3', '25GE1/0/3'],
    ['FortyGigE1/0/4', '40GE1/0/4'],
    ['HundredGigE1/0/5', '100GE1/0/5'],
  ])('shortens %s without changing the port path', (value, expected) => {
    expect(displayInterfaceName(value)).toBe(expected)
  })

  it('preserves unknown interface names and missing values', () => {
    expect(displayInterfaceName('Bridge-Aggregation1')).toBe('Bridge-Aggregation1')
    expect(displayInterfaceName(null)).toBe('')
  })
})
