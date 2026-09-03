export interface SiteContextReadinessOptions<T> {
  read: () => Promise<T | null>
  expectedSiteId: string
  timeoutMs?: number
  pollIntervalMs?: number
  delay?: (milliseconds: number) => Promise<void>
}

export async function waitForExpectedSiteContext<T extends { activeSiteId: string }>(
  options: SiteContextReadinessOptions<T>,
): Promise<T> {
  const timeoutMs = Math.max(1, options.timeoutMs ?? 10_000)
  const pollIntervalMs = Math.max(1, options.pollIntervalMs ?? 100)
  const delay = options.delay ?? ((milliseconds: number) => new Promise<void>((resolve) => {
    setTimeout(resolve, milliseconds)
  }))
  const startedAt = Date.now()
  let lastActiveSiteId = ''
  let lastReadError: unknown

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const context = await options.read()
      if (context?.activeSiteId === options.expectedSiteId) return context
      if (context?.activeSiteId) lastActiveSiteId = context.activeSiteId
    } catch (cause) {
      lastReadError = cause
    }
    const remainingMs = timeoutMs - (Date.now() - startedAt)
    if (remainingMs <= 0) break
    await delay(Math.min(pollIntervalMs, remainingMs))
  }

  const observed = lastActiveSiteId ? ` observed=${lastActiveSiteId}` : ''
  const readFailure = lastReadError instanceof Error ? ` last_error=${lastReadError.message}` : ''
  throw new Error(
    `Backend ready 后未在 ${timeoutMs}ms 内确认目标局点 ${options.expectedSiteId}.${observed}${readFailure}`,
  )
}
