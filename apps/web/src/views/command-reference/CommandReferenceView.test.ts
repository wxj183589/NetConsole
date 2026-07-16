import { describe, expect, it } from 'vitest'

import source from './CommandReferenceView.vue?raw'
import { commandReferenceArtifactDownloadRequest } from '../../api/commandReference'

describe('Command Reference view', () => {
  it('covers Qt query, detail, copy, refresh and stable states without command execution', () => {
    expect(source).toContain("const state = computed(() => error.value ? 'error' : loading.value ? 'loading'")
    expect(source).toContain('搜索命令、用途、模块、源码位置')
    expect(source).toContain('filters.risk_level')
    expect(source).toContain('navigator.clipboard.writeText')
    expect(source).toContain('selected.parameters')
    expect(source).toContain('不执行设备命令')
    expect(source).not.toContain('executeCommand')
  })

  it('uses a persistent export task and controlled Artifact download', () => {
    expect(source).toContain('window.localStorage.setItem(taskStorageKey')
    expect(source).toContain('getCommandReferenceExport')
    expect(source).toContain('cancelCommandReferenceExport')
    expect(source).toContain('downloadBackendResource')
    expect(source).not.toContain('output_path')
    expect(commandReferenceArtifactDownloadRequest('a/b', 'commands.md')).toEqual({
      apiPath: '/api/command-reference/artifacts/a%2Fb/download',
      suggestedName: 'commands.md',
    })
  })
})
