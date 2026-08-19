import { describe, expect, it } from 'vitest'

import { parseRendererBuildMetadata, visibleVersionIdentity } from './buildIdentity'

function metadata(commit = '29541dda879049c54ace0730c44fc6f3eb92b872') {
  return {
    app_version: 'v1.4.9',
    product_version: '1.4.9',
    build_number: 0,
    file_version: '1.4.9.0',
    git_commit: commit,
    git_commit_full: commit,
    git_commit_short: commit.slice(0, 8),
    build_time: '2026-08-14T08:00:00Z',
    build_time_utc: '2026-08-14T08:00:00Z',
    build_dirty: false,
    build_source: 'git-release',
    frontend_commit: commit,
    backend_commit: commit,
    navigation_schema_version: 1,
    build_id: `v1.4.9+${commit}`,
    published: true,
  }
}

describe('visibleVersionIdentity', () => {
  it('shows the packaged commit in the permanent user-visible version', () => {
    expect(
      visibleVersionIdentity(
        '1.4.9',
        'v1.4.9+29541dda879049c54ace0730c44fc6f3eb92b872',
      ),
    ).toBe('1.4.9+29541dda')
  })

  it('keeps dirty source builds explicit', () => {
    expect(
      visibleVersionIdentity(
        'v1.4.9',
        'v1.4.9+29541dda879049c54ace0730c44fc6f3eb92b872-dirty',
      ),
    ).toBe('1.4.9+29541dda-dirty')
  })

  it('falls back to the version for an invalid build identity', () => {
    expect(visibleVersionIdentity('1.4.9', 'unknown')).toBe('1.4.9')
  })

  it('accepts only self-consistent Renderer metadata', () => {
    expect(parseRendererBuildMetadata(metadata()).git_commit_short).toBe('29541dda')
    expect(() => parseRendererBuildMetadata({
      ...metadata(),
      frontend_commit: '1'.repeat(40),
    })).toThrow('Renderer 构建提交身份不一致')
  })
})
