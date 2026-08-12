import { appendFile, mkdir, readFile, readdir, rename, rm, utimes, writeFile } from 'node:fs/promises'
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

function appendAtLogicalTime(now: () => Date) {
  return async (path: string, line: string): Promise<void> => {
    await appendFile(path, line, 'utf8')
    const timestamp = now()
    await utimes(path, timestamp, timestamp)
  }
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
      const now = () => new Date(clock)
      const logger = createFileLogger(active, { now, appendLine: appendAtLogicalTime(now) })
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
      const now = () => new Date(clock)
      const logger = createFileLogger(active, { now, appendLine: appendAtLogicalTime(now) })
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

  it('bounds a 10000-event slow-disk burst and emits one recovery', async () => {
    const root = await temporaryDirectory()
    let releaseDisk: (() => void) | undefined
    let appendStartedResolve: (() => void) | undefined
    const appendStartedPromise = new Promise<void>((resolvePromise) => {
      appendStartedResolve = resolvePromise
    })
    const diskGate = new Promise<void>((resolvePromise) => { releaseDisk = resolvePromise })
    try {
      const active = join(root, 'electron.log')
      const logger = createFileLogger(active, {
        minimumLevel: 'DEBUG',
        queueSoftLimitBytes: 4 * 1024,
        queueHardLimitBytes: 8 * 1024,
        flushTimeoutMs: 30_000,
        appendLine: async (path, line) => {
          appendStartedResolve?.()
          appendStartedResolve = undefined
          await diskGate
          await appendFile(path, line, { encoding: 'utf8' })
        },
      })
      for (let index = 0; index < 10_000; index += 1) {
        const level = index % 500 === 0 ? 'ERROR' : index % 2 === 0 ? 'DEBUG' : 'INFO'
        logger(`BURST_${index}`, 'x'.repeat(256), level)
      }
      await appendStartedPromise
      const pressured = logger.getQueueMetrics()
      expect(pressured.queuedBytes).toBeLessThanOrEqual(8 * 1024)
      expect(pressured.peakQueuedBytes).toBeLessThanOrEqual(8 * 1024)
      expect(pressured.droppedDebug + pressured.droppedInfo).toBeGreaterThan(0)
      expect(pressured.droppedError).toBe(0)

      releaseDisk?.()
      await logger.flush(30_000)
      const content = await readFile(active, 'utf8')
      expect(content.match(/\| LOG_BACKPRESSURE \|/g)).toHaveLength(1)
      expect(content.match(/\| LOG_BACKPRESSURE_RECOVERED \|/g)).toHaveLength(1)
      expect(logger.getQueueMetrics().queuedBytes).toBe(0)
    } finally {
      releaseDisk?.()
      await rm(root, { recursive: true, force: true })
    }
  })

  it('reports whether a bounded flush reached disk', async () => {
    const root = await temporaryDirectory()
    let releaseDisk: (() => void) | undefined
    const diskGate = new Promise<void>((resolvePromise) => { releaseDisk = resolvePromise })
    try {
      const logger = createFileLogger(join(root, 'electron.log'), {
        appendLine: async (path, line) => {
          await diskGate
          await appendFile(path, line, { encoding: 'utf8' })
        },
      })
      logger('SLOW_DISK_EVENT')

      await expect(logger.flush(1)).resolves.toBe(false)
      releaseDisk?.()
      await expect(logger.flush(30_000)).resolves.toBe(true)
    } finally {
      releaseDisk?.()
      await rm(root, { recursive: true, force: true })
    }
  })

  it('backs off repeated EBUSY rotation failures and recovers rolling', async () => {
    const root = await temporaryDirectory()
    try {
      const active = join(root, 'electron.log')
      await writeFile(active, Buffer.alloc(64, 0x78))
      let clock = new Date('2026-08-10T01:00:00.000').getTime()
      let renameCalls = 0
      const logger = createFileLogger(active, {
        maxFileBytes: 64,
        now: () => new Date(clock),
        renameFile: async (source, target) => {
          renameCalls += 1
          if (renameCalls <= 3) throw Object.assign(new Error('locked'), { code: 'EBUSY' })
          await rename(source, target)
        },
      })
      for (let index = 0; index < 1_000; index += 1) logger(`EBUSY_${index}`, 'task continues')
      await logger.flush(30_000)
      expect(renameCalls).toBe(1)

      clock += 31_000
      logger('RETRY_2', 'after first backoff')
      await logger.flush()
      expect(renameCalls).toBe(2)
      clock += 61_000
      logger('RETRY_3', 'after second backoff')
      await logger.flush()
      expect(renameCalls).toBe(3)
      clock += 121_000
      logger('ROTATION_RECOVERED', 'after third backoff')
      await logger.flush()

      expect(renameCalls).toBe(4)
      expect((await readdir(root)).some((name) => name.startsWith('electron-20260810-'))).toBe(true)
      expect(await readFile(active, 'utf8')).toContain('ELECTRON_LOG_ROTATION_RECOVERED')
      const fallback = await readFile(join(root, 'electron-log-fallback.log'), 'utf8')
      expect(fallback.trim().split('\n').length).toBeLessThanOrEqual(2)
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('rate-limits and caps fallback diagnostics when the primary writer fails', async () => {
    const root = await temporaryDirectory()
    try {
      let writeNumber = 0
      const logger = createFileLogger(join(root, 'electron.log'), {
        fallbackMaxBytes: 512,
        appendLine: async () => {
          writeNumber += 1
          throw Object.assign(new Error(`disk failure ${writeNumber}`), { code: 'ENOSPC' })
        },
      })
      for (let index = 0; index < 100; index += 1) {
        logger(`PRIMARY_WRITE_${index}`, 'password=must-not-leak')
        await logger.flush()
      }
      const fallback = await readFile(join(root, 'electron-log-fallback.log'), 'utf8')
      expect(Buffer.byteLength(fallback, 'utf8')).toBeLessThanOrEqual(512)
      expect(fallback).not.toContain('must-not-leak')
      expect(fallback).toContain('ENOSPC')
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
