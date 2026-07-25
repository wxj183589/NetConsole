import { describe, expect, it } from 'vitest'

import {
  meshSessionPathSegment,
  normalizeMeshSessionIdentifier,
  normalizeOpaqueIdentifier,
} from './opaqueIdentifier'

describe('opaque identifiers', () => {
  it('preserves backend separators and encodes the complete MESH session id', () => {
    const sessionId = 'c4682b2a-ba83-44f2-8bc9-3d2b37c37237:1'
    expect(normalizeMeshSessionIdentifier(`  ${sessionId}  `)).toBe(sessionId)
    expect(normalizeMeshSessionIdentifier('source.v2@line:12')).toBe('source.v2@line:12')
    expect(meshSessionPathSegment(sessionId)).toBe('c4682b2a-ba83-44f2-8bc9-3d2b37c37237%3A1')
  })

  it('rejects empty, control, local path and traversal values without a character whitelist', () => {
    expect(normalizeOpaqueIdentifier('')).toBeNull()
    expect(normalizeOpaqueIdentifier('session\n1')).toBeNull()
    expect(normalizeOpaqueIdentifier('C:\\private\\session')).toBeNull()
    expect(normalizeOpaqueIdentifier('file:///private/session')).toBeNull()
    expect(normalizeOpaqueIdentifier('../session')).toBeNull()
    expect(normalizeOpaqueIdentifier('x'.repeat(513))).toBeNull()
  })
})
