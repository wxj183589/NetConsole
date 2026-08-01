import type { Station } from '../../../types/railTransitBaseData'
import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'

export type PlanningStation = Pick<Station, 'id' | 'name' | 'sort_order'>
  & Partial<Pick<Station, 'enabled' | 'node_type' | 'participates_in_direction'>>

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

export function reconcileTracksideApPlans(
  currentPlans: TracksideApPlanRow[],
  currentStations: PlanningStation[],
  generatedStationIds: Iterable<string>,
): TracksideApPlanRow[] {
  const stationById = new Map(currentStations.map((station) => [station.id, station]))
  const generated = new Set(generatedStationIds)
  const rows = currentPlans.map((source) => {
    const row = copy(source)
    const station = stationById.get(row.station_id)
    if (!station || !station.enabled) {
      return { ...row, relation_status: 'stale' as const }
    }
    return {
      ...row,
      station_name: station.name,
      sequence_no: station.sort_order ?? row.sequence_no,
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
      sequence_no: station.sort_order ?? rows.length + 1,
      planned_ap_count: 0,
      management_vlan: null,
      remark: '',
      relation_status: 'resolved',
      candidate_station_ids: [],
    })
    existingIds.add(station.id)
  }
  const stationClass = (row: TracksideApPlanRow): number => {
    const nodeType = stationById.get(row.station_id)?.node_type
    if (nodeType === 'station') return 0
    if (nodeType === 'depot') return 1
    if (nodeType === 'parking_lot') return 2
    return 3
  }
  return rows.sort((left, right) => {
    const classDelta = stationClass(left) - stationClass(right)
    if (classDelta) return classDelta
    if (stationClass(left) === 0) {
      const leftOrder = stationById.get(left.station_id)?.sort_order
      const rightOrder = stationById.get(right.station_id)?.sort_order
      const orderDelta = (leftOrder ?? Number.MAX_SAFE_INTEGER)
        - (rightOrder ?? Number.MAX_SAFE_INTEGER)
      if (orderDelta) return orderDelta
    }
    return left.station_id.localeCompare(right.station_id)
  })
}
