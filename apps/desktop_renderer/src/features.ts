import { reactive, ref } from 'vue'

import { getRendererFeatureStates } from './api/features'

interface FeatureState {
  visible: boolean
  enabled: boolean
}

const states = reactive<Record<string, FeatureState>>({})
const loaded = ref(false)
let generation = 0
let pending: { generation: number, promise: Promise<void> } | null = null

export async function loadRendererFeatures(force = false): Promise<void> {
  if (loaded.value && !force) return
  if (pending && !force) return pending.promise
  if (force) loaded.value = false
  const requestGeneration = ++generation
  const request = getRendererFeatureStates()
    .then((items) => {
      if (requestGeneration !== generation) return
      for (const key of Object.keys(states)) delete states[key]
      for (const item of items) states[item.feature_id] = { visible: item.visible, enabled: item.enabled }
      loaded.value = true
    })
    .catch((cause: unknown) => {
      if (requestGeneration === generation) throw cause
    })
    .finally(() => {
      if (pending?.generation === requestGeneration) pending = null
    })
  pending = { generation: requestGeneration, promise: request }
  return request
}

export function isFeatureVisible(featureId: string): boolean {
  if (!loaded.value) return false
  return states[featureId]?.visible === true
}

export function isFeatureEnabled(featureId: string): boolean {
  if (!loaded.value) return false
  return states[featureId]?.enabled === true
}

export function setRendererFeaturesForTest(values: Record<string, FeatureState>): void {
  generation += 1
  pending = null
  for (const key of Object.keys(states)) delete states[key]
  Object.assign(states, values)
  loaded.value = true
}

export function resetRendererFeaturesForTest(): void {
  generation += 1
  for (const key of Object.keys(states)) delete states[key]
  loaded.value = false
  pending = null
}
