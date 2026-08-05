import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  getDeviceTerminalPreflight,
  getExternalTerminalSettings,
  issueExternalTerminalConfirmation,
  launchExternalTerminals,
} from '../api/deviceManagement'
import {
  getAcExternalTerminalOptions,
  openAcFitApExternalTerminal,
} from '../api/acWebParity'
import type {
  DeviceExternalTerminalPreflightItem,
  DeviceExternalTerminalSettings,
} from '../types/deviceManagement'
import type {
  AcExternalTerminalAction,
  AcTerminalType,
} from '../types/acWebParity'

export type DeviceTerminalType = 'securecrt' | 'putty' | 'xshell'

export interface DeviceTerminalPreflightResult {
  terminalType: DeviceTerminalType
  launchableDevices: string[]
  skippedDevices: DeviceExternalTerminalPreflightItem[]
}

export interface DeviceTerminalLaunchResult {
  success: number
  failed: number
  failures: string[]
}

export interface FitApTerminalTarget {
  acId: string
  apId: string
}

export function useExternalTerminalLauncher() {
  const router = useRouter()
  const busy = ref(false)
  const fitApTerminalVisible = ref(false)
  const fitApTerminalType = ref<AcTerminalType>('securecrt')
  const fitApTerminalOptions = ref<Array<{ terminal_type: AcTerminalType; label: string }>>([])
  const fitApTarget = ref<FitApTerminalTarget | null>(null)

  async function preflightDeviceTerminalTargets(
    deviceUuids: string[],
    preferredTerminalType?: DeviceTerminalType,
    loadedSettings?: DeviceExternalTerminalSettings,
  ): Promise<DeviceTerminalPreflightResult | null> {
    const unique = uniqueValues(deviceUuids)
    if (!unique.length || busy.value) return null
    busy.value = true
    try {
      const settings = loadedSettings || await getExternalTerminalSettings()
      const terminalType = chooseTerminalType(settings, preferredTerminalType)
      const preflight = await getDeviceTerminalPreflight(unique, terminalType)
      return {
        terminalType,
        launchableDevices: preflight.launchable_devices,
        skippedDevices: preflight.skipped_devices,
      }
    } finally {
      busy.value = false
    }
  }

  async function launchDeviceTerminalTargets(
    deviceUuids: string[],
    terminalType: DeviceTerminalType,
    confirmMany?: () => Promise<boolean>,
  ): Promise<DeviceTerminalLaunchResult | null> {
    const unique = uniqueValues(deviceUuids)
    if (!unique.length || busy.value) return null
    busy.value = true
    try {
      let confirmationToken = ''
      if (unique.length > 20) {
        if (confirmMany && !await confirmMany()) return null
        confirmationToken = (
          await issueExternalTerminalConfirmation(unique, terminalType)
        ).confirmation_token
      }
      return await launchExternalTerminals(unique, terminalType, confirmationToken)
    } finally {
      busy.value = false
    }
  }

  async function requestFitApTerminal(target: FitApTerminalTarget): Promise<AcExternalTerminalAction | null> {
    const normalized = normalizeFitApTarget(target)
    if (!normalized || busy.value) return null
    busy.value = true
    fitApTarget.value = normalized
    try {
      const result = await getAcExternalTerminalOptions()
      if (!result.options.length) {
        await promptExternalTerminalSettings()
        return null
      }
      fitApTerminalOptions.value = result.options
      fitApTerminalType.value = result.default_terminal_type || result.options[0].terminal_type
      if (result.options.length === 1) {
        return await launchFitApTerminalTarget(normalized, fitApTerminalType.value)
      }
      fitApTerminalVisible.value = true
      return null
    } catch (cause) {
      ElMessage.error(safeTerminalError(cause, '打开外部终端失败'))
      return null
    } finally {
      busy.value = false
    }
  }

  async function launchSelectedFitApTerminal(): Promise<AcExternalTerminalAction | null> {
    const target = fitApTarget.value
    if (!target || busy.value) return null
    busy.value = true
    try {
      return await launchFitApTerminalTarget(target, fitApTerminalType.value)
    } catch (cause) {
      ElMessage.error(safeTerminalError(cause, '打开外部终端失败'))
      return null
    } finally {
      busy.value = false
    }
  }

  async function launchFitApTerminalTarget(
    target: FitApTerminalTarget,
    terminalType: AcTerminalType,
  ): Promise<AcExternalTerminalAction | null> {
    try {
      const result = await openAcFitApExternalTerminal(target.apId, target.acId, terminalType)
      fitApTerminalVisible.value = false
      ElMessage.success(result.message)
      return result
    } catch (cause) {
      if (terminalErrorCode(cause) === 'TERMINAL_NOT_CONFIGURED') {
        await promptExternalTerminalSettings()
        return null
      }
      throw cause
    }
  }

  async function promptExternalTerminalSettings(): Promise<void> {
    try {
      await ElMessageBox.confirm(
        '尚未配置可用的外部终端程序。请先到工具集配置 SecureCRT、PuTTY 或 Xshell。',
        '外部终端未配置',
        { confirmButtonText: '打开工具集', cancelButtonText: '取消', type: 'warning' },
      )
      await router.push({ name: 'tool-collection', query: { section: 'external-terminal' } })
    } catch {
      // 用户取消。
    }
  }

  function showPreflightSkipped(skippedDevices: DeviceExternalTerminalPreflightItem[]): void {
    const reason = skippedDevices.find((item) => item.reason)?.reason || '没有可启动的外部终端目标'
    ElMessage.warning(reason)
  }

  function showLaunchResult(result: DeviceTerminalLaunchResult): void {
    if (result.failed) {
      ElMessage.warning(`外部终端启动完成：成功 ${result.success}，失败 ${result.failed}。${result.failures.slice(0, 3).join('；')}`)
    } else {
      ElMessage.success(`已启动 ${result.success} 个外部终端`)
    }
  }

  return {
    busy,
    fitApTerminalVisible,
    fitApTerminalType,
    fitApTerminalOptions,
    preflightDeviceTerminalTargets,
    launchDeviceTerminalTargets,
    requestFitApTerminal,
    launchSelectedFitApTerminal,
    showPreflightSkipped,
    showLaunchResult,
  }
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))]
}

function normalizeFitApTarget(target: FitApTerminalTarget): FitApTerminalTarget | null {
  const acId = String(target.acId || '').trim()
  const apId = String(target.apId || '').trim()
  return acId && apId ? { acId, apId } : null
}

function chooseTerminalType(
  settings: DeviceExternalTerminalSettings,
  preferred?: DeviceTerminalType,
): DeviceTerminalType {
  const configured = (['securecrt', 'xshell', 'putty'] as const).filter(
    (type) => Boolean(settings[`${type}_path`]),
  )
  if (!configured.length) throw new Error('尚未配置外部终端程序路径')
  if (preferred && configured.includes(preferred)) return preferred
  if (configured.includes(settings.terminal_type)) return settings.terminal_type
  return configured[0]
}

function terminalErrorCode(cause: unknown): string {
  if (!cause || typeof cause !== 'object' || !('code' in cause)) return ''
  return String(cause.code || '')
}

function safeTerminalError(cause: unknown, fallback: string): string {
  const message = cause instanceof Error ? cause.message : fallback
  return message
    .replace(/(password|token)\s*[:=]\s*[^,;\s]+/gi, '$1=***')
    .replace(/[A-Za-z]:\\[^\r\n]+/g, '<本机路径>')
}
