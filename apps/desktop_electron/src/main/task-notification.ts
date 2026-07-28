import type { NativeActionResult, TaskNotificationPayload } from '../shared/bridge'

export interface TaskNotificationLike {
  on(event: 'click', listener: () => void): void
  show(): void
}

export interface TaskNotificationControllerOptions {
  createNotification(payload: TaskNotificationPayload): TaskNotificationLike
  activateTask(taskId: string): Promise<void> | void
  isApplicationFocused?(): boolean
  logger(event: string): void
}

const MAX_DEDUPLICATION_KEYS = 256

export class TaskNotificationController {
  private readonly shownEventIds = new Set<string>()

  constructor(private readonly options: TaskNotificationControllerOptions) {}

  show(payload: TaskNotificationPayload): NativeActionResult {
    if (this.shownEventIds.has(payload.eventId)) {
      this.options.logger('ELECTRON_TASK_NOTIFICATION_DUPLICATE_SKIPPED')
      return { success: true }
    }
    if (this.options.isApplicationFocused?.()) {
      this.remember(payload.eventId)
      this.options.logger('ELECTRON_TASK_NOTIFICATION_FOREGROUND_SKIPPED')
      return { success: true }
    }
    try {
      const notification = this.options.createNotification(payload)
      notification.on('click', () => {
        this.options.logger('ELECTRON_TASK_NOTIFICATION_CLICKED')
        void this.options.activateTask(payload.taskId)
      })
      notification.show()
      this.remember(payload.eventId)
      this.options.logger('ELECTRON_TASK_NOTIFICATION_SHOWN')
      return { success: true }
    } catch {
      this.options.logger('ELECTRON_TASK_NOTIFICATION_FAILED')
      return { success: false, error: '系统通知不可用' }
    }
  }

  private remember(eventId: string): void {
    this.shownEventIds.add(eventId)
    while (this.shownEventIds.size > MAX_DEDUPLICATION_KEYS) {
      const oldest = this.shownEventIds.values().next().value
      if (typeof oldest !== 'string') break
      this.shownEventIds.delete(oldest)
    }
  }
}
