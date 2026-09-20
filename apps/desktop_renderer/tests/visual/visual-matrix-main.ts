import { createApp } from 'vue'

import VisualMatrixFixture from './VisualMatrixFixture.vue'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '../../src/theme/tokens.css'
import '../../src/theme/light.css'
import '../../src/theme/dark.css'
import '../../src/theme/element-plus.css'
import '../../src/styles/main.css'

createApp(VisualMatrixFixture).mount('#app')
