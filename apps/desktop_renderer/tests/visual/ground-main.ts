import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import { initializePlatformRuntime } from '../../src/platform/runtime'
import { loadRendererFeatures } from '../../src/features'
import VisualGroundFixture from './VisualGroundFixture.vue'
import 'element-plus/theme-chalk/dark/css-vars.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import '../../src/theme/tokens.css'
import '../../src/theme/light.css'
import '../../src/theme/element-plus.css'
import '../../src/styles/main.css'

document.documentElement.dataset.theme = 'light'
window.netconsoleDesktop = {
  getRuntimeConfig: async () => ({
    hostType: 'electron', apiBaseUrl: window.location.origin,
    apiToken: 'visual-test-session-token-000000000000',
  }),
  onBackendStatusChanged: () => () => undefined,
} as unknown as NetConsoleDesktopBridge
await initializePlatformRuntime()
await loadRendererFeatures()
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: VisualGroundFixture }] })
await router.push('/')
await router.isReady()
createApp(VisualGroundFixture).use(createPinia()).use(router).mount('#app')
