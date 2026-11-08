import { createApp } from 'vue'
import { createPinia } from 'pinia'
import type { NetConsoleDesktopBridge } from '../../../desktop_electron/src/shared/bridge'
import { initializePlatformRuntime } from '../../src/platform/runtime'
import VisualMeshBusinessFixture from './VisualMeshBusinessFixture.vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '../../src/theme/tokens.css'
import '../../src/theme/light.css'
import '../../src/theme/dark.css'
import '../../src/theme/element-plus.css'
import '../../src/styles/main.css'

document.documentElement.dataset.theme = 'dark'
document.documentElement.classList.add('dark')
window.netconsoleDesktop = {
  getRuntimeConfig: async () => ({ hostType: 'electron', apiBaseUrl: window.location.origin, apiToken: 'mesh-fixture-token-0000000000000000' }),
  onBackendStatusChanged: () => () => undefined,
} as unknown as NetConsoleDesktopBridge
await initializePlatformRuntime()
createApp(VisualMeshBusinessFixture).use(createPinia()).mount('#app')
