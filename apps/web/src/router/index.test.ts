import { describe, expect, it } from 'vitest'

import { flattenNavigation } from '../navigation/registry'
import { appRoutes } from './routes'

describe('Web route ownership', () => {
  const root = appRoutes.find((route) => route.path === '/')!
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
    expect(routes.find((route) => route.path === 'ac-management/optical')?.redirect).toEqual({ name: 'ac-fit-aps' })
    const meshRedirect = routes.find((route) => route.path === 'ac-management/mesh-links')?.redirect
    const monitorRedirect = routes.find((route) => route.path === 'ac/mesh-link-monitor')?.redirect
    expect(typeof meshRedirect).toBe('function')
    expect(typeof monitorRedirect).toBe('function')
    expect((meshRedirect as (to: { query: Record<string, string> }) => object)({ query: { query: '01' } })).toEqual({ name: 'rail-train-online', query: { query: '01' } })
    expect((monitorRedirect as (to: { query: Record<string, string> }) => object)({ query: {} })).toEqual({ name: 'rail-train-online', query: {} })
    expect(routes.find((route) => route.path === 'rail-transit/car-network-diagnostic')?.redirect).toEqual({ name: 'train-communication' })
    expect(routes.find((route) => route.path === 'rail-transit/train-communication')?.meta?.title).toBe('轨道交通 / 车内通信检测')
    expect(routes.find((route) => route.path === 'network-tools/overview')?.redirect).toEqual({ name: 'network-tools-toolbox' })
    expect(routes.find((route) => route.path === 'rail-transit/trackside-ap-plan')?.redirect).toEqual({
      name: 'rail-transit-base-data', query: { tab: 'trackside-ap-planning' },
    })
  })

  it('registers the standalone device detail route with list navigation context', () => {
    const route = routes.find((item) => item.name === 'device-detail')
    expect(route?.path).toBe('devices/:deviceId')
    expect(route?.meta?.navigationId).toBe('devices')
    expect(route?.meta?.hiddenRoute).toBe(true)
  })

  it('keeps the complete task center inside the main application shell', () => {
    const taskCenter = routes.find((route) => route.name === 'tasks')
    expect(taskCenter?.path).toBe('tasks')
    expect(appRoutes.some((route) => route.path === '/desktop/tasks')).toBe(false)
  })

  it('does not register excluded or unfinished routes', () => {
    const paths = routes.map((route) => `/${route.path}`)
    expect(paths.some((path) => /snmp|wifi-survey/.test(path))).toBe(false)
    expect(paths).toContain('/network-tools/wireless-scan')
    expect(paths).toContain('/command-reference')
  })
})
