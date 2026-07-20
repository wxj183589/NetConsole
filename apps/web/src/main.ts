import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { getHealth } from './api/client'
import {
  getPlatformAdapter,
  initializePlatformRuntime,
} from './platform/runtime'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './theme/tokens.css'
import './theme/light.css'
import './theme/dark.css'
import './theme/element-plus.css'
import './styles/main.css'
import { applySafeSystemAppearance, initializeSystemAppearance } from './settings/appearance'

async function bootstrap(): Promise<void> {
  // Electron 在系统配色启动页上等待持久化设置；Browser 仍需要同步安全默认。
  if (!window.netconsoleDesktop) applySafeSystemAppearance()
  try {
    await initializePlatformRuntime()
  } catch (cause) {
    getPlatformAdapter().reportRendererReady(false, 'failed')
    const root = document.querySelector('#app')
    if (root) root.textContent = cause instanceof Error ? cause.message : '桌面运行时初始化失败'
    return
  }
  await initializeSystemAppearance()
  const application = createApp(App).use(createPinia()).use(router)
  const currentUrl = new URL(window.location.href)
  const surface = currentUrl.pathname === '/desktop/tasks' && currentUrl.searchParams.get('task_window') === '1'
    ? 'task-window'
    : 'main'
  application.mount('#app')
  const runtime = getPlatformAdapter()
  if (runtime.hostType === 'electron') {
    runtime.reportRendererReady(true, 'mounted', surface)
    try {
      const health = await getHealth()
      if (surface === 'main') runtime.reportRendererReady(health.status === 'ok', 'interactive', surface)
    } catch {
      runtime.reportRendererReady(false, 'failed', surface)
    }
  }
}

void bootstrap()
