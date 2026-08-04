import { describe, expect, it, vi } from 'vitest'

import { coordinateSiteSwitch, SiteSwitchCancelled } from './site-switch'

describe('site switch coordination', () => {
  it('treats a page cancellation during workspace preparation as cancelled', async () => {
    const coordinator = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => { throw new SiteSwitchCancelled() }),
      activate: vi.fn(async () => undefined),
      restart: vi.fn(async () => undefined),
      restoreWorkspace: vi.fn(async () => undefined),
    }

    await expect(coordinateSiteSwitch(
      { siteId: 'line-b', displayName: '线路 B' },
      coordinator,
    )).resolves.toBe('cancelled')
    expect(coordinator.activate).not.toHaveBeenCalled()
    expect(coordinator.restoreWorkspace).not.toHaveBeenCalled()
  })
})
