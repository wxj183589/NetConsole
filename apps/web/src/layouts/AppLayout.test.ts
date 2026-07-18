/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import source from './AppLayout.vue?raw'

const styles = readFileSync(fileURLToPath(new URL('../styles/main.css', import.meta.url)), 'utf8')

describe('App layout foundation', () => {
  it('renders navigation from the shared registry instead of hard-coded entries', () => {
    expect(source).toContain("from '../navigation/registry'")
    expect(source).toContain('v-for="entry in navigationItems"')
    expect(source).not.toContain('route.path.startsWith')
    expect(source).not.toContain('<span>设备管理</span>')
  })

  it('shows the fixed stale frontend warning', () => {
    expect(source).toContain('当前 Web 前端资源与后端版本不一致，请重新构建 Web 资源。')
    expect(source).toContain('frontendBuildId.value !== backendBuildId.value')
    expect(source).toContain("document.querySelector('[data-netconsole-build-warning]')")
  })

  it('keeps sidebar state and responds at collapse and drawer breakpoints', () => {
    expect(source).toContain('sessionStorage.setItem(COLLAPSED_KEY')
    expect(source).toContain('sessionStorage.setItem(OPEN_GROUPS_KEY')
    expect(source).toContain('viewportWidth.value < 1100')
    expect(source).toContain('viewportWidth.value < 850')
    expect(styles).toContain('.app-menu .el-sub-menu__title')
    expect(styles).toContain('.app-menu .el-menu--inline')
    expect(styles).toContain('@media (max-width: 850px)')
    expect(styles).toContain('html, body, #app { width: 100%; min-width: 0;')
    expect(source).toContain("'var(--nc-shell-sidebar-width)'")
    expect(styles).toContain('height: var(--nc-shell-header-height)')
    expect(styles).toContain('padding: var(--nc-content-padding)')
    expect(styles).not.toContain('min-width: 960px')
  })

  it('keeps the root menu on the sidebar palette after lazy Element Plus styles load', () => {
    expect(styles).toContain('--el-menu-bg-color: transparent')
    expect(styles).toContain('--el-menu-text-color: color-mix(in srgb, var(--nc-text-inverse), transparent 38%)')
    expect(styles).toContain('--el-menu-hover-bg-color: var(--nc-bg-sidebar-hover)')
    expect(styles).toContain('--el-menu-active-color: var(--nc-primary-hover)')
  })
})
