// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest'

import {
  coordinateSiteSwitch,
  notifyBeforeSiteSwitch,
  SITE_SWITCH_METADATA_EVENT,
  SiteSwitchCancelled,
  type SiteSwitchMetadataDetail,
} from './site-switch'

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
    const metadata: SiteSwitchMetadataDetail[] = []
    const listener = (event: Event) => {
      metadata.push((event as CustomEvent<SiteSwitchMetadataDetail>).detail)
    }
    window.addEventListener(SITE_SWITCH_METADATA_EVENT, listener)
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
    expect(metadata.map((item) => item.state)).toEqual(['loading', 'rollback'])
    window.removeEventListener(SITE_SWITCH_METADATA_EVENT, listener)
  })

  it('publishes target metadata before waiting for Backend handoff', async () => {
    let finishRestart: (() => void) | undefined
    const metadata: SiteSwitchMetadataDetail[] = []
    window.addEventListener(SITE_SWITCH_METADATA_EVENT, (event) => {
      metadata.push((event as CustomEvent<SiteSwitchMetadataDetail>).detail)
    }, { once: true })
    const coordinator = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => ({ previous: true })),
      activate: vi.fn(async () => undefined),
      restart: vi.fn(() => new Promise<void>((resolve) => { finishRestart = resolve })),
      restoreWorkspace: vi.fn(async () => undefined),
    }

    const switching = coordinateSiteSwitch(
      { siteId: 'line-b', displayName: '线路 B' },
      coordinator,
    )
    await vi.waitFor(() => expect(metadata).toEqual([{
      siteId: 'line-b',
      displayName: '线路 B',
      state: 'loading',
    }]))
    expect(coordinator.restart).toHaveBeenCalledOnce()

    finishRestart?.()
    await expect(switching).resolves.toBe('completed')
  })

  it('uses the Backend runtime rebind result without restarting the Backend', async () => {
    const coordinator = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => ({ previous: true })),
      activate: vi.fn(async () => ({ restart_required: false })),
      restart: vi.fn(async () => undefined),
      restoreWorkspace: vi.fn(async () => undefined),
    }

    await expect(coordinateSiteSwitch(
      { siteId: 'line-b', displayName: '线路 B' },
      coordinator,
    )).resolves.toBe('completed')
    expect(coordinator.restart).not.toHaveBeenCalled()
  })

  it('restores the metadata indicator when warm handoff fails', async () => {
    const metadata: SiteSwitchMetadataDetail[] = []
    const listener = (event: Event) => {
      metadata.push((event as CustomEvent<SiteSwitchMetadataDetail>).detail)
    }
    window.addEventListener(SITE_SWITCH_METADATA_EVENT, listener)
    const coordinator = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => ({ previous: true })),
      activate: vi.fn(async () => undefined),
      restart: vi.fn(async () => { throw new Error('candidate failed') }),
      restoreWorkspace: vi.fn(async () => undefined),
    }

    await expect(coordinateSiteSwitch(
      { siteId: 'line-b', displayName: '线路 B' },
      coordinator,
    )).rejects.toThrow('candidate failed')

    expect(metadata.map((item) => item.state)).toEqual(['loading', 'rollback'])
    expect(coordinator.restoreWorkspace).toHaveBeenCalledOnce()
    window.removeEventListener(SITE_SWITCH_METADATA_EVENT, listener)
  })
})
