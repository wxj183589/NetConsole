export interface WirelessScanFilters {
  only_trackside: boolean
  band: string
  radio: string
  search: string
}

export function filterWirelessScanRows(rows: Record<string, unknown>[], filters: WirelessScanFilters): Record<string, unknown>[] {
  const search = filters.search.trim().toLocaleLowerCase()
  return rows.filter((row) => {
    if (filters.only_trackside && !row.matched_trackside_ap) return false
    if (filters.band && row.band !== filters.band) return false
    if (filters.radio && String(row.matched_radio_id || '') !== filters.radio) return false
    if (!search) return true
    return ['display_ssid', 'display_mac_address', 'display_ap_mac', 'display_ap_name', 'display_station', 'display_section', 'display_location_mileage']
      .some((field) => String(row[field] || '').toLocaleLowerCase().includes(search))
  })
}
