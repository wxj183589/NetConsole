import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { getHealth } from './api/client'
import {
  getPlatformAdapter,
  initializePlatformRuntime,
} from './platform/runtime'
import './styles/main.css'

async function bootstrap(): Promise<void> {
  try {
    await initializePlatformRuntime()
  } catch (cause) {
    getPlatformAdapter().reportRendererReady(false)
    const root = document.querySelector('#app')
    if (root) root.textContent = cause instanceof Error ? cause.message : '桌面运行时初始化失败'
    return
  }

  createApp(App).use(createPinia()).use(router).mount('#app')
  const runtime = getPlatformAdapter()
  if (runtime.hostType === 'electron') {
    try {
      const health = await getHealth()
      runtime.reportRendererReady(health.status === 'ok')
    } catch {
      runtime.reportRendererReady(false)
    }
  }
}

void bootstrap()
