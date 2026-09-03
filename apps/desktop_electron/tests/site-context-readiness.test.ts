import { describe, expect, it } from 'vitest'

import { waitForExpectedSiteContext } from '../src/main/site-context-readiness'

describe('waitForExpectedSiteContext', () => {
  it('retries transient empty reads after backend health is ready', async () => {
    let reads = 0
    const context = await waitForExpectedSiteContext({
      expectedSiteId: 'site-b',
      read: async () => {
        reads += 1
        return reads < 3 ? null : { activeSiteId: 'site-b' }
      },
      timeoutMs: 100,
      pollIntervalMs: 1,
      delay: async () => undefined,
    })

    expect(context.activeSiteId).toBe('site-b')
    expect(reads).toBe(3)
  })

  it('does not accept a different site as readiness', async () => {
    await expect(
      waitForExpectedSiteContext({
        expectedSiteId: 'site-b',
        read: async () => ({ activeSiteId: 'site-a' }),
        timeoutMs: 1,
        pollIntervalMs: 1,
        delay: async () => undefined,
      }),
    ).rejects.toThrow(/目标局点 site-b/)
  })
})
