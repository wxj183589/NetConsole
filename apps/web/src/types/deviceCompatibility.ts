export interface DeviceCompatibilityProfile {
  profile_id: string
  vendor: string
  device_role: string
  platform: string
  validation_level: string
  capabilities: Record<string, string>
}

export interface DeviceCompatibilitySummary {
  generated_at: string
  profile_count: number
  platforms: string[]
  roles: string[]
  validation_levels: string[]
  statement: string
  disclaimer: string
  profiles: DeviceCompatibilityProfile[]
}
