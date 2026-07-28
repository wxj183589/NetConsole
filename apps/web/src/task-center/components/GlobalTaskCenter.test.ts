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
    expect(source).toContain("document.visibilityState === 'visible' && document.hasFocus()")
    expect(source).toContain("runtime.hostType !== 'electron'")
    expect(source).toContain('showTaskNotification')
    expect(source).toContain("duration: kind === 'success' ? 5000 : 0")
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
    expect(source).toContain('await store.cleanupHistory(cleanupType)')
    expect(source).toContain("'job_center.cleanup.done'")
    expect(source).toContain("String(result.dismissed)")
    expect(source).not.toContain('window.confirm')
    expect(source).not.toContain('window.alert')
    expect(source).not.toContain('drawerVisible.value = false\n    await confirm')
  })

  it('loads the programmatic MessageBox base style and bounds shared confirmation dialogs', () => {
    expect(mainSource).toContain("import 'element-plus/theme-chalk/el-message-box.css'")
    expect(confirmDialogSource).toContain('nc-confirm-dialog')
    expect(confirmDialogSource).toContain("request.value?.options.width || 'min(620px, calc(100vw - 32px))'")
    expect(confirmDialogSource).not.toContain('width: 100vw')
  })
})
