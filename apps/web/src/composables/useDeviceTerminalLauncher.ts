import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  getDeviceTerminalPreflight,
  getExternalTerminalSettings,
  issueExternalTerminalConfirmation,
  launchExternalTerminals,
} from '../api/deviceManagement'
import type {
  DeviceExternalTerminalPreflightItem,
  DeviceExternalTerminalSettings,
} from '../types/deviceManagement'

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

export function useDeviceTerminalLauncher() {
  const busy = ref(false)

  async function preflightDeviceTerminalTargets(
    deviceUuids: string[],
    preferredTerminalType?: DeviceTerminalType,
    loadedSettings?: DeviceExternalTerminalSettings,
  ): Promise<DeviceTerminalPreflightResult | null> {
    const unique = [...new Set(deviceUuids.map((value) => String(value || '').trim()).filter(Boolean))]
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
    const unique = [...new Set(deviceUuids.map((value) => String(value || '').trim()).filter(Boolean))]
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
    preflightDeviceTerminalTargets,
    launchDeviceTerminalTargets,
    showPreflightSkipped,
    showLaunchResult,
  }
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
