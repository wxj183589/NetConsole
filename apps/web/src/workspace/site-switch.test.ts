// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest'

import { coordinateSiteSwitch, notifyBeforeSiteSwitch, SiteSwitchCancelled } from './site-switch'

describe('site switch coordination', () => {
  it('waits for active pages to resolve an asynchronous dirty-draft decision', async () => {
    let resolveDraft: ((value: boolean) => void) | undefined
    window.addEventListener('netconsole:before-site-switch', (event) => {
      const detail = (event as CustomEvent<{ waitUntil: (promise: Promise<boolean>) => void }>).detail
      detail.waitUntil(new Promise((resolve) => { resolveDraft = resolve }))
    }, { once: true })
    const pending = notifyBeforeSiteSwitch('line-b')

    resolveDraft?.(true)
    await expect(pending).resolves.toBe(true)
  })

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
