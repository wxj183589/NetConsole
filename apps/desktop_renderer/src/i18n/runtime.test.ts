import { afterEach, describe, expect, it } from 'vitest'

import { setAppLocale, t } from './runtime'

describe('Desktop Renderer runtime i18n', () => {
  afterEach(() => setAppLocale('zh_CN'))

  it('uses Desktop Renderer terminology in the English shell', () => {
    setAppLocale('en_US')

    expect(t('shell.console')).toBe('NetConsole')
    expect(t('shell.build_mismatch')).toBe(
      'The Desktop Renderer resources do not match the backend version. Rebuild the Desktop Renderer resources.',
    )
  })
})
