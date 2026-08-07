import { describe, expect, it, vi } from 'vitest'

import { wpsAirScriptSource, type WpsAirScriptKind } from './wpsAirScriptSources'
import type { WpsTracksideTargetCode } from '../../types/tracksideApBusiness'

const scripts: Array<{
  targetCode: WpsTracksideTargetCode
  kind: WpsAirScriptKind
  scriptVersion: string
  deploymentId: string
  documentId: string
  targetType: string
}> = [
  {
    targetCode: 'wps_standard_spreadsheet',
    kind: 'probe',
    scriptVersion: '2.4.0-standard',
    deploymentId: 'trackside-ap-standard-2.4.0',
    documentId: '549847228994',
    targetType: 'WPS_STANDARD_SPREADSHEET',
  },
  {
    targetCode: 'wps_standard_spreadsheet',
    kind: 'sync',
    scriptVersion: '2.4.0-standard',
    deploymentId: 'trackside-ap-standard-2.4.0',
    documentId: '549847228994',
    targetType: 'WPS_STANDARD_SPREADSHEET',
  },
  {
    targetCode: 'wps_smart_sheet',
    kind: 'probe',
    scriptVersion: '2.1.0-smart',
    deploymentId: 'trackside-ap-smart-2.1.0',
    documentId: 'cbRdGQdb10R9',
    targetType: 'WPS_SMART_SHEET',
  },
  {
    targetCode: 'wps_smart_sheet',
    kind: 'sync',
    scriptVersion: '2.1.0-smart',
    deploymentId: 'trackside-ap-smart-2.1.0',
    documentId: 'cbRdGQdb10R9',
    targetType: 'WPS_SMART_SHEET',
  },
]

function standardSpreadsheetRuntime(
  initialNames: string[],
  options: { hiddenFailureNames?: string[]; noMoveNames?: string[]; tabColorFailureNames?: string[] } = {},
) {
  const hiddenFailureNames = new Set(options.hiddenFailureNames || [])
  const noMoveNames = new Set(options.noMoveNames || [])
  const tabColorFailureNames = new Set(options.tabColorFailureNames || [])
  const moves: Array<{ sheet: string; before: string; after: string }> = []
  const inserts: Array<{ sheet: string; address: string }> = []
  const writes: Array<{ sheet: string; address: string; value: unknown }> = []
  const bindingRows = [
    ['document_id', '549847228994'],
    ['binding_id', 'wpsbind_v1_stable'],
    ['site_id', 'hzl10'],
    ['site_name', '杭州地铁10号线'],
    ['business_key', 'rail_transit.trackside_ap_business'],
    ['target_code', 'wps_standard_spreadsheet'],
    ['target_type', 'WPS_STANDARD_SPREADSHEET'],
    ['last_sync_at', ''],
    ['last_sync_revision', ''],
    ['last_target_batch_id', ''],
    ['last_prepend_target_batch_id', ''],
  ]
  const sheets: Array<Record<string, any>> = []
  let nextId = 1

  function makeSheet(name: string): Record<string, any> {
    let visible: unknown = true
    let tabColor: unknown = null
    const sheet: Record<string, any> = {
      Name: name,
      Id: `sheet-${nextId++}`,
      UsedRange: { ClearContents: vi.fn() },
      Range(address: string) {
        if (sheet.Name === '_NetConsoleSyncMeta' && address === 'A1:B30') {
          return { Value2: bindingRows }
        }
        const metaCell = sheet.Name === '_NetConsoleSyncMeta' ? address.match(/^([AB])(\d+)$/) : null
        if (metaCell) {
          const rowIndex = Number(metaCell[2]) - 1
          const columnIndex = metaCell[1] === 'A' ? 0 : 1
          while (bindingRows.length <= rowIndex) bindingRows.push(['', ''])
          return {
            get Value2() { return bindingRows[rowIndex][columnIndex] },
            set Value2(value: unknown) { bindingRows[rowIndex][columnIndex] = String(value ?? '') },
          }
        }
        let resizedAddress = address
        const range: Record<string, any> = {
          get Value2() { return [] },
          set Value2(value: unknown) { writes.push({ sheet: String(sheet.Name), address: resizedAddress, value }) },
          ClearContents: vi.fn(),
          EntireRow: { Insert: vi.fn(() => inserts.push({ sheet: String(sheet.Name), address })) },
          Resize(rows: number, columns: number) {
            resizedAddress = `${address}|${rows}x${columns}`
            return range
          },
        }
        return range
      },
      Move(before: Record<string, any> | null = null, after: Record<string, any> | null = null) {
        if (before && ('Before' in before || 'After' in before)) {
          throw new Error('AirScript 2.0 Move must use positional worksheet arguments')
        }
        moves.push({
          sheet: String(sheet.Name),
          before: String(before?.Name || ''),
          after: String(after?.Name || ''),
        })
        if (noMoveNames.has(String(sheet.Name))) return
        const currentIndex = sheets.indexOf(sheet)
        if (currentIndex >= 0) sheets.splice(currentIndex, 1)
        const anchor = before || after
        if (!anchor) throw new Error('Move requires Before or After')
        const anchorIndex = sheets.indexOf(anchor)
        if (anchorIndex < 0) throw new Error('Move anchor is outside the workbook')
        sheets.splice(anchorIndex + (after ? 1 : 0), 0, sheet)
      },
    }
    Object.defineProperty(sheet, 'Visible', {
      enumerable: true,
      get: () => visible,
      set: (value) => {
        if (hiddenFailureNames.has(String(sheet.Name))) throw new Error('visibility unsupported')
        visible = value
      },
    })
    sheet.Tab = {}
    Object.defineProperty(sheet.Tab, 'Color', {
      enumerable: true,
      get: () => tabColor,
      set: (value) => {
        if (tabColorFailureNames.has(String(sheet.Name))) throw new Error('tab color unsupported')
        tabColor = value
      },
    })
    return sheet
  }

  for (const name of initialNames) sheets.push(makeSheet(name))
  const worksheets = {
    get Count() { return sheets.length },
    Item(value: number | string) {
      if (typeof value === 'string') return sheets.find((sheet) => sheet.Name === value)
      return sheets[value - 1]
    },
    Add() {
      const sheet = makeSheet(`Sheet${nextId}`)
      sheets.unshift(sheet)
      return sheet
    },
  }
  return {
    application: { Worksheets: worksheets },
    inserts,
    moves,
    writes,
    names: () => sheets.map((sheet) => String(sheet.Name)),
  }
}

function executeStandardSpreadsheet(
  runtime: ReturnType<typeof standardSpreadsheetRuntime>,
  args: Record<string, unknown>,
) {
  const source = wpsAirScriptSource('wps_standard_spreadsheet', 'sync')
  const raw = new Function('Application', 'Context', source)(runtime.application, { argv: args })
  return JSON.parse(String(raw)) as Record<string, any>
}

function standardSyncArgs(sheetNames: string[]): Record<string, unknown> {
  return {
    operation: 'sync_trackside_ap_business',
    protocol_version: 2,
    target_type: 'WPS_STANDARD_SPREADSHEET',
    target_code: 'wps_standard_spreadsheet',
    document_id: '549847228994',
    binding_id: 'wpsbind_v1_stable',
    site_id: 'hzl10',
    site_name: '杭州地铁10号线',
    business_key: 'rail_transit.trackside_ap_business',
    parent_batch_id: 'batch-parent',
    target_batch_id: 'batch-target',
    snapshot_revision: 'revision-1',
    snapshot_sha256: 'sha-1',
    script_id: 'test',
    workbook: {
      sheets: sheetNames.map((sheetName, sheetOrder) => ({
        logical_sheet_key: `sheet-${sheetOrder}`,
        sheet_name: sheetName,
        sheet_order: sheetOrder,
        sync_mode: 'FULL_REPLACE',
        cells: [[sheetName]],
        row_count: 1,
        column_count: 1,
      })),
    },
  }
}

describe('WPS AirScript deployment sources', () => {
  it.each(scripts)(
    'returns $targetCode $kind with an explicit top-level result',
    ({ targetCode, kind, scriptVersion, deploymentId, documentId, targetType }) => {
      const source = wpsAirScriptSource(targetCode, kind)

      expect(source.trimEnd()).toMatch(/return main\(\);$/)
      expect(source).not.toMatch(/^\s*main\(\);\s*$/m)
      expect(source).toContain(`const SCRIPT_VERSION = "${scriptVersion}";`)
      expect(source).toContain(`const DEPLOYMENT_ID = "${deploymentId}";`)
      expect(source).toContain(`const DOCUMENT_ID = "${documentId}";`)
      expect(source).toContain(`const TARGET_TYPE = "${targetType}";`)
      expect(source).toContain(`const TARGET_CODE = "${targetCode}";`)
      expect(source).toContain('script_id')
    },
  )

  it.each(scripts.filter(({ kind }) => kind === 'probe'))(
    'keeps $targetCode connection probe read-only',
    ({ targetCode, kind }) => {
      const source = wpsAirScriptSource(targetCode, kind)

      expect(source).toContain('verification: "CONNECTION_PROBE_ONLY"')
      expect(source).not.toMatch(/\.Add\(|\.Insert\(|\.ClearContents\(|\.Value\s*=|CreateRecords|DeleteRecords|EnsureFields|DeleteWhere|AddRecords/)
      expect(source).not.toContain('sync_trackside_ap_business')
      if (targetCode === 'wps_standard_spreadsheet') {
        expect(source).toContain('Application.Worksheets')
        expect(source).toContain('LEGACY_BINDING_ID_MISMATCH')
        expect(source).toContain('WPS_BINDING_MIGRATION_REQUIRES_SYNC_SCRIPT')
        expect(source).not.toContain('ActiveWorkbook')
        expect(source).not.toContain('Application.Workbook')
      }
    },
  )

  it('makes the ordinary spreadsheet sync fail closed before business writes', () => {
    const source = wpsAirScriptSource('wps_standard_spreadsheet', 'sync')

    expect(source).toContain('_NetConsoleSyncMeta')
    expect(source).toContain('WPS_DOCUMENT_BINDING_MISMATCH')
    expect(source).toContain('LEGACY_BINDING_ID_MISMATCH')
    expect(source).toContain('migrate_legacy_binding')
    expect(source).toContain('function updateBindingIdOnly(newBindingId)')
    expect(source).toContain('runtime_write_probe')
    expect(source).toContain('sync_test_sheet')
    expect(source).toContain('sheet_order_probe')
    expect(source).toContain('sheet_tab_color_probe')
    expect(source).toContain('_NetConsoleSyncTest')
    expect(source).toContain('Application.Worksheets')
    expect(source).not.toContain('ActiveWorkbook')
    expect(source).not.toContain('Application.Workbook')
    expect(source).toContain('.Value2 = values')
    expect(source).toContain('EntireRow.Insert()')
    expect(source).toContain('sheetIsHidden')
    expect(source).toContain('core_capabilities: coreCapabilities')
    expect(source).toContain('optional_capabilities: optionalCapabilities')
    expect(source).toContain('full_replace_ready: fullReplaceReady')
    expect(source).toContain('prepend_snapshot_ready: prependSnapshotReady')
    expect(source).toContain('sheet.sync_mode === "PREPEND_SNAPSHOT"')
    expect(source).toContain('function toWpsColor(value)')
    expect(source).toContain('sheet_visibility')
    expect(source).toContain('sheet.Range("A1").Value2 = "OLD"')
    expect(source).toContain('sheet.Range("A1").Value2 = "NEW"')
    expect(source).toContain('sheet.Range("A2").Value2')
    expect(source).not.toContain('sheet.Visible === false')
    expect(source).not.toContain('Rows.Insert(1, values.length)')
    expect(source).not.toContain('.Value = values')
  })

  it('reorders dynamic business sheets after stable writes and keeps system sheets behind them', () => {
    const businessNames = ['动态第一页', '动态第二页', '动态第三页']
    const runtime = standardSpreadsheetRuntime(
      ['_NetConsoleSyncMeta', '动态第三页', '动态第一页', '_NetConsoleRuntimeProbe', '动态第二页', '_NetConsoleSyncTest'],
      { hiddenFailureNames: ['_NetConsoleSyncMeta'] },
    )

    const result = executeStandardSpreadsheet(runtime, standardSyncArgs(businessNames))

    expect(result).toMatchObject({
      success: true,
      status: 'SUCCESS_WITH_WARNINGS',
      sheet_order_verified: true,
      expected_sheet_order: businessNames,
      actual_sheet_order: businessNames,
      system_sheet_order_verified: true,
    })
    expect(runtime.names().slice(0, businessNames.length)).toEqual(businessNames)
    expect(runtime.names().slice(businessNames.length).every((name) => name.startsWith('_NetConsole'))).toBe(true)
    expect(result.format_warnings).toEqual(expect.arrayContaining([
      expect.objectContaining({ sheet_name: '_NetConsoleSyncMeta', feature: 'system_sheet_visibility' }),
    ]))
    expect(runtime.moves.some((move) => move.before === '动态第三页' && move.after === '')).toBe(true)
    expect(runtime.moves.some((move) => move.before === '' && move.after.startsWith('_NetConsole'))).toBe(true)
  })

  it('fails formal sync with the dedicated error when the business order cannot be corrected', () => {
    const businessNames = ['动态第一页', '动态第二页']
    const runtime = standardSpreadsheetRuntime(
      ['动态第二页', '动态第一页', '_NetConsoleSyncMeta'],
      { noMoveNames: ['动态第一页'] },
    )

    const result = executeStandardSpreadsheet(runtime, standardSyncArgs(businessNames))

    expect(result).toMatchObject({
      success: false,
      error_code: 'WPS_SHEET_ORDER_VERIFY_FAILED',
      expected_sheet_order: businessNames,
      actual_sheet_order: ['动态第二页', '动态第一页'],
    })
  })

  it('probes both AirScript 2.0 Move argument positions without touching business values', () => {
    const runtime = standardSpreadsheetRuntime([
      '保留业务页',
      '_NetConsoleSyncTest',
      '_NetConsoleRuntimeProbe',
      '_NetConsoleSyncMeta',
    ])

    const result = executeStandardSpreadsheet(runtime, {
      operation: 'sheet_order_probe',
      protocol_version: 2,
      target_type: 'WPS_STANDARD_SPREADSHEET',
      target_code: 'wps_standard_spreadsheet',
      site_id: 'hzl10',
      business_key: 'rail_transit.trackside_ap_business',
      binding_id: 'wpsbind_v1_stable',
      probe_id: 'probe-one',
      script_id: 'test',
    })

    expect(result).toMatchObject({
      success: true,
      sheet_order_verified: true,
      sheet_move_before_verified: true,
      sheet_move_after_verified: true,
      expected_sheet_order: ['_NetConsoleRuntimeProbe', '_NetConsoleSyncTest'],
      actual_sheet_order: ['_NetConsoleRuntimeProbe', '_NetConsoleSyncTest'],
    })
    expect(runtime.names()[0]).toBe('保留业务页')
    expect(runtime.moves).toEqual(expect.arrayContaining([
      expect.objectContaining({ sheet: '_NetConsoleSyncTest', before: '_NetConsoleRuntimeProbe', after: '' }),
      expect.objectContaining({ sheet: '_NetConsoleSyncTest', before: '', after: '_NetConsoleRuntimeProbe' }),
    ]))
  })

  it('probes Sheet.Tab.Color through RGB conversion on the sync test sheet', () => {
    const runtime = standardSpreadsheetRuntime([
      '保留业务页',
      '_NetConsoleSyncTest',
      '_NetConsoleSyncMeta',
    ])

    const result = executeStandardSpreadsheet(runtime, {
      operation: 'sheet_tab_color_probe',
      protocol_version: 2,
      target_type: 'WPS_STANDARD_SPREADSHEET',
      target_code: 'wps_standard_spreadsheet',
      site_id: 'hzl10',
      business_key: 'rail_transit.trackside_ap_business',
      binding_id: 'wpsbind_v1_stable',
      probe_id: 'tab-color-one',
      script_id: 'test',
    })

    expect(result).toMatchObject({
      success: true,
      status: 'SUCCESS',
      sheet_tab_color_verified: true,
      expected_tab_color: '#C6EFCE',
      expected_tab_color_value: 13561798,
      actual_tab_color: 13561798,
      probe_sheet: '_NetConsoleSyncTest',
    })
  })

  it('keeps formal data sync successful when an enabled tab color is unsupported', () => {
    const businessNames = ['AP上线情况概览', '轨旁AP业务']
    const runtime = standardSpreadsheetRuntime(
      ['轨旁AP业务', '_NetConsoleSyncMeta', 'AP上线情况概览'],
      { tabColorFailureNames: ['轨旁AP业务'] },
    )
    const args = standardSyncArgs(businessNames) as Record<string, any>
    args.sheet_tab_color_enabled = true
    args.workbook.sheets[0].tab_color = '#C6EFCE'
    args.workbook.sheets[1].tab_color = '#C6EFCE'

    const result = executeStandardSpreadsheet(runtime, args)

    expect(result).toMatchObject({
      success: true,
      status: 'SUCCESS_WITH_WARNINGS',
      sheet_tab_color_enabled: true,
      applied_tab_color_count: 1,
    })
    expect(result.format_warnings).toEqual(expect.arrayContaining([
      expect.objectContaining({ sheet_name: '轨旁AP业务', feature: 'sheet_tab_color' }),
    ]))
  })

  it('prepends one complete history block and deduplicates the same target batch', () => {
    const runtime = standardSpreadsheetRuntime([
      'AP上线情况概览',
      '_NetConsoleSyncMeta',
    ])
    const args = standardSyncArgs(['AP上线情况概览']) as Record<string, any>
    args.snapshot_generated_at = '2026-08-07T01:30:00Z'
    args.workbook.sheets[0] = {
      logical_sheet_key: 'ap_online_history_overview',
      sheet_name: 'AP上线情况概览',
      sheet_order: 0,
      sync_mode: 'PREPEND_SNAPSHOT',
      cells: [
        ['日期：2026-08-07', null],
        ['更新时间：2026-08-07 09:30:00', null],
        ['归属站点', '上线'],
        ['站点A', 1],
        ['合计', 1],
        [null, null],
      ],
      row_count: 6,
      column_count: 2,
    }

    const first = executeStandardSpreadsheet(runtime, args)
    const firstBlockWrite = runtime.writes.find((item) => (
      item.sheet === 'AP上线情况概览' && item.address === 'A1|6x2'
    ))
    expect(first).toMatchObject({
      success: true,
      written_row_count: 6,
      idempotent_prepend_replay: false,
    })
    expect(runtime.inserts).toHaveLength(1)
    expect(firstBlockWrite?.value).toEqual(expect.arrayContaining([
      ['日期：2026-08-07', null],
      ['归属站点', '上线'],
      [null, null],
    ]))
    expect((firstBlockWrite?.value as unknown[][])[1][0]).toMatch(/^更新时间：\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)

    const second = executeStandardSpreadsheet(runtime, args)
    expect(second).toMatchObject({
      success: true,
      written_row_count: 0,
      idempotent_prepend_replay: true,
    })
    expect(runtime.inserts).toHaveLength(1)
  })

  it('keeps the field-verified stable writer isolated from ordering and formatting', () => {
    const source = wpsAirScriptSource('wps_standard_spreadsheet', 'sync')
    const stableWriter = source.split('function writeStableSheet(sheetDto)', 2)[1]
      .split('function isSystemSheetName(name)', 1)[0]

    expect(stableWriter).toContain('if (used && used.ClearContents) used.ClearContents();')
    expect(stableWriter).toContain('sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;')
    expect(stableWriter).not.toContain('.Move(')
    expect(stableWriter).not.toContain('applySheetFormatting')
    expect(stableWriter).not.toContain('format_runs')
  })

  function executeLegacyBindingMigration(overrides: Record<string, string> = {}) {
    const rows: Array<[string, string]> = [
      ['document_id', '549847228994'],
      ['binding_id', `wst_${'a'.repeat(32)}`],
      ['site_id', 'hzl10'],
      ['site_name', '杭州地铁10号线'],
      ['business_key', 'rail_transit.trackside_ap_business'],
      ['target_code', 'wps_standard_spreadsheet'],
      ['target_type', 'WPS_STANDARD_SPREADSHEET'],
    ]
    for (const [key, value] of Object.entries(overrides)) {
      const row = rows.find(([name]) => name === key)
      if (row) row[1] = value
    }
    const writes: string[] = []
    let businessSheetTouched = false
    const metaSheet = {
      Name: '_NetConsoleSyncMeta',
      Range(address: string) {
        if (address === 'A1:B30') return { Value2: rows }
        const match = address.match(/^B(\d+)$/)
        if (!match) throw new Error(`unexpected meta range: ${address}`)
        const index = Number(match[1]) - 1
        return {
          get Value2() { return rows[index]?.[1] },
          set Value2(value: string) {
            writes.push(address)
            rows[index][1] = String(value)
          },
        }
      },
    }
    const businessSheet = {
      Name: '轨旁AP业务',
      Range() {
        businessSheetTouched = true
        throw new Error('migration touched a business sheet')
      },
    }
    const sheets = [metaSheet, businessSheet]
    const application = {
      Worksheets: {
        Count: sheets.length,
        Item(index: number) { return sheets[index - 1] },
        Add() { throw new Error('migration created a sheet') },
      },
    }
    const args = {
      operation: 'migrate_legacy_binding',
      document_id: '549847228994',
      site_id: 'hzl10',
      business_key: 'rail_transit.trackside_ap_business',
      target_code: 'wps_standard_spreadsheet',
      target_type: 'WPS_STANDARD_SPREADSHEET',
      expected_old_binding_id: `wst_${'a'.repeat(32)}`,
      new_binding_id: 'wpsbind_v1_stable',
      script_id: 'test',
    }
    const source = wpsAirScriptSource('wps_standard_spreadsheet', 'sync')
    const raw = new Function('Application', 'Context', source)(application, { argv: args })
    return {
      result: JSON.parse(String(raw)) as Record<string, unknown>,
      rows,
      writes,
      businessSheetTouched,
    }
  }

  it('migrates only the legacy binding cell and returns the new bound identity', () => {
    const execution = executeLegacyBindingMigration()

    expect(execution.result).toMatchObject({
      success: true,
      migrated: true,
      already_migrated: false,
      binding_status: 'BOUND',
      binding_id_match: true,
      previous_binding_id: `wst_${'a'.repeat(32)}`,
      remote_binding_id: 'wpsbind_v1_stable',
    })
    expect(execution.writes).toEqual(['B2'])
    expect(execution.rows[1]).toEqual(['binding_id', 'wpsbind_v1_stable'])
    expect(execution.businessSheetTouched).toBe(false)
  })

  it.each([
    ['document_id', 'other-document'],
    ['site_id', 'other-site'],
    ['business_key', 'other-business'],
    ['target_code', 'other-target'],
    ['target_type', 'WPS_SMART_SHEET'],
  ])('rejects legacy migration when %s does not match', (key, value) => {
    const execution = executeLegacyBindingMigration({ [key]: value })

    expect(execution.result).toMatchObject({
      success: false,
      error_code: 'WPS_DOCUMENT_BINDING_MISMATCH',
    })
    expect(execution.writes).toEqual([])
    expect(execution.businessSheetTouched).toBe(false)
  })

  it('rejects migration when the old binding changed after preflight', () => {
    const execution = executeLegacyBindingMigration({ binding_id: `wst_${'b'.repeat(32)}` })

    expect(execution.result).toMatchObject({
      success: false,
      error_code: 'WPS_DOCUMENT_BINDING_MISMATCH',
      failed_operation: 'VALIDATE_EXPECTED_OLD_BINDING_ID',
    })
    expect(execution.writes).toEqual([])
  })

  it('treats an already migrated stable binding as idempotent success', () => {
    const execution = executeLegacyBindingMigration({ binding_id: 'wpsbind_v1_stable' })

    expect(execution.result).toMatchObject({
      success: true,
      migrated: false,
      already_migrated: true,
      binding_status: 'BOUND',
    })
    expect(execution.writes).toEqual([])
  })
})
