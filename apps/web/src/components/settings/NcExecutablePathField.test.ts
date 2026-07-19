import { describe, expect, it } from 'vitest'

import source from './NcExecutablePathField.vue?raw'

describe('NcExecutablePathField', () => {
  it('keeps executable path actions separate and responsive', () => {
    expect(source).toContain('grid-template-columns: minmax(0, 1fr) auto')
    expect(source).toContain('display: inline-flex')
    expect(source).toContain('gap: 6px')
    expect(source).toContain('min-width: 64px')
    expect(source).toContain('margin-left: 0')
    expect(source).toContain('@media (max-width: 900px)')
    expect(source).toContain('grid-template-columns: 1fr')
    expect(source).not.toContain('position: absolute')
  })

  it('renders complete select, clear and optional test actions with field feedback', () => {
    expect(source).toContain('>选择</el-button>')
    expect(source).toContain('>清空</el-button>')
    expect(source).toContain('>试启动</el-button>')
    expect(source).toContain('nc-executable-path-field__error')
    expect(source).toContain('nc-executable-path-field__success')
    expect(source).toContain('min-height: 20px')
  })
})
