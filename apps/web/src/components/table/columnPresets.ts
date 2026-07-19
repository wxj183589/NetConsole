import type { NcColumnValueType } from './NcTableColumn'

export interface NcColumnWidthPreset {
  minWidth: number
  maxWidth: number
}

export const NC_COLUMN_WIDTH_PRESETS: Readonly<Record<NcColumnValueType, NcColumnWidthPreset>> = Object.freeze({
  selection: { minWidth: 48, maxWidth: 48 },
  index: { minWidth: 64, maxWidth: 80 },
  text: { minWidth: 100, maxWidth: 300 },
  name: { minWidth: 140, maxWidth: 360 },
  status: { minWidth: 96, maxWidth: 140 },
  ip: { minWidth: 140, maxWidth: 240 },
  mac: { minWidth: 150, maxWidth: 190 },
  port: { minWidth: 90, maxWidth: 260 },
  number: { minWidth: 88, maxWidth: 150 },
  rate: { minWidth: 100, maxWidth: 150 },
  percentage: { minWidth: 100, maxWidth: 140 },
  datetime: { minWidth: 170, maxWidth: 220 },
  duration: { minWidth: 110, maxWidth: 150 },
  mileage: { minWidth: 130, maxWidth: 180 },
  description: { minWidth: 160, maxWidth: 480 },
  error: { minWidth: 180, maxWidth: 520 },
  actions: { minWidth: 96, maxWidth: 240 },
})

export function getColumnWidthPreset(valueType: NcColumnValueType): NcColumnWidthPreset {
  return NC_COLUMN_WIDTH_PRESETS[valueType]
}
