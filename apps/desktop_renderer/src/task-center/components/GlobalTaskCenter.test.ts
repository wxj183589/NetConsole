import { describe, expect, it } from 'vitest'

import source from './GlobalTaskCenter.vue?raw'
import mainSource from '../../main.ts?raw'
import confirmDialogSource from '../../components/feedback/NcConfirmDialog.vue?raw'

describe('GlobalTaskCenter', () => {
  it('keeps one global task connection and three non-blocking task surfaces', () => {
    expect(source).toContain("const GLOBAL_POLLING_CONSUMER = 'global-task-center'")
    expect(source).toContain('data-testid="global-task-indicator"')
    expect(source).toContain('data-testid="task-center-drawer"')
    expect(source).toContain('data-testid="active-task-floating-card"')
    expect(source).toContain('进入完整任务中心')
    expect(source).toContain('floatingDismissedSignature')
  })

  it('deduplicates terminal notifications and separates foreground from native delivery', () => {
    expect(source).toContain('previous === key')
    expect(source).toContain('const TERMINAL_NOTIFICATION_BUFFER_MS = 800')
    expect(source).toContain('BATCH_NOTIFICATION_TASK_TYPES')
    expect(source).toContain('batchNotificationSummary')
    expect(source).toContain("document.visibilityState === 'visible' && document.hasFocus()")
    expect(source).toContain("runtime.hostType !== 'electron'")
    expect(source).toContain('showTaskNotification')
    expect(source).toContain("duration: kind === 'success' ? 5000 : 0")
    expect(source).toContain("customClass: 'nc-task-notification'")
    expect(source).toContain('appendTo: document.body')
    expect(source).toContain("}, '查看详情')")
  })

  it('updates the tray with bounded aggregate task status instead of task payloads', () => {
    expect(source).toContain('setTaskTrayStatus({ active, failed, warning })')
    expect(source).not.toContain('ipcRenderer')
  })

  it('uses the shared centered confirmation dialog for cleanup without changing the drawer', () => {
    expect(source).toContain('const { confirm } = useConfirm()')
    expect(source).toContain("title: t('job_center.cleanup.dialog_title', '清理任务记录')")
    expect(source).toContain('highlight: `${preview.matched} 个`')
    expect(source).toContain("width: 'min(468px, calc(100vw - 32px))'")
    expect(source).toContain("type: 'DANGER'")
    expect(source).toContain("confirmLoadingText: t('job_center.cleanup.loading', '正在清理…')")
    expect(source).toContain('onConfirm: async () =>')
    expect(source).toContain('cleanupBusy.value = true')
    expect(source).toContain(':loading="cleanupBusy"')
    expect(source).toContain(':disabled="cleanupBusy"')
    expect(source).toContain('await store.cleanupHistory(cleanupType)')
    expect(source).toContain("'job_center.cleanup.done'")
    expect(source).toContain("String(result.dismissed)")
    expect(source).toContain('PRODUCTION_WRITE_CONFIRMATION_REQUIRED')
    expect(source).toContain('void store.refresh()')
    expect(source).not.toContain('window.confirm')
    expect(source).not.toContain('window.alert')
    expect(source).not.toContain('drawerVisible.value = false\n    await confirm')
  })

  it('loads only the required programmatic Element Plus styles and bounds shared dialogs', () => {
    expect(mainSource).toContain("import 'element-plus/theme-chalk/el-message.css'")
    expect(mainSource).toContain("import 'element-plus/theme-chalk/el-message-box.css'")
    expect(mainSource).toContain("import 'element-plus/theme-chalk/el-notification.css'")
    expect(mainSource).not.toContain("import 'element-plus/dist/index.css'")
    expect(confirmDialogSource).toContain('nc-confirm-dialog')
    expect(confirmDialogSource).toContain("request.value?.options.width || 'min(620px, calc(100vw - 32px))'")
    expect(confirmDialogSource).not.toContain('width: 100vw')
  })

  it('opens reusable details in place and reserves route navigation for the full task center', () => {
    expect(source).toContain("import TaskDetailDrawer from './TaskDetailDrawer.vue'")
    expect(source).toContain('openTaskDetail(task.id)')
    expect(source).toContain("openTaskDetail(primaryActiveTask.id, 'floating')")
    expect(source).toContain("await workspace.openOrActivateRoute('/tasks')")
    expect(source).not.toContain('openFullTaskCenter')
    expect(source).not.toContain("openOrActivateRoute(`/tasks")
  })

  it('formats REST and WebSocket task timestamps through the shared business-time utility', () => {
    expect(source).toContain("import { formatTaskDateTime, parseUtcDateTime, taskDateTimeTitle } from '../../utils/dateTime'")
    expect(source).toContain('formatTaskDateTime(task.updated_time || task.created_time)')
    expect(source).toContain('function taskTimestamp(task: TaskItem): number')
    expect(source).not.toContain('{{ taskStatusLabel(task.status) }} · {{ task.updated_time || task.created_time }}')
  })
})
