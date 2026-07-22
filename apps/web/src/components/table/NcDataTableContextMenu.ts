export interface NcDataTableContext<Row extends object> {
  row: Row
  rowIndex: number
  columnKey: string
  cellValue: unknown
}

export interface NcDataTableContextMenuItem<Row extends object> {
  key: string
  label: string
  action: (context: NcDataTableContext<Row>) => void | Promise<void>
  disabled?: boolean | ((context: NcDataTableContext<Row>) => boolean)
  disabledReason?: string | ((context: NcDataTableContext<Row>) => string)
  danger?: boolean
  separatorBefore?: boolean
}
