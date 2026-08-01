import type { Station } from '../../../types/railTransitBaseData'
import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'

export type PlanningStation = Pick<Station, 'id' | 'name' | 'sort_order'>
  & Partial<Pick<Station, 'enabled' | 'node_type' | 'participates_in_direction'>>

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

function participatesInAutomaticPlan(station: PlanningStation): boolean {
  return station.enabled === true
    && station.node_type === 'station'
    && station.participates_in_direction === true
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
    if (!station || !station.enabled) return { ...row, relation_status: 'stale' as const }
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
      || !participatesInAutomaticPlan(station)) continue
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
  return rows.sort((left, right) => left.sequence_no - right.sequence_no
    || left.station_id.localeCompare(right.station_id))
}
