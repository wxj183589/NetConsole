import { createRouter, createWebHistory } from 'vue-router'

import { enforceRouteFeature } from './featureGuard'
import { appRoutes } from './routes'

const router = createRouter({
  history: createWebHistory(),
  routes: appRoutes,
})

router.beforeEach(enforceRouteFeature)

export default router
