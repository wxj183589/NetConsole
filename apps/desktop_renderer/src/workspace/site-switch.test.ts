// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  coordinateSiteSwitch,
  CURRENT_SITE_CHANGED_EVENT,
  notifyBeforeSiteSwitch,
  SITE_CONTEXT_CHANGED_EVENT,
  SITE_SWITCH_METADATA_EVENT,
  SiteSwitchCancelled,
  type SiteSwitchMetadataDetail,
} from './site-switch'
import { clearSiteContext, getSiteContextSnapshot, setActiveSiteContext } from '../stores/siteContext'

beforeEach(() => {
  clearSiteContext()
})

describe('site switch coordination', () => {
  it('uses the canonical current-site-changed event after a successful commit', () => {
    expect(CURRENT_SITE_CHANGED_EVENT).toBe('netconsole:current-site-changed')
  })

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

  it('does not publish the target as active until activation succeeds', async () => {
    setActiveSiteContext({ site_id: 'line-a', display_name: '线路 A', revision: 'rev-a' })
    let finishActivation: ((value: unknown) => void) | undefined
    const changed: unknown[] = []
    const listener = (event: Event) => {
      changed.push((event as CustomEvent<unknown>).detail)
    }
    window.addEventListener(SITE_CONTEXT_CHANGED_EVENT, listener)
    const coordinator = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => ({ previous: true })),
      activate: vi.fn(() => new Promise((resolve) => { finishActivation = resolve })),
      restart: vi.fn(async () => undefined),
      restoreWorkspace: vi.fn(async () => undefined),
      refreshCurrentContext: vi.fn(async () => ({ site_id: 'line-b', display_name: '线路 B', revision: 'rev-b' })),
      refreshTraySiteState: vi.fn(async () => undefined),
    }

    const switching = coordinateSiteSwitch(
      { siteId: 'line-b', displayName: '线路 B' },
      coordinator,
    )
    await vi.waitFor(() => expect(coordinator.activate).toHaveBeenCalledOnce())
    expect(getSiteContextSnapshot()).toEqual({ siteId: 'line-a', displayName: '线路 A', revision: 'rev-a' })
    finishActivation?.({ site_id: 'line-b', display_name: '线路 B', revision: 'rev-b', restart_required: false })
    await expect(switching).resolves.toBe('completed')
    expect(getSiteContextSnapshot()).toEqual({ siteId: 'line-b', displayName: '线路 B', revision: 'rev-b' })
    expect(changed).toEqual([{ siteId: 'line-b', displayName: '线路 B', revision: 'rev-b' }])
    expect(coordinator.refreshCurrentContext).toHaveBeenCalledOnce()
    expect(coordinator.refreshTraySiteState).toHaveBeenCalledOnce()
    window.removeEventListener(SITE_CONTEXT_CHANGED_EVENT, listener)
  })

  it('serializes rapid switch requests and leaves the last completed target active', async () => {
    let finishFirst: (() => void) | undefined
    const first = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => ({ first: true })),
      activate: vi.fn(() => new Promise((resolve) => { finishFirst = () => resolve({ site_id: 'line-b', display_name: '线路 B', revision: 'rev-b', restart_required: false }) })),
      restart: vi.fn(async () => undefined),
      restoreWorkspace: vi.fn(async () => undefined),
    }
    const second = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => ({ second: true })),
      activate: vi.fn(async () => ({ site_id: 'line-c', display_name: '线路 C', revision: 'rev-c', restart_required: false })),
      restart: vi.fn(async () => undefined),
      restoreWorkspace: vi.fn(async () => undefined),
    }

    const firstSwitch = coordinateSiteSwitch({ siteId: 'line-b', displayName: '线路 B' }, first)
    await vi.waitFor(() => expect(first.activate).toHaveBeenCalledOnce())
    const secondSwitch = coordinateSiteSwitch({ siteId: 'line-c', displayName: '线路 C' }, second)
    await Promise.resolve()
    expect(second.confirm).not.toHaveBeenCalled()
    finishFirst?.()
    await expect(firstSwitch).resolves.toBe('completed')
    await expect(secondSwitch).resolves.toBe('completed')
    expect(second.confirm).toHaveBeenCalledOnce()
    expect(getSiteContextSnapshot()).toEqual({ siteId: 'line-c', displayName: '线路 C', revision: 'rev-c' })
  })

  it('keeps the previous context after a failed switch', async () => {
    setActiveSiteContext({ site_id: 'line-a', display_name: '线路 A', revision: 'rev-a' })
    const coordinator = {
      isBlocked: () => false,
      confirm: vi.fn(async () => true),
      preflight: vi.fn(async () => undefined),
      prepareWorkspace: vi.fn(async () => { throw new Error('candidate failed') }),
      activate: vi.fn(async () => undefined),
      restart: vi.fn(async () => undefined),
      restoreWorkspace: vi.fn(async () => undefined),
    }

    await expect(coordinateSiteSwitch(
      { siteId: 'line-b', displayName: '线路 B' },
      coordinator,
    )).rejects.toThrow('candidate failed')
    expect(getSiteContextSnapshot()).toEqual({ siteId: 'line-a', displayName: '线路 A', revision: 'rev-a' })
  })
})
