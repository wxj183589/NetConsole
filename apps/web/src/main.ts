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
    getPlatformAdapter().reportRendererReady(false)
    const root = document.querySelector('#app')
    if (root) root.textContent = cause instanceof Error ? cause.message : '桌面运行时初始化失败'
    return
  }
  if (getPlatformAdapter().hostType === 'electron') {
    try {
      applySystemAppearance((await getSystemSettings()).values)
    } catch {
      // 设置页会显示受控错误；启动仍保留默认外观。
    }
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
