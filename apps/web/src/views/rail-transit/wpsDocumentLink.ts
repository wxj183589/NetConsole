import { getPlatformAdapter } from '../../platform/runtime'

export interface WpsDocumentOpenResult {
  success: boolean
  error?: string
}

export function validateWpsDocumentUrl(value: string): string {
  let url: URL
  try {
    url = new URL(value.trim())
  } catch {
    throw new TypeError('在线文档地址无效')
  }
  const hostname = url.hostname.toLowerCase().replace(/\.$/, '')
  if (
    url.protocol !== 'https:'
    || (hostname !== 'kdocs.cn' && !hostname.endsWith('.kdocs.cn'))
    || !url.pathname.startsWith('/l/')
    || url.username
    || url.password
    || url.search
    || url.hash
    || (url.port && url.port !== '443')
  ) {
    throw new TypeError('在线文档地址无效')
  }
  return url.href
}

export async function openWpsDocumentUrl(value: string): Promise<WpsDocumentOpenResult> {
  let url: string
  try {
    url = validateWpsDocumentUrl(value)
  } catch (cause) {
    return { success: false, error: cause instanceof Error ? cause.message : '在线文档地址无效' }
  }

  const adapter = getPlatformAdapter()
  try {
    const result = await adapter.openExternalUrl(url)
    if (result.success) return result
    if (adapter.hostType === 'browser') {
      const popup = window.open(url, '_blank', 'noopener,noreferrer')
      if (popup) return { success: true }
      return { success: false, error: '系统浏览器打开失败' }
    }
    return { success: false, error: result.error || '系统浏览器打开失败' }
  } catch (cause) {
    return {
      success: false,
      error: adapter.hostType === 'electron'
        ? '系统浏览器打开失败'
        : (cause instanceof Error ? cause.message : '桌面外部链接能力不可用'),
    }
  }
}
