import { mkdir, readFile, readdir, rm, utimes, writeFile } from 'node:fs/promises'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  createFileLogger,
  redactSensitiveText,
  truncateApplicationDetail,
} from '../src/main/logger'

async function temporaryDirectory(): Promise<string> {
  return mkdtempSync(join(tmpdir(), 'netconsole-logger-test-'))
}

describe('desktop file logger lifecycle', () => {
  it('rotates the active file at the configured size and keeps it writable', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      await writeFile(active, Buffer.alloc(128, 0x78))
      const logger = createFileLogger(active, {
        maxFileBytes: 128,
        now: () => new Date('2026-08-10T01:15:23.000Z'),
      })
      logger('AFTER_ROTATE', 'ready')
      await logger.flush()
      const names = await readdir(root)
      expect(names.some((name) => /^electron-20260810-/.test(name))).toBe(true)
      expect((await readFile(active, 'utf8')).includes('AFTER_ROTATE')).toBe(true)
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('allocates monotonically increasing same-day rotation sequence numbers', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      const logger = createFileLogger(active, {
        maxFileBytes: 64,
        now: () => new Date('2026-08-10T01:15:23.000Z'),
      })
      await writeFile(active, Buffer.alloc(64, 0x78))
      logger('ROTATE_ONE', 'x')
      await logger.flush()
      await writeFile(active, Buffer.alloc(64, 0x78))
      logger('ROTATE_TWO', 'x')
      await logger.flush()
      const names = (await readdir(root)).filter((name) => name.startsWith('electron-20260810-'))
      expect(names.map((name) => name.slice(-8, -4)).sort()).toEqual(['0001', '0002'])
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('rotates when the active file crosses a local date boundary', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      await writeFile(active, 'previous day\n')
      const previous = new Date('2026-08-09T23:59:00.000')
      await utimes(active, previous, previous)
      const logger = createFileLogger(active, {
        maxFileBytes: 1024 * 1024,
        now: () => new Date('2026-08-10T00:00:01.000'),
      })
      logger('DATE_ROLL', 'new day')
      await logger.flush()
      expect((await readdir(root)).some((name) => name.startsWith('electron-20260810-'))).toBe(true)
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('suppresses a repeated fingerprint and emits a periodic summary', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      let clock = new Date('2026-08-10T01:00:00.000Z').getTime()
      const logger = createFileLogger(active, { now: () => new Date(clock) })
      for (let index = 0; index < 13; index += 1) {
        logger('BACKEND_TIMEOUT', 'endpoint=/health status=504', 'WARNING')
        clock += 5_000
      }
      await logger.flush()
      const lines = (await readFile(active, 'utf8')).trim().split('\n')
      expect(lines).toHaveLength(2)
      expect(lines[1]).toContain('repeated=12')
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('writes the same fingerprint again after the suppression window', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      let clock = new Date('2026-08-10T01:00:00.000Z').getTime()
      const logger = createFileLogger(active, { now: () => new Date(clock) })
      logger('BACKEND_TIMEOUT', 'endpoint=/health status=504', 'WARNING')
      clock += 11_000
      logger('BACKEND_TIMEOUT', 'endpoint=/health status=504', 'WARNING')
      await logger.flush()
      expect((await readFile(active, 'utf8')).trim().split('\n')).toHaveLength(2)
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('guards application details and does not persist DEBUG in INFO mode', async () => {
    expect(truncateApplicationDetail('x'.repeat(200), 64)).toContain('payload_truncated=true')
    const largeApiResponse = JSON.stringify(Array.from({ length: 50_000 }, (_, index) => ({ index })))
    const summarized = truncateApplicationDetail(largeApiResponse)
    expect(summarized).toContain('payload_truncated=true')
    expect(summarized).not.toBe(largeApiResponse)
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      const logger = createFileLogger(active, { minimumLevel: 'INFO' })
      logger('DEBUG_EVENT', 'hidden', 'DEBUG')
      logger('INFO_EVENT', 'visible')
      await logger.flush()
      const content = await readFile(active, 'utf8')
      expect(content).toContain('INFO_EVENT')
      expect(content).not.toContain('DEBUG_EVENT')
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('survives a rename EBUSY and leaves a fallback diagnostic', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      await mkdir(root, { recursive: true })
      await writeFile(active, Buffer.alloc(64, 0x78))
      const logger = createFileLogger(active, {
        maxFileBytes: 64,
        renameFile: async () => { throw Object.assign(new Error('locked'), { code: 'EBUSY' }) },
      })
      logger('AFTER_EBUSY', 'task continues')
      await logger.flush()
      expect((await readFile(active, 'utf8')).includes('AFTER_EBUSY')).toBe(true)
      expect((await readFile(join(root, 'electron-log-fallback.log'), 'utf8')).includes('ELECTRON_LOG_ROTATION_FAILED')).toBe(true)
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it.each([100, 500, 1_000])('queues %i events without synchronous main-process I/O', async (count) => {
    const root = await temporaryDirectory()
    try {
      const logger = createFileLogger(join(root, 'electron.log'))
      const started = performance.now()
      for (let index = 0; index < count; index += 1) {
        logger('HIGH_RATE_EVENT', `sequence=${index}`)
      }
      const enqueueMs = performance.now() - started
      expect(enqueueMs).toBeLessThan(500)
      await logger.flush()
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })
})

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
