import { beforeEach, describe, expect, it, vi } from 'vitest'

const messageBoxConfirm = vi.hoisted(() => vi.fn())

vi.mock('element-plus', () => ({ ElMessageBox: { confirm: messageBoxConfirm } }))

import { confirmState, resolveConfirm, useConfirm } from './useConfirm'

describe('useConfirm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmState.providerReady = false
    confirmState.request = null
  })

  it('uses the centralized dialog provider when it is mounted', async () => {
    confirmState.providerReady = true
    const promise = useConfirm().confirm({
      type: 'DESTRUCTIVE',
      title: '删除设备',
      message: '确认删除？',
      confirmText: '确认删除',
    })

    expect(confirmState.request?.options).toMatchObject({ type: 'DESTRUCTIVE', confirmText: '确认删除' })
    expect(messageBoxConfirm).not.toHaveBeenCalled()
    resolveConfirm('confirm')
    await expect(promise).resolves.toBe(true)
    expect(confirmState.request).toBeNull()
  })

  it('returns false when the centralized dialog is cancelled', async () => {
    confirmState.providerReady = true
    const promise = useConfirm().confirm({ title: '操作', message: '确认？' })
    resolveConfirm('cancel')
    await expect(promise).resolves.toBe(false)
  })

  it('supports secondary choices without leaking them into boolean confirms', async () => {
    confirmState.providerReady = true
    const promise = useConfirm().confirmChoice({
      type: 'SECURITY',
      title: '传递密码',
      message: '确认启用？',
      secondaryText: '仅本次启用',
    })
    resolveConfirm('secondary')
    await expect(promise).resolves.toBe('secondary')
  })

  it('keeps a development/test fallback inside the service boundary', async () => {
    const onConfirm = vi.fn()
    messageBoxConfirm.mockResolvedValueOnce(undefined)
    await expect(useConfirm().confirm({ title: '确认', message: '继续？', onConfirm })).resolves.toBe(true)
    expect(messageBoxConfirm).toHaveBeenCalledWith('继续？', '确认', expect.objectContaining({
      confirmButtonText: '确认操作',
      cancelButtonText: '取消',
    }))
    expect(onConfirm).toHaveBeenCalledOnce()

    messageBoxConfirm.mockRejectedValueOnce(new Error('cancel'))
    await expect(useConfirm().confirm({ title: '确认', message: '继续？', onConfirm })).resolves.toBe(false)
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})
