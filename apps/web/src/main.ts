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
import { initializeSystemAppearance } from './settings/appearance'

async function bootstrap(): Promise<void> {
  try {
    await initializePlatformRuntime()
  } catch (cause) {
    getPlatformAdapter().reportRendererReady(false, 'failed')
    const root = document.querySelector('#app')
    if (root) root.textContent = cause instanceof Error ? cause.message : '桌面运行时初始化失败'
    return
  }
  createApp(App).use(createPinia()).use(router).mount('#app')
  void initializeSystemAppearance()
  const runtime = getPlatformAdapter()
  if (runtime.hostType === 'electron') {
    runtime.reportRendererReady(true, 'mounted')
    try {
      const health = await getHealth()
      runtime.reportRendererReady(health.status === 'ok', 'interactive')
    } catch {
      runtime.reportRendererReady(false, 'failed')
    }
  }
}

void bootstrap()
