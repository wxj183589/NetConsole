export type SystemTheme = 'light' | 'dark' | 'auto'
export type SystemLanguage = 'zh_CN' | 'en_US'
export type SystemThemeColor = '#0078D4' | '#2563EB' | '#0891B2' | '#16A34A'
export type ExternalTerminalType = 'putty' | 'securecrt' | 'xshell'

export interface SystemSettingsValues {
  theme: SystemTheme
  language: SystemLanguage
  theme_color: SystemThemeColor
  iperf_path: string
  fping_path: string
  ipop_path: string
  terminal_type: ExternalTerminalType
  terminal_paths: Record<ExternalTerminalType, string>
  securecrt_sessions_root: string
  ssh_port: number
  telnet_port: number
  crt_encoding: 'UTF-8' | 'GBK'
}

export interface SystemSettingsSnapshot {
  version: string
  values: SystemSettingsValues
  defaults: SystemSettingsValues
  current_site_name: string
  current_site_path: string
  language_status: 'BLOCKED_ON_GLOBAL_I18N'
}

export type NetworkComponentName = 'iperf3' | 'fping'
export type NetworkComponentMode = 'builtin' | 'custom'
export type NetworkComponentSource = 'builtin' | 'custom'

export interface NetworkComponentStatus {
  component_name: NetworkComponentName
  mode: NetworkComponentMode
  source: NetworkComponentSource
  configured_path: string
  effective_path: string
  available: boolean
  file_exists: boolean
  fallback_used: boolean
  fallback_reason: string
  validation_message: string
}

export interface NetworkComponentsSnapshot {
  version: string
  components: NetworkComponentStatus[]
}

export interface FeatureSetting {
  feature_id: string
  title: string
  group_id: string
  group_title: string
  scope: 'global'
  visible: boolean
  enabled: boolean
  inherited_visible: boolean
  inherited_enabled: boolean
  client_package: boolean
  internal_only: boolean
  package_range: 'customer_internal' | 'internal' | 'internal_only' | 'not_included'
  status: 'ENABLED' | 'DISABLED' | 'DEVELOPMENT' | 'HIDDEN'
  dependencies: string[]
  locked: boolean
  lock_reason: string
  overridden: boolean
}

export interface FeatureSettingsSnapshot {
  items: FeatureSetting[]
  preview_active: boolean
  configuration_name: string
  scope_label: string
  inherited_profile: string
}

export interface RuntimeSelfCheckItem {
  check_id: string
  title: string
  status: 'normal' | 'warning' | 'error'
  message: string
  suggestion: string
}

export interface RuntimeSelfCheckSnapshot {
  status: 'normal' | 'warning' | 'error'
  checked_at: string
  packaged: boolean
  unicode_sample: string
  items: RuntimeSelfCheckItem[]
}
