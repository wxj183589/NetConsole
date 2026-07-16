import { describe, expect, it } from 'vitest'

import { flattenNavigation } from '../navigation/registry'
import { appRoutes } from './routes'

describe('Web route ownership', () => {
  const root = appRoutes[0]
  const routes = root.children ?? []

  it('gives every business route navigation ownership or marks it hidden', () => {
    expect(root.path).toBe('/')
    for (const route of routes) {
      const meta = route.meta ?? {}
      expect(Boolean(meta.navigationId || meta.hiddenRoute)).toBe(true)
      expect(typeof meta.moduleId).toBe('string')
      expect(typeof meta.title).toBe('string')
      expect(typeof meta.desktopOnly).toBe('boolean')
    }
  })

  it('maps every implemented navigation leaf to a named route', () => {
    const routeNames = new Set(routes.flatMap((route) => route.name ? [String(route.name)] : []))
    const leaves = flattenNavigation().filter((item) => item.implemented && item.route_name)
    expect(leaves.every((item) => routeNames.has(String(item.route_name)))).toBe(true)
  })

  it('keeps legacy AC and toolbox redirects', () => {
    expect(routes.find((route) => route.path === 'ac-management')?.redirect).toEqual({ name: 'ac-fit-aps' })
    expect(routes.find((route) => route.path === 'network-tools/overview')?.redirect).toEqual({ name: 'network-tools-toolbox' })
  })

  it('does not register excluded or unfinished routes', () => {
    const paths = routes.map((route) => `/${route.path}`)
    expect(paths.some((path) => /snmp|wifi-survey/.test(path))).toBe(false)
    expect(paths).toContain('/network-tools/wireless-scan')
    expect(paths).not.toContain('/command-reference')
  })
})
