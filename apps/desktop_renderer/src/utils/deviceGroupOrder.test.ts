import { describe, expect, it } from 'vitest'

import { canonicalDeviceGroupName, sortDeviceGroupNames } from './deviceGroupOrder'

describe('device group business order', () => {
  it('keeps aliases as display values but sorts by the fixed business priority', () => {
    expect(canonicalDeviceGroupName(' Cocc ')).toBe('COCC')
    expect(canonicalDeviceGroupName('车载 MR')).toBe('车载-MR')
    expect(sortDeviceGroupNames(['10组', '车载-3SW', '车载 MR', '车站', 'bOcc', 'cocc', '2组']))
      .toEqual(['cocc', 'bOcc', '车站', '车载 MR', '2组', '10组', '车载-3SW'])
  })
})
