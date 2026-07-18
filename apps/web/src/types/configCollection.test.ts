import { describe, expect, it } from 'vitest'

import type { ConfigSnapshot } from './configCollection'

describe('config collection DTO types', () => {
  it('accepts a snapshot whose size is not available', () => {
    const snapshot: ConfigSnapshot = {
      id: 1,
      device_id: null,
      device_uuid: 'device-1',
      timestamp: '',
      type: 'running',
      size_bytes: null,
      artifact_id: '',
      filename: '',
      hash: '',
      created_at: '',
      error_message: '',
    }

    expect(snapshot.size_bytes).toBeNull()
  })
})
