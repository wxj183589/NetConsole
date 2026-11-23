import { createRouter, createWebHistory, type NavigationGuard } from 'vue-router'

import { enforceRouteFeature } from './featureGuard'
import { appRoutes } from './routes'

const router = createRouter({
  history: createWebHistory(),
  routes: appRoutes,
})

export const redirectLegacyCommandReference: NavigationGuard = (to) => {
  if (to.name === 'logs' && to.query.tab === 'command-reference') {
    const { tab: _legacyTab, ...query } = to.query
    return { name: 'command-reference', query, hash: to.hash, replace: true }
  }
  return true
}

router.beforeEach(redirectLegacyCommandReference)
router.beforeEach(enforceRouteFeature)

export default router
