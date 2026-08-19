const COMMIT_BUILD_ID = /^[^+]+\+([0-9a-f]{8})[0-9a-f]*(?:-(dirty))?$/i
const FULL_GIT_SHA = /^[0-9a-f]{40}$/

export interface RendererBuildMetadata {
  app_version: string
  git_commit: string
  git_commit_full: string
  git_commit_short: string
  build_time: string
  build_time_utc: string
  build_dirty: boolean
  build_source: string
  frontend_commit: string
  backend_commit: string
  product_version: string
  build_number: number
  file_version: string
  published: boolean
  navigation_schema_version: number
  build_id: string
}

export function visibleVersionIdentity(version: string, buildId: string): string {
  const normalizedVersion = String(version || '').trim().replace(/^v/i, '')
  const match = String(buildId || '').trim().match(COMMIT_BUILD_ID)
  if (!match) return normalizedVersion
  return `${normalizedVersion}+${match[1]}${match[2] ? '-dirty' : ''}`
}

export function parseRendererBuildMetadata(value: unknown): RendererBuildMetadata {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Renderer 构建元数据格式无效')
  }
  const metadata = value as Record<string, unknown>
  const full = stringField(metadata, 'git_commit_full')
  const version = stringField(metadata, 'app_version')
  const dirty = metadata.build_dirty
  if (
    !FULL_GIT_SHA.test(full)
    || typeof dirty !== 'boolean'
    || stringField(metadata, 'git_commit_short') !== full.slice(0, 8)
    || stringField(metadata, 'frontend_commit') !== full
    || stringField(metadata, 'backend_commit') !== full
    || stringField(metadata, 'product_version') !== version.replace(/^v/i, '')
    || !Number.isInteger(metadata.build_number)
    || stringField(metadata, 'file_version') !== `${stringField(metadata, 'product_version')}.${metadata.build_number}`
    || typeof metadata.published !== 'boolean'
  ) {
    throw new Error('Renderer 构建提交身份不一致')
  }
  const commitIdentity = dirty ? `${full}-dirty` : full
  if (
    stringField(metadata, 'git_commit') !== commitIdentity
    || stringField(metadata, 'build_id') !== `${version}+${commitIdentity}`
    || stringField(metadata, 'build_time') !== stringField(metadata, 'build_time_utc')
    || !stringField(metadata, 'build_source')
    || !Number.isInteger(metadata.navigation_schema_version)
    || Number(metadata.navigation_schema_version) < 1
  ) {
    throw new Error('Renderer 构建元数据不自洽')
  }
  return metadata as unknown as RendererBuildMetadata
}

function stringField(metadata: Record<string, unknown>, key: string): string {
  return typeof metadata[key] === 'string' ? metadata[key].trim() : ''
}
