import { reactive } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { ConfirmOptions } from './confirm.types'

export type ConfirmResult = 'confirm' | 'secondary' | 'cancel'

interface ConfirmRequest extends Required<Pick<ConfirmOptions, 'title' | 'message'>> {
  options: ConfirmOptions
  resolve: (value: ConfirmResult) => void
}

export const confirmState = reactive<{ request: ConfirmRequest | null; providerReady: boolean }>({ request: null, providerReady: false })

export function useConfirm() {
  function confirm(options: ConfirmOptions): Promise<boolean> {
    if (!confirmState.providerReady) {
      const action = options.confirmationText
        ? ElMessageBox.prompt(options.message, options.title, {
            type: 'error',
            confirmButtonText: options.confirmText || '确认操作',
            cancelButtonText: options.cancelText || '取消',
            confirmButtonType: 'danger',
            inputPlaceholder: options.confirmationPlaceholder || options.confirmationText,
            inputValidator: (value) => value === options.confirmationText || '输入内容与完整名称不一致',
          })
        : ElMessageBox.confirm(options.message, options.title, {
            type: options.type === 'DANGER' || options.type === 'DESTRUCTIVE' ? 'error' : 'warning',
            confirmButtonText: options.confirmText || '确认操作',
            cancelButtonText: options.cancelText || '取消',
            confirmButtonType: options.type === 'DANGER' || options.type === 'DESTRUCTIVE' ? 'danger' : 'primary',
            customStyle: options.width ? { width: options.width, maxWidth: 'calc(100vw - 32px)' } : undefined,
          })
      return action.then(async () => {
        await options.onConfirm?.()
        return true
      }).catch(() => false)
    }
    if (confirmState.request) confirmState.request.resolve('cancel')
    return new Promise<boolean>((resolve) => {
      confirmState.request = {
        title: options.title,
        message: options.message,
        options,
        resolve: (value) => resolve(value === 'confirm'),
      }
    })
  }

  function confirmChoice(options: ConfirmOptions): Promise<ConfirmResult> {
    if (!confirmState.providerReady) {
      return ElMessageBox.confirm(options.message, options.title, {
        type: options.type === 'SECURITY' ? 'warning' : 'info',
        confirmButtonText: options.confirmText || '确认操作',
        cancelButtonText: options.cancelText || '取消',
      }).then(() => 'confirm' as ConfirmResult).catch(() => 'cancel' as ConfirmResult)
    }
    if (confirmState.request) confirmState.request.resolve('cancel')
    return new Promise<ConfirmResult>((resolve) => {
      confirmState.request = { title: options.title, message: options.message, options, resolve }
    })
  }

  return { confirm, confirmChoice }
}

export function resolveConfirm(value: ConfirmResult): void {
  const request = confirmState.request
  if (!request) return
  confirmState.request = null
  request.resolve(value)
}
