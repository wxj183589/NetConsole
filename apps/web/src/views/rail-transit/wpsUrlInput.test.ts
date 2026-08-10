import { describe, expect, it } from 'vitest'

import { normalizeWpsUrlInput, tryParseWpsWebhookIdentity, WpsUrlInputError } from './wpsUrlInput'

const DOCUMENT_URL = 'https://www.kdocs.cn/l/cuYXVQ6v36Rv'
const WEBHOOK_URL = 'https://www.kdocs.cn/api/v3/ide/file/536585421042/script/V2-abc/sync_task'

describe('WPS URL input normalization', () => {
  it.each([
    DOCUMENT_URL,
    `【金山文档 | WPS云文档】 在线测试\n${DOCUMENT_URL}`,
    `【金山文档 | WPS云文档】 在线测试 ${DOCUMENT_URL}`,
    `[${DOCUMENT_URL}](${DOCUMENT_URL})`,
  ])('normalizes a trusted document URL from pasted content', (value) => {
    expect(normalizeWpsUrlInput(value, 'document')).toMatchObject({ url: DOCUMENT_URL })
  })

  it('normalizes and parses a webhook pasted with a label', () => {
    expect(normalizeWpsUrlInput(`webhook地址：\n${WEBHOOK_URL}`, 'webhook')).toMatchObject({
      url: WEBHOOK_URL,
      webhookIdentity: { documentId: '536585421042', scriptId: 'V2-abc' },
    })
    expect(tryParseWpsWebhookIdentity(WEBHOOK_URL)).toEqual({
      documentId: '536585421042',
      scriptId: 'V2-abc',
    })
  })

  it('rejects an untrusted URL instead of extracting it', () => {
    expect(() => normalizeWpsUrlInput('标题 https://evil.example/test', 'document')).toThrow(WpsUrlInputError)
    expect(() => normalizeWpsUrlInput('标题 https://evil.example/test', 'document')).toThrow('请填写有效的 WPS 在线文档链接')
    try {
      normalizeWpsUrlInput('标题 https://evil.example/test', 'document')
    } catch (error) {
      expect(error).toMatchObject({ code: 'WPS_DOCUMENT_URL_INVALID' })
    }
  })

  it('rejects multiple distinct trusted WPS URLs', () => {
    expect(() => normalizeWpsUrlInput(
      `${DOCUMENT_URL} https://www.kdocs.cn/l/another-document`,
      'document',
    )).toThrow('检测到多个 WPS 链接')
    try {
      normalizeWpsUrlInput(`${DOCUMENT_URL} https://www.kdocs.cn/l/another-document`, 'document')
    } catch (error) {
      expect(error).toMatchObject({ code: 'WPS_DOCUMENT_URL_AMBIGUOUS' })
    }
  })
})
