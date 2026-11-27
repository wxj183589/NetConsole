import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useWorkspaceStore } from './stores/workspace'
import { getHealth } from './api/client'
import { refreshSiteContext } from './stores/siteContext'
import {
  getPlatformAdapter,
  initializePlatformRuntime,
} from './platform/runtime'
import 'element-plus/theme-chalk/dark/css-vars.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-notification.css'
import './theme/tokens.css'
import './theme/light.css'
import './theme/dark.css'
import './theme/element-plus.css'
import './styles/main.css'
import { applySafeSystemAppearance, initializeSystemAppearance } from './settings/appearance'

const startupProfile = import.meta.env.VITE_NETCONSOLE_STARTUP_PROFILE === '1'
const startupStartedAt = performance.now()

function traceStartupStage(
  stage: string,
  phase: 'start' | 'end',
  request?: string,
  startedAt?: number,
): void {
  if (!startupProfile) return
  const elapsedMs = performance.now() - startupStartedAt
  console.info('NETCONSOLE_STARTUP_STAGE', JSON.stringify({
    stage,
    phase,
    elapsed_ms: Number(elapsedMs.toFixed(1)),
    ...(startedAt === undefined ? {} : { duration_ms: Number((performance.now() - startedAt).toFixed(1)) }),
    ...(request ? { request } : {}),
  }))
}

async function measureStartupStage<T>(
  stage: string,
  request: string | undefined,
  action: () => Promise<T>,
): Promise<T> {
  const startedAt = performance.now()
  traceStartupStage(stage, 'start', request)
  try {
    return await action()
  } finally {
    traceStartupStage(stage, 'end', request, startedAt)
  }
}

async function bootstrap(): Promise<void> {
  // Electron 在系统配色启动页上等待持久化设置；Browser 仍需要同步安全默认。
  if (!window.netconsoleDesktop) applySafeSystemAppearance()
  try {
    await measureStartupStage('renderer.platform_runtime', 'IPC:getRuntimeConfig', async () => {
      await initializePlatformRuntime()
    })
  } catch (cause) {
    getPlatformAdapter().reportRendererReady(false, 'failed')
    const root = document.querySelector('#app')
    if (root) root.textContent = cause instanceof Error ? cause.message : '桌面运行时初始化失败'
    return
  }
  await measureStartupStage('renderer.system_appearance', 'IPC:read persisted appearance', initializeSystemAppearance)
  const pinia = createPinia()
  const application = createApp(App).use(pinia).use(router)
  await measureStartupStage('renderer.router_ready', 'initial route component resolution', () => router.isReady())
  const currentUrl = new URL(window.location.href)
  const surface = currentUrl.searchParams.get('workspace_window') === '1'
    ? 'workspace-window'
    : 'main'
  await measureStartupStage(
    'renderer.workspace_restore',
    'IPC:getWorkspaceWindowState; initial route redirect',
    () => useWorkspaceStore(pinia).initialize(router),
  )
  const mountStartedAt = performance.now()
  const firstViewStartedAt = performance.now()
  traceStartupStage('renderer.first_view', 'start')
  traceStartupStage('renderer.application_mount', 'start')
  application.mount('#app')
  traceStartupStage('renderer.application_mount', 'end', undefined, mountStartedAt)
  await nextTick()
  traceStartupStage('renderer.first_view', 'end', undefined, firstViewStartedAt)
  const runtime = getPlatformAdapter()
  if (runtime.hostType === 'electron') {
    runtime.reportRendererReady(true, 'mounted', surface)
    try {
      const health = await measureStartupStage('renderer.health_check', 'GET /api/health', getHealth)
      const rendererSiteId = surface === 'main'
        ? await measureStartupStage(
          'renderer.site_context',
          'GET /api/v1/sites/runtime-context',
          refreshSiteContext,
        )
          .then((context) => context?.siteId)
          .catch(() => undefined)
        : undefined
      runtime.reportRendererReady(health.status === 'ok', 'interactive', surface, rendererSiteId)
    } catch {
      runtime.reportRendererReady(false, 'failed', surface)
    }
  }
}

void bootstrap()
