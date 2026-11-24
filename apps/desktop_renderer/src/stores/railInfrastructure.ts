import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Infrastructure, InfrastructureDevice } from '../api/railInfrastructure'

// UI state only; facts continue to come from the shared engineering query.
export const useRailInfrastructureStore = defineStore('rail-transit-infrastructure', () => {
  const snapshot = ref<Infrastructure>()
  const loading = ref(false), error = ref(''), search = ref(''), selectedUid = ref('')
  const showUnassociated = ref(false), selectedDevice = ref<InfrastructureDevice>(), retry = ref(0)
  return { snapshot, loading, error, search, selectedUid, showUnassociated, selectedDevice, retry }
})
