/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import source from './AppLayout.vue?raw'
import routeViewSource from './AppRouteView.vue?raw'
import ncLayoutSource from './NcLayout.vue?raw'
import routesSource from '../router/routes.ts?raw'

const styles = readFileSync(fileURLToPath(new URL('../styles/main.css', import.meta.url)), 'utf8')

describe('App layout foundation', () => {
  it('renders navigation from the shared registry instead of hard-coded entries', () => {
    expect(source).toContain("from '../navigation/registry'")
    expect(source).toContain('v-for="entry in navigationItems"')
    expect(source).not.toContain('route.path.startsWith')
    expect(source).not.toContain('<span>设备管理</span>')
  })

  it('shows the fixed stale frontend warning', () => {
    expect(source).toContain('当前 Desktop Renderer 资源与后端版本不一致，请重新构建桌面界面资源。')
    expect(source).toContain('frontendBuildId.value !== backendBuildId.value')
    expect(source).toContain("document.querySelector('[data-netconsole-build-warning]')")
  })

  it('marks Backend Online only after a rebound runtime passes health again', () => {
    expect(source).toContain('onPlatformRuntimeStatusChanged((status) =>')
    expect(source).toContain("if (status.state === 'ready')")
    expect(source).toContain('void refreshBackendHealth()')
    expect(source).toContain('backendOnline.value = false')
  })

  it('keeps sidebar state and responds at collapse and drawer breakpoints', () => {
    expect(source).toContain("const COLLAPSED_KEY = 'netconsole.desktop.sidebar.collapsed'")
    expect(source).toContain("const OPEN_GROUPS_KEY = 'netconsole.desktop.sidebar.open-groups'")
    expect(source).not.toContain('netconsole.web.sidebar')
    expect(source).toContain('sessionStorage.setItem(COLLAPSED_KEY')
    expect(source).toContain('sessionStorage.setItem(OPEN_GROUPS_KEY')
    expect(source).toContain('viewportWidth.value < 1100')
    expect(source).toContain('viewportWidth.value < 850')
    expect(styles).toContain('.app-menu .el-sub-menu__title')
    expect(styles).toContain('.app-menu .el-menu--inline')
    expect(styles).toContain('@media (max-width: 850px)')
    expect(styles).toContain('html, body, #app { width: 100%; min-width: 0;')
    expect(source).toContain("'var(--nc-shell-sidebar-width)'")
    expect(source).toContain('class="brand-logo"')
    expect(source).toContain("const BRAND_LOGO_URL = '/branding/netconsole.png'")
    expect(source).toContain(':src="BRAND_LOGO_URL"')
    expect(source).toContain('alt="NetConsole"')
    expect(source).not.toMatch(/>\s*NC\s*</)
    expect(styles).toContain('.brand-logo { flex: 0 0 auto; width: 64px; max-height: 38px; object-fit: contain; }')
    expect(styles).toContain('.app-sidebar.collapsed .brand-logo')
    expect(styles).toContain('height: var(--nc-shell-header-height)')
    expect(styles).toContain('padding: var(--nc-content-padding)')
    expect(styles).not.toContain('min-width: 960px')
  })

  it('keeps workspace routes alive by isolated tab cache keys', () => {
    expect(routesSource).toMatch(/name: 'mesh-analysis'.*identity: 'singleton'/)
    expect(source).toContain('<AppRouteView />')
    expect(source).toContain('<WorkspaceTabBar />')
    expect(routeViewSource).toContain(':include="cachedWorkspaceComponentNames"')
    expect(routeViewSource).toContain(':key="workspace.routeCacheKey(viewRoute.fullPath)"')
    expect(routeViewSource).toContain('class="app-route-viewport"')
  })

  it('passes the remaining shell height through one scrollable route viewport', () => {
    expect(styles).toContain('.app-shell { position: relative; height: 100dvh; overflow: hidden; }')
    expect(styles).toContain('.app-main.el-main { display: flex; width: 100%; min-height: 0;')
    expect(styles).toContain('.app-route-viewport { flex: 1 1 auto; min-height: 0; overflow: auto; }')
    expect(styles).toContain('.frontend-build-warning { flex: 0 0 auto;')
  })

  it('keeps the root menu on the sidebar palette after lazy Element Plus styles load', () => {
    expect(styles).toContain('--el-menu-bg-color: transparent')
    expect(styles).toContain('--el-menu-text-color: var(--nc-text-secondary)')
    expect(styles).toContain('--el-menu-hover-bg-color: var(--nc-bg-hover)')
    expect(styles).toContain('--el-menu-active-color: var(--nc-text-active)')
    expect(styles).toContain('.el-menu--popup')
  })

  it('lets routed pages use all desktop workspace width without breaking narrow tables', () => {
    expect(styles).toContain('.app-workspace { width: 0; height: 100%; min-width: 0; min-height: 0; flex: 1 1 auto; }')
    expect(styles).toContain('.app-shell .app-workspace .app-main > * { width: 100%; max-width: var(--nc-content-max-width); margin-inline: 0; }')
    expect(styles).toContain('.app-main .el-table { width: 100%; }')
    expect(styles).toContain('.app-main.el-main { display: flex; width: 100%;')
    expect(styles).toContain('.task-center { max-width: var(--nc-content-max-width); margin-inline: 0; }')
    expect(styles).toContain('.agent-center { max-width: var(--nc-content-max-width); margin-inline: 0; }')
    expect(styles).toContain('@media (max-width: 850px)')
    expect(ncLayoutSource).toContain("maxWidth: 'var(--nc-content-max-width)'")
    expect(ncLayoutSource).not.toContain("maxWidth: '1680px'")
  })

  it('themes shell states and scrollbars entirely through semantic tokens', () => {
    expect(styles).toContain('background: var(--nc-bg-sidebar)')
    expect(styles).toContain('background: var(--nc-bg-header)')
    expect(styles).toContain('background: var(--nc-bg-active)')
    expect(styles).toContain('color: var(--nc-text-disabled)')
    expect(styles).toContain('scrollbar-color: var(--nc-scrollbar-thumb) transparent')
    expect(styles).toContain('background-color: var(--nc-scrollbar-thumb-hover)')
  })
})
