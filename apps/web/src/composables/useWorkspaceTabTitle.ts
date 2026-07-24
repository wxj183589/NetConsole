import { onMounted, watch, type MaybeRefOrGetter, toValue } from 'vue'

import { useWorkspaceStore } from '../stores/workspace'

export function useWorkspaceTabTitle(title: MaybeRefOrGetter<string>): void {
  const workspace = useWorkspaceStore()
  const update = () => workspace.updateTabTitle(toValue(title))
  onMounted(update)
  watch(() => toValue(title), update)
}
