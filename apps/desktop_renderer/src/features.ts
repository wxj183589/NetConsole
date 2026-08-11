import { reactive, ref } from 'vue'

import { getRendererFeatureStates } from './api/features'

interface FeatureState {
  visible: boolean
  enabled: boolean
}

const states = reactive<Record<string, FeatureState>>({})
const loaded = ref(false)
let pending: Promise<void> | null = null

export async function loadRendererFeatures(force = false): Promise<void> {
  if (loaded.value && !force) return
  if (pending && !force) return pending
  pending = getRendererFeatureStates()
    .then((items) => {
      for (const key of Object.keys(states)) delete states[key]
      for (const item of items) states[item.feature_id] = { visible: item.visible, enabled: item.enabled }
      loaded.value = true
    })
    .finally(() => {
      pending = null
    })
  return pending
}

export function isFeatureVisible(featureId: string): boolean {
  if (!loaded.value) return !featureId.startsWith('internal.')
  return states[featureId]?.visible === true
}

export function isFeatureEnabled(featureId: string): boolean {
  if (!loaded.value) return !featureId.startsWith('internal.')
  return states[featureId]?.enabled === true
}

export function setRendererFeaturesForTest(values: Record<string, FeatureState>): void {
  for (const key of Object.keys(states)) delete states[key]
  Object.assign(states, values)
  loaded.value = true
}

export function resetRendererFeaturesForTest(): void {
  for (const key of Object.keys(states)) delete states[key]
  loaded.value = false
  pending = null
}
