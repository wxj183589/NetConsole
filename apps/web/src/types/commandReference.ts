export interface CommandReference {
  id: string
  module: string
  device_scope: string
  vendor: string
  protocol: string
  category: string
  command_template: string
  parameters: Array<Record<string, string>>
  pre_commands: string[]
  purpose: string
  output_log: string
  parser: string
  consumer: string
  risk_level: string
  interactive_input: boolean
  is_cli: boolean
  source_locations: string[]
  zte_adaptation_status: string
  comware_command: string
  zte_command: string
  parser_status: string
  notes: string
}

export interface CommandReferencePage {
  items: CommandReference[]
  filters: {
    modules: string[]
    device_scopes: string[]
    vendors: string[]
    protocols: string[]
    categories: string[]
    risk_levels: string[]
  }
  summary: { total: number; shown: number; switch_count: number; non_cli_count: number }
}

export interface CommandReferenceQuery {
  query?: string
  module?: string
  device_scope?: string
  vendor?: string
  protocol?: string
  category?: string
  risk_level?: string
}

export interface CommandReferenceExportTask {
  id: string
  type: string
  name: string
  status: string
  progress: number
  stage: string
  current: number
  total: number
  message: string
  error_message: string
  cancellable: boolean
  result: Record<string, unknown>
}
