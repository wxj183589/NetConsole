import type { Station } from '../../../types/railTransitBaseData'
import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'

export type PlanningStation = Pick<Station, 'id' | 'name'>
  & Partial<Pick<Station, 'sort_order' | 'code' | 'path_code' | 'center_mileage_m' | 'canonical_station_name' | 'source_order' | 'enabled' | 'node_type' | 'participates_in_direction'>>
  & { mainline_order?: number | null }

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export function participatesInMainlineTopology(station: PlanningStation): boolean {
  return station.enabled === true
    && station.node_type === 'station'
    && station.participates_in_direction === true
}

export function participatesInTracksideApPlanning(station: PlanningStation): boolean {
  return station.enabled === true
    && ['station', 'depot', 'parking_lot'].includes(station.node_type || '')
}

const NON_MAINLINE_NODE_TYPES = new Set(['depot', 'parking_lot', 'connection_point', 'other'])
const NODE_TYPE_RANK: Record<string, number> = {
  depot: 0,
  parking_lot: 1,
  connection_point: 2,
  other: 3,
  unknown: 4,
  station: 5,
}

function validMainlineOrder(station: PlanningStation | undefined): number | null {
  const nodeType = String(station?.node_type || 'station').toLocaleLowerCase()
  if (!station || NON_MAINLINE_NODE_TYPES.has(nodeType)) return null
  if (nodeType === 'station' && station.participates_in_direction === false) return null
  const order = Number(station.sort_order ?? station.mainline_order)
  return Number.isInteger(order) && order >= 0 ? order : null
}

function fallbackStationKey(station: PlanningStation | undefined): (number | string)[] {
  const nodeType = String(station?.node_type || 'unknown').toLocaleLowerCase()
  const sourceOrder = Number(station?.source_order)
  const centerMileage = Number(station?.center_mileage_m)
  return [
    NODE_TYPE_RANK[nodeType] ?? 6,
    String(station?.path_code || '').toLocaleLowerCase(),
    Number.isInteger(sourceOrder) ? 0 : 1,
    Number.isInteger(sourceOrder) ? sourceOrder : 0,
    Number.isFinite(centerMileage) ? 0 : 1,
    Number.isFinite(centerMileage) ? centerMileage : 0,
    String(station?.canonical_station_name || '').toLocaleLowerCase(),
    String(station?.code || '').toLocaleLowerCase(),
    String(station?.name || '').toLocaleLowerCase(),
    String(station?.id || ''),
  ]
}

export function compareRailStationDisplayOrder(left: PlanningStation, right: PlanningStation): number {
  const leftMainline = validMainlineOrder(left)
  const rightMainline = validMainlineOrder(right)
  if (leftMainline !== null && rightMainline === null) return -1
  if (leftMainline === null && rightMainline !== null) return 1
  if (leftMainline !== null && rightMainline !== null && leftMainline !== rightMainline) {
    return leftMainline - rightMainline
  }
  const leftFallback = fallbackStationKey(left)
  const rightFallback = fallbackStationKey(right)
  for (let index = 0; index < leftFallback.length; index += 1) {
    if (leftFallback[index] < rightFallback[index]) return -1
    if (leftFallback[index] > rightFallback[index]) return 1
  }
  return 0
}

export function sortRailStations<T extends PlanningStation>(rows: T[]): T[] {
  return [...rows].sort(compareRailStationDisplayOrder)
}

function positiveInteger(value: unknown): number | null {
  const number = Number(value)
  return Number.isInteger(number) && number > 0 ? number : null
}

export function sortTracksideApPlanRows(
  rows: TracksideApPlanRow[],
  stations: PlanningStation[],
): TracksideApPlanRow[] {
  const stationById = new Map(stations.map((station) => [station.id, station]))
  return [...rows].sort((left, right) => {
    const leftOrder = positiveInteger(left.display_order ?? left.sequence_no) ?? Number.MAX_SAFE_INTEGER
    const rightOrder = positiveInteger(right.display_order ?? right.sequence_no) ?? Number.MAX_SAFE_INTEGER
    return leftOrder - rightOrder
      || compareRailStationDisplayOrder(
        stationById.get(left.station_id) || { id: left.station_id, name: left.station_name, sort_order: null },
        stationById.get(right.station_id) || { id: right.station_id, name: right.station_name, sort_order: null },
      )
      || left.station_id.localeCompare(right.station_id)
  })
}

export function reconcileTracksideApPlans(
  currentPlans: TracksideApPlanRow[],
  currentStations: PlanningStation[],
  generatedStationIds: Iterable<string>,
): TracksideApPlanRow[] {
  const stationById = new Map(currentStations.map((station) => [station.id, station]))
  const generated = new Set(generatedStationIds)
  const maxMainlineOrder = Math.max(
    0,
    ...currentStations.map((station) => validMainlineOrder(station) ?? 0),
  )
  const rows = currentPlans.map((source) => {
    const row = copy(source)
    const station = stationById.get(row.station_id)
    if (!station || !station.enabled) {
      return { ...row, relation_status: 'stale' as const }
    }
    return {
      ...row,
      station_name: station.name,
      relation_status: 'resolved' as const,
      candidate_station_ids: [],
    }
  })
  const existingIds = new Set(rows.map((row) => row.station_id).filter(Boolean))
  for (const station of currentStations) {
    if (!generated.has(station.id)
      || existingIds.has(station.id)
      || !participatesInTracksideApPlanning(station)) continue
    rows.push({
      station_id: station.id,
      station_name: station.name,
      sequence_no: station.sort_order ?? maxMainlineOrder + rows.length + 1,
      planning_order: null,
      display_order: station.sort_order ?? null,
      planned_ap_count: 0,
      management_vlan: null,
      remark: '',
      relation_status: 'resolved',
      candidate_station_ids: [],
    })
    existingIds.add(station.id)
  }
  const explicitOrders = new Set<number>()
  const displayRows = rows.map((row) => {
    const station = stationById.get(row.station_id)
    const explicit = positiveInteger(row.planning_order)
      ?? (positiveInteger(row.sequence_no) !== null
        && positiveInteger(row.sequence_no)! > maxMainlineOrder
        ? positiveInteger(row.sequence_no)
        : null)
    const mainline = validMainlineOrder(station)
    const display = explicit ?? mainline
    if (display !== null) explicitOrders.add(display)
    return { row, station, explicit, display }
  })
  let nextDisplay = Math.max(
    maxMainlineOrder,
    ...explicitOrders,
  ) + 1
  for (const item of displayRows
    .filter((value) => value.display === null)
    .sort((left, right) => compareRailStationDisplayOrder(
      left.station || { id: left.row.station_id, name: left.row.station_name, sort_order: null },
      right.station || { id: right.row.station_id, name: right.row.station_name, sort_order: null },
    ))) {
    while (explicitOrders.has(nextDisplay)) nextDisplay += 1
    item.display = nextDisplay
    explicitOrders.add(nextDisplay)
    nextDisplay += 1
  }
  return displayRows
    .map(({ row, explicit, display }) => ({
      ...row,
      sequence_no: display || 0,
      display_order: display,
      planning_order: explicit,
    }))
    .sort((left, right) =>
      (left.sequence_no - right.sequence_no)
      || left.station_id.localeCompare(right.station_id))
}
