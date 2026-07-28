import type { TaskWindowContext } from '../../../desktop_electron/src/shared/bridge'

const TASK_CENTER_OPEN_EVENT = 'netconsole:task-center-open'

export type TaskCenterOpenContext = TaskWindowContext

export function requestTaskCenterOpen(context: TaskCenterOpenContext = {}): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<TaskCenterOpenContext>(TASK_CENTER_OPEN_EVENT, {
    detail: { ...context },
  }))
}

export function onTaskCenterOpenRequested(
  listener: (context: TaskCenterOpenContext) => void,
): () => void {
  if (typeof window === 'undefined') return () => undefined
  const handler = (event: Event) => {
    const detail = event instanceof CustomEvent && event.detail && typeof event.detail === 'object'
      ? event.detail as TaskCenterOpenContext
      : {}
    listener({ ...detail })
  }
  window.addEventListener(TASK_CENTER_OPEN_EVENT, handler)
  return () => window.removeEventListener(TASK_CENTER_OPEN_EVENT, handler)
}
