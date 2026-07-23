/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import source from './AppLayout.vue?raw'

const styles = readFileSync(fileURLToPath(new URL('../styles/main.css', import.meta.url)), 'utf8')

describe('App layout current site entry', () => {
  it('hosts one shared current-site indicator without crowding runtime status', () => {
    expect(source).toContain("import CurrentSiteIndicator from '../components/CurrentSiteIndicator.vue'")
    expect(source).toContain('<CurrentSiteIndicator />')
    expect(source.match(/<CurrentSiteIndicator \/>/g)).toHaveLength(1)
    expect(styles).toContain('.current-site-slot { flex: 0 1 280px; min-width: 150px; }')
    expect(styles).toContain('.header-status { display: flex; flex: 0 0 auto;')
    expect(styles).toContain('overflow: hidden; background: var(--nc-bg-header)')
  })
})
