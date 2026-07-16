import { describe, expect, it } from 'vitest'

import { redactSensitiveText } from '../src/main/logger'

describe('desktop log redaction', () => {
  it.each([
    ['authorization=Bearer bearer-token', 'bearer-token'],
    ['agent_token=agent-secret', 'agent-secret'],
    ['community: private-community', 'private-community'],
    ['ssh_key=private-key-material', 'private-key-material'],
    ['passphrase="quoted-passphrase"', 'quoted-passphrase'],
  ])('redacts credential fields from %s', (line, secret) => {
    const safe = redactSensitiveText(line)

    expect(safe).not.toContain(secret)
    expect(safe).toContain('***')
  })

  it('always removes the active runtime token even from unstructured text', () => {
    expect(redactSensitiveText('prefix runtime-secret suffix', ['runtime-secret'])).toBe(
      'prefix *** suffix',
    )
  })
})
