import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../api/externalTools'
import type { ExternalToolView } from '../types/externalTools'
import { useExternalToolsStore } from './externalTools'

vi.mock('../api/externalTools')

function tool(overrides: Partial<ExternalToolView>): ExternalToolView {
  return {
    id: '7c890030-3a3f-4d6b-b58e-7624d21daff9',
    name: 'IPOP',
    source_type: 'independent',
    source_key: null,
    executable_path: 'C:\\Tools\\IPOP.EXE',
    executable_name: 'IPOP.EXE',
    arguments: [],
    working_directory: 'C:\\Tools',
    category_id: 'e5057ec4-03c5-4c17-b24d-b8111ee8f942',
    category_name: '其他工具',
    favorite: false,
    sort_order: 10,
    icon_mode: 'auto',
    custom_icon_path: null,
    icon_data_url: null,
    launch_privilege: 'normal',
    status: 'AVAILABLE',
    status_message: '可用',
    launch_count: 0,
    administrator_launch_count: 0,
    last_launched_at: null,
    last_launch_mode: null,
    created_at: '2026-07-30T00:00:00.000Z',
    updated_at: '2026-07-30T00:00:00.000Z',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('external tools store', () => {
  it('sorts favorites separately and keeps common tools unique and limited', () => {
    const store = useExternalToolsStore()
    store.tools = [
      tool({ id: '9bba76da-b72c-4c1e-af53-293f3cc460f1', name: '收藏', favorite: true, launch_count: 99 }),
      tool({ id: '718694db-36e8-4a91-909d-ad328e350271', name: '常用', launch_count: 5, last_launched_at: '2026-07-30T02:00:00.000Z' }),
      tool({ id: '995d668f-dd6f-49a9-9a2d-2f5f698640c9', name: '未启动' }),
    ]
    expect(store.favoriteTools.map((item) => item.name)).toEqual(['收藏'])
    expect(store.commonTools.map((item) => item.name)).toEqual(['常用'])
  })

  it('disables only the launching tool and refreshes usage after success', async () => {
    const store = useExternalToolsStore()
    const first = tool({})
    vi.mocked(api.launchExternalTool).mockImplementation(async (toolId, launchMode) => {
      expect(store.launchingIds.has(first.id)).toBe(true)
      expect(launchMode).toBe('normal')
      return { success: true, toolId }
    })
    vi.mocked(api.listExternalTools).mockResolvedValue({ schema_version: 2, categories: [], tools: [first] })
    await store.launch(first, 'normal')
    expect(store.launchingIds.has(first.id)).toBe(false)
    expect(api.listExternalTools).toHaveBeenCalledOnce()
  })

  it('clears only the failed tool launch state and preserves other tools', async () => {
    const store = useExternalToolsStore()
    const first = tool({})
    store.tools = [first, tool({ id: '718694db-36e8-4a91-909d-ad328e350271', name: 'Wireshark' })]
    vi.mocked(api.launchExternalTool).mockResolvedValue({ success: false, toolId: first.id, error: '程序文件不存在' })
    await expect(store.launch(first, 'normal')).resolves.toMatchObject({
      success: false,
      error: '程序文件不存在',
    })
    expect(store.tools).toHaveLength(2)
    expect(store.launchingIds.size).toBe(0)
  })
})
