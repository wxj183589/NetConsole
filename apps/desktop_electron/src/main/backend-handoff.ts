import type { BackendRuntimeInfo } from './backend-manager'

export interface WarmHandoffBackend {
  start(): Promise<BackendRuntimeInfo>
  stop(): Promise<void>
}

export interface WarmBackendHandoffOptions<TBackend extends WarmHandoffBackend> {
  current: TBackend
  candidate: TBackend
  verify(runtime: BackendRuntimeInfo): Promise<void>
  commit(candidate: TBackend, runtime: BackendRuntimeInfo): Promise<void>
  rollback?(): Promise<void>
}

export interface WarmBackendHandoffResult<TBackend extends WarmHandoffBackend> {
  active: TBackend
  retired: TBackend
  runtime: BackendRuntimeInfo
}

/**
 * Start and verify a replacement Backend before changing the active runtime.
 * The caller owns retiring the previous process after Renderer handoff.
 */
export async function prepareWarmBackendHandoff<TBackend extends WarmHandoffBackend>(
  options: WarmBackendHandoffOptions<TBackend>,
): Promise<WarmBackendHandoffResult<TBackend>> {
  let commitStarted = false
  try {
    const runtime = await options.candidate.start()
    await options.verify(runtime)
    commitStarted = true
    await options.commit(options.candidate, runtime)
    return {
      active: options.candidate,
      retired: options.current,
      runtime,
    }
  } catch (cause) {
    if (commitStarted && options.rollback) {
      try {
        await options.rollback()
      } catch {
        // Preserve the handoff failure. The caller performs site-level recovery.
      }
    }
    try {
      await options.candidate.stop()
    } catch {
      // Preserve the original startup, verification, or commit failure.
    }
    throw cause
  }
}
