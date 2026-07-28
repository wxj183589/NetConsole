import type {
  Station,
  StationConflictGroup,
  StationSourceCandidate,
} from '../../types/railTransitBaseData'

export const SOURCE_OVERWRITE_FIELDS = [
  'code',
  'name',
  'sort_order',
  'node_type',
  'path_code',
  'participates_in_direction',
  'source_station_value',
  'source_station_key',
  'source_order_text',
  'source_order',
  'canonical_station_name',
  'source_device_count',
  'source_sync_status',
  'source_last_seen_at',
] as const

export const MANUAL_STATION_FIELDS = [
  'center_mileage_text',
  'center_mileage_m',
  'structure_type',
  'platform_layout',
  'is_line_terminal',
  'is_service_terminal',
  'turnback_capable',
  'turnback_type',
  'track_facilities',
  'turnback_direction',
  'terminal_extension_enabled',
  'terminal_endpoint_label',
  'terminal_extension_distance_m',
  'terminal_endpoint_mileage_text',
  'remark',
] as const

export interface StationFieldDiff {
  field: keyof Station
  current: unknown
  proposed: unknown
  protectedManualField: boolean
}

export function overwriteStationFromSource(
  target: Station,
  candidate: StationSourceCandidate,
  manualFields: readonly (keyof Station)[] = [],
): Station {
  const source = candidate.proposed_station
  const next = { ...target, track_facilities: [...target.track_facilities] }
  for (const field of SOURCE_OVERWRITE_FIELDS) {
    ;(next as unknown as Record<string, unknown>)[field] = source[field]
  }
  for (const field of manualFields) {
    ;(next as unknown as Record<string, unknown>)[field] = source[field]
  }
  next.id = target.id
  next.node_uid = target.node_uid
  next.source_kind = 'device_station_field'
  next.source_sync_status = 'matched'
  next.source_device_count = candidate.source_device_count
  return next
}

export function overwriteStationFromStation(
  target: Station,
  source: Station,
  manualFields: readonly (keyof Station)[] = [],
): Station {
  const next = { ...target, track_facilities: [...target.track_facilities] }
  for (const field of SOURCE_OVERWRITE_FIELDS) {
    ;(next as unknown as Record<string, unknown>)[field] = source[field]
  }
  for (const field of manualFields) {
    ;(next as unknown as Record<string, unknown>)[field] = source[field]
  }
  next.id = target.id
  next.node_uid = target.node_uid
  next.source_kind = 'device_station_field'
  next.source_sync_status = 'matched'
  return next
}

export function stationOverwriteDiffs(
  target: Station,
  candidate: StationSourceCandidate,
): StationFieldDiff[] {
  const source = candidate.proposed_station
  return [...SOURCE_OVERWRITE_FIELDS, ...MANUAL_STATION_FIELDS]
    .filter((field) => JSON.stringify(target[field]) !== JSON.stringify(source[field]))
    .map((field) => ({
      field,
      current: target[field],
      proposed: source[field],
      protectedManualField: (MANUAL_STATION_FIELDS as readonly string[]).includes(field),
    }))
}

export function stationOverwriteDiffsFromStation(
  target: Station,
  source: Station,
): StationFieldDiff[] {
  return [...SOURCE_OVERWRITE_FIELDS, ...MANUAL_STATION_FIELDS]
    .filter((field) => JSON.stringify(target[field]) !== JSON.stringify(source[field]))
    .map((field) => ({
      field,
      current: target[field],
      proposed: source[field],
      protectedManualField: (MANUAL_STATION_FIELDS as readonly string[]).includes(field),
    }))
}

export function groupStationOrderConflicts(stations: readonly Station[]): StationConflictGroup[] {
  const groups = new Map<string, Station[]>()
  for (const station of stations) {
    if (!station.participates_in_direction || station.sort_order === null) continue
    const key = `${station.path_code.toLocaleLowerCase()}:${station.sort_order}`
    const rows = groups.get(key) || []
    rows.push(station)
    groups.set(key, rows)
  }
  return [...groups.entries()]
    .filter(([, rows]) => rows.length > 1)
    .map(([groupId, rows]) => ({
      group_id: groupId,
      path_code: rows[0].path_code,
      sort_order: rows[0].sort_order as number,
      stations: rows.map((row) => ({
        station_id: row.id,
        station_name: row.name,
        code: row.code,
        node_uid: row.node_uid,
        node_type: row.node_type,
        path_code: row.path_code,
        sort_order: row.sort_order,
        source_kind: row.source_kind,
      })),
      suggested_action: 'MANUAL' as const,
      reason: '同一路径内参与方向判断的站点顺序重复',
    }))
    .sort((left, right) => left.path_code.localeCompare(right.path_code) || left.sort_order - right.sort_order)
}

export function stationCombinationErrors(target: Station, sources: readonly Station[]): string[] {
  const errors: string[] = []
  if (target.id.startsWith('new:')) errors.push('保留目标必须是已有正式站点')
  for (const source of sources) {
    if (source.node_type !== target.node_type) errors.push(`${source.name} 与目标节点类型不同`)
    if (source.path_code.toLocaleLowerCase() !== target.path_code.toLocaleLowerCase()) errors.push(`${source.name} 与目标所属路径不同`)
    if (source.is_line_terminal !== target.is_line_terminal) errors.push(`${source.name} 与目标线路端点属性不同`)
    if (
      source.center_mileage_m !== null
      && target.center_mileage_m !== null
      && Math.abs(source.center_mileage_m - target.center_mileage_m) > 250
    ) {
      errors.push(`${source.name} 与目标中心里程差异超过 250 米`)
    }
  }
  return [...new Set(errors)]
}
