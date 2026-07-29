import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import {
  userSelectedExportDefinitions,
  type UserSelectedExportAction,
} from './exportActionRegistry'

const SRC_ROOT = dirname(dirname(fileURLToPath(import.meta.url)))

interface CoordinatedExportEntry {
  file: string
  actions: UserSelectedExportAction[]
  apiCalls: string[]
}

const COORDINATED_EXPORTS: CoordinatedExportEntry[] = [
  entry('views/devices/DeviceManagementView.vue',
    ['devices.csv', 'devices.template', 'devices.securecrt', 'devices.diagnostics'],
    ['startDeviceCsvExport', 'startDeviceTemplateExport', 'startSecureCrtExport', 'startSecureCrtExportWithTemplate', 'startDeviceDiagnosticDownload']),
  entry('views/ac-management/AcManagementView.vue', ['ac.fit_ap_resources'], ['startAcFitApResourceExport']),
  entry('views/ac-management/AcWebParityView.vue', ['ac.extensions'], ['exportAcExtensions']),
  entry('views/rail-transit/MeshAnalysisView.vue',
    ['rail.mesh_report', 'rail.mesh_link_details'],
    ['exportMeshAnalysisReport', 'exportMeshLinkDetails']),
  entry('views/rail-transit/TracksideApBusinessView.vue', ['rail.trackside_business'], ['startTracksideApBusinessExport']),
  entry('components/rail-transit/base-data/TracksideApPlanningTab.vue',
    ['rail.trackside_plan_template', 'rail.trackside_plan_current'],
    ['exportTracksideApPlan']),
  entry('views/rail-transit/RailTransitBaseDataView.vue',
    ['rail.trackside_base_template', 'rail.trackside_base_current', 'rail.trackside_rename_commands'],
    ['exportTracksideApBase', 'exportTracksideApRenameCommands']),
  entry('views/rail-transit/OnlineMrAnalysisView.vue', ['rail.online_mr_report'], ['exportOnlineMrReport']),
  entry('views/rail-transit/VehicleMrOnlineView.vue',
    ['rail.vehicle_history', 'rail.vehicle_mapping_template'],
    ['exportVehicleMrHistory', 'exportVehicleMrMappingTemplate']),
  entry('views/rail-transit/CarNetworkPointTableDialog.vue',
    ['rail.car_network_points_csv', 'rail.car_network_points_xlsx'],
    ['exportCarNetworkPointTable']),
  entry('views/config-collection/ConfigCollectionView.vue',
    ['config.diff', 'config.snapshots'],
    ['submitConfigDiffExport', 'submitConfigSnapshotsExport']),
  entry('views/command-reference/CommandReferenceView.vue',
    ['command-reference.markdown'],
    ['startCommandReferenceExport']),
  entry('views/system/SystemMaintenanceView.vue',
    ['system.logs', 'system.open_source_txt', 'system.open_source_xlsx'],
    ['startLogExport', 'startOpenSourceExport']),
  entry('components/network-tools/NetworkToolboxPanel.vue',
    ['network.toolbox_csv', 'network.toolbox_xlsx'],
    ['exportNetworkTask']),
  entry('components/network-tools/WirelessScanPanel.vue',
    ['network.wireless_scan_csv', 'network.wireless_scan_xlsx'],
    ['exportWirelessScan']),
]

const CUSTOM_PRESELECTED_EXPORTS = [
  {
    file: 'views/ac-management/AcOmniPeekExportDialog.vue',
    apiCall: 'startAcOmniPeekExport',
    selector: 'chooseOutputFile',
    reason: 'OmniPeek 名称表保留既有目录与文件选择、授权目标绑定和完整性校验。',
  },
  {
    file: 'views/settings/SiteStoragePanel.vue',
    apiCall: 'exportSite',
    selector: 'selectSiteExportDestination',
    reason: '局点包使用 Main 的专用受控目标选择和迁移包契约。',
  },
] as const

const IMPORT_ENTRIES = [
  ['views/devices/DeviceManagementView.vue', 'onImportFileChange'],
  ['views/ac-management/AcWebParityView.vue', 'chooseFile'],
  ['views/rail-transit/MeshAnalysisView.vue', 'chooseFiles'],
  ['views/rail-transit/RailTransitBaseDataView.vue', 'handleStationTemplateFile'],
  ['views/rail-transit/RailTransitBaseDataView.vue', 'handleFile'],
  ['views/rail-transit/RailTransitBaseDataView.vue', 'handleTracksideApFile'],
  ['views/rail-transit/VehicleMrOnlineView.vue', 'chooseMappingImport'],
  ['views/rail-transit/CarNetworkPointTableDialog.vue', 'chooseImport'],
  ['components/rail-transit/base-data/TracksideApPlanningTab.vue', 'chooseImport'],
] as const

const MANAGED_DOWNLOAD_EXCEPTIONS = [
  'views/file-management/FileManagementView.vue',
] as const

const DIRECT_SAVE_PATH_ENTRIES = [
  'composables/useUserSelectedExport.ts',
  'components/DesktopRuntimeStatus.vue',
  'platform/electron-adapter.ts',
  'views/ac-management/AcOmniPeekExportDialog.vue',
] as const

const LOCAL_PATH_SELECTION_ENTRIES = [
  {
    file: 'views/tools/components/ExternalToolEditorDialog.vue',
    selectors: [
      'selectExternalToolExecutable',
      'selectExternalToolWorkingDirectory',
      'selectExternalToolIcon',
    ],
    reason: '工具集只接受 Electron Main 选择并复验的 EXE、工作目录和短期图标选择 ID。',
  },
] as const

describe('visible import/export entry audit', () => {
  it('requires every registered task export to select and bind a destination before submission', () => {
    const registeredActions = new Set(Object.keys(userSelectedExportDefinitions))
    const auditedActions = new Set<UserSelectedExportAction>()
    const auditedApiCalls = new Set<string>()

    for (const item of COORDINATED_EXPORTS) {
      const source = readSource(item.file)
      expect(source, item.file).toContain('submitExportAfterDestinationSelected')
      for (const action of item.actions) {
        expect(source, `${item.file}: ${action}`).toContain(`'${action}'`)
        auditedActions.add(action)
      }
      for (const apiCall of item.apiCalls) {
        expect(source, `${item.file}: ${apiCall}`).toMatch(new RegExp(`\\b${apiCall}\\b`))
        auditedApiCalls.add(apiCall)
      }
    }

    expect(auditedActions).toEqual(registeredActions)
    expect(auditedApiCalls.size).toBeGreaterThan(20)
  })

  it('keeps the two reviewed custom preselection flows explicit and documented', () => {
    for (const item of CUSTOM_PRESELECTED_EXPORTS) {
      const source = readSource(item.file)
      expect(item.reason.length).toBeGreaterThan(20)
      expect(source).toMatch(new RegExp(`\\b${item.selector}\\s*\\(`))
      expect(source).toMatch(new RegExp(`\\b${item.apiCall}\\s*\\(`))
      expect(source.indexOf(item.selector)).toBeLessThan(source.lastIndexOf(item.apiCall))
    }
  })

  it('keeps every file input user-triggered and clears its value for same-name reselection', () => {
    for (const [file, handler] of IMPORT_ENTRIES) {
      const source = readSource(file)
      const body = functionBody(source, handler)
      expect(source, file).toContain('type="file"')
      expect(body, `${file}: ${handler}`).toMatch(/\.value\s*=\s*''/)
      expect(body, `${file}: ${handler}`).toMatch(/files\?\.\[0\]|Array\.from\(input\.files/)
    }
    const siteStorage = readSource('views/settings/SiteStoragePanel.vue')
    expect(siteStorage).toContain('selectSitePackage()')
    expect(siteStorage.indexOf('if (selected.cancelled')).toBeLessThan(siteStorage.indexOf('await importSite('))
  })

  it('forbids renderer anchor downloads and test/user default export paths in production sources', () => {
    const productionFiles = sourceFiles(SRC_ROOT)
      .filter((file) => !file.endsWith('.test.ts'))
    for (const file of productionFiles) {
      const source = readFileSync(file, 'utf8')
      const name = relative(SRC_ROOT, file)
      if (name !== join('platform', 'browser-adapter.ts')) {
        expect(source, name).not.toContain("document.createElement('a')")
        expect(source, name).not.toContain('document.createElement("a")')
      }
      expect(source, name).not.toMatch(/NetConsole(?:ExportTest|TestData|BuildLogs)/)
      expect(source, name).not.toMatch(/(?:^|[\\/])Downloads(?:[\\/]|$)/)
    }
  })

  it('limits direct Save As and private export state to the shared or reviewed flows', () => {
    const directSavePathEntries: string[] = []
    for (const file of sourceFiles(SRC_ROOT).filter((item) => !item.endsWith('.test.ts'))) {
      const source = readFileSync(file, 'utf8')
      const name = relative(SRC_ROOT, file).replaceAll('\\', '/')
      if (/\.chooseSavePath\s*\(/.test(source)) directSavePathEntries.push(name)
      expect(source, name).not.toMatch(/\b(?:pendingExports|autoSavedTaskIds)\b/)
    }
    expect(directSavePathEntries.sort()).toEqual([...DIRECT_SAVE_PATH_ENTRIES].sort())
  })

  it('limits managed-directory download exceptions to the reviewed device-file workflow', () => {
    expect(MANAGED_DOWNLOAD_EXCEPTIONS).toEqual([
      'views/file-management/FileManagementView.vue',
    ])
    const source = readSource(MANAGED_DOWNLOAD_EXCEPTIONS[0])
    expect(source).toContain('startRemoteFileDownload')
    expect(source).toContain('local_path')
  })

  it('keeps non-import local resource paths behind reviewed Main selectors', () => {
    for (const item of LOCAL_PATH_SELECTION_ENTRIES) {
      const source = readSource(item.file)
      expect(item.reason.length).toBeGreaterThan(20)
      expect(source).toContain('result.cancelled')
      for (const selector of item.selectors) {
        expect(source, `${item.file}: ${selector}`).toMatch(new RegExp(`\\b${selector}\\s*\\(`))
      }
    }
  })
})

function entry(
  file: string,
  actions: UserSelectedExportAction[],
  apiCalls: string[],
): CoordinatedExportEntry {
  return { file, actions, apiCalls }
}

function readSource(file: string): string {
  return readFileSync(join(SRC_ROOT, ...file.split('/')), 'utf8')
}

function functionBody(source: string, name: string): string {
  const start = source.search(new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`))
  if (start < 0) return ''
  const next = source.indexOf('\nfunction ', start + 1)
  const nextAsync = source.indexOf('\nasync function ', start + 1)
  const boundaries = [next, nextAsync].filter((value) => value > start)
  return source.slice(start, boundaries.length ? Math.min(...boundaries) : source.length)
}

function sourceFiles(root: string): string[] {
  const files: string[] = []
  for (const name of readdirSync(root)) {
    const path = join(root, name)
    if (statSync(path).isDirectory()) files.push(...sourceFiles(path))
    else if (/\.(?:ts|vue)$/.test(name)) files.push(path)
  }
  return files
}
