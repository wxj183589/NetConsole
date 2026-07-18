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
import { getSystemSettings } from './api/systemSettings'
import { applySystemAppearance } from './settings/appearance'

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
  const runtime = getPlatformAdapter()
  if (runtime.hostType === 'electron') {
    runtime.reportRendererReady(true, 'mounted')
    void getSystemSettings().then((settings) => applySystemAppearance(settings.values)).catch(() => {
      // 设置页会显示受控错误；启动仍保留默认外观。
    })
    try {
      const health = await getHealth()
      runtime.reportRendererReady(health.status === 'ok', 'interactive')
    } catch {
      runtime.reportRendererReady(false, 'failed')
    }
  }
}

void bootstrap()
