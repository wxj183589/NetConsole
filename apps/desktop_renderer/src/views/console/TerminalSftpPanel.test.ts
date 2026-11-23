// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TerminalSftpPanel from './TerminalSftpPanel.vue'

const mocks = vi.hoisted(() => ({
  sessions: vi.fn(), entries: vi.fn(), transfers: vi.fn(), close: vi.fn(), save: vi.fn(), download: vi.fn(),
  success: vi.fn(), error: vi.fn(), info: vi.fn(),
}))
vi.mock('../../api/terminal', async (original) => ({
  ...await original<typeof import('../../api/terminal')>(),
  listTerminalSftpSessions: mocks.sessions, listTerminalSftpEntries: mocks.entries,
  listTerminalSftpTransfers: mocks.transfers, closeTerminalSftpSession: mocks.close,
  recordTerminalSftpSave: mocks.save,
}))
vi.mock('../../platform/runtime', () => ({ downloadBackendResource: mocks.download }))
vi.mock('element-plus', async (original) => ({
  ...await original<typeof import('element-plus')>(),
  ElMessage: { success: mocks.success, error: mocks.error, info: mocks.info },
}))
const task = { device_uuid: 'device-one', task_id: 'a'.repeat(32), kind: 'DOWNLOAD', status: 'READY', result_name: '中文.cfg', result_size: 6, result_sha256: 'b'.repeat(64), transferred_bytes: 6, total_bytes: 6, source: '/中文.cfg', target: '中文.cfg' }
const session = { session_id: 'session-one', device_uuid: 'device-one', root_path: '/', current_path: '/', state: 'CONNECTED' }
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.clearAllMocks()
  mocks.sessions.mockResolvedValue({ items: [session] })
  mocks.entries.mockResolvedValue({ session, path: '/', items: [] })
  mocks.transfers.mockResolvedValue({ items: [task] })
  mocks.save.mockResolvedValue({ ...task, status: 'COMPLETED' })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })
async function panel() {
  const wrapper = mount(TerminalSftpPanel, { props: { deviceUuid: 'device-one', deviceName: 'LAB' }, global: { stubs: { teleport: true, ElTable: true, ElTableColumn: true, ElDialog: true } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
async function save() {
  const wrapper = await panel()
  await (wrapper.vm as unknown as { saveDownload(value: unknown): Promise<void> }).saveDownload(task)
  return wrapper
}
describe('SFTP native save and session lifetime', () => {
  it('keeps its queue inside the panel and excludes another device', async () => {
    mocks.transfers.mockResolvedValue({ items: [task, { ...task, task_id: 'other-device', device_uuid: 'device-two', result_name: 'other-file', target: 'other-file' }] })
    const wrapper = await panel()
    expect(wrapper.find('.sftp-panel .transfer-queue').exists()).toBe(true)
    expect(wrapper.findAll('.transfer-row')).toHaveLength(1)
    await wrapper.setProps({ deviceUuid: 'device-two' })
    await flushPromises()
    expect(wrapper.text()).not.toContain('中文.cfg')
    expect(mocks.close).not.toHaveBeenCalled()
  })
  it('keeps READY when the native dialog is cancelled', async () => {
    mocks.download.mockResolvedValue({ status: 'cancelled' })
    await save()
    expect(mocks.save).not.toHaveBeenCalled()
    expect(mocks.success).not.toHaveBeenCalled()
  })
  it('reports native save failure and retains the remote download for retry', async () => {
    mocks.download.mockResolvedValue({ status: 'failed', error: 'disk full' })
    await save()
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ result_name: '中文.cfg' }), false)
    expect(mocks.error).toHaveBeenCalledWith('disk full')
    expect(mocks.success).not.toHaveBeenCalled()
  })
  it('rejects mismatched successful responses instead of showing fake completion', async () => {
    mocks.download.mockResolvedValue({ status: 'saved', sizeBytes: 5, sha256: task.result_sha256 })
    await save()
    expect(mocks.save).toHaveBeenCalledWith(expect.anything(), false)
    expect(mocks.success).not.toHaveBeenCalled()
  })
  it('marks completion only after Main returns actual matching size and hash', async () => {
    mocks.download.mockResolvedValue({ status: 'saved', sizeBytes: 6, sha256: task.result_sha256 })
    await save()
    expect(mocks.download).toHaveBeenCalledWith({ apiPath: `/api/terminal/sftp/transfers/${task.task_id}/file`, suggestedName: '中文.cfg', expectedSizeBytes: 6, expectedSha256: task.result_sha256 })
    expect(mocks.save).toHaveBeenCalledWith(expect.anything(), true)
    expect(mocks.success).toHaveBeenCalledWith('文件已保存并校验')
  })
  it('preserves the backend connection when switching devices and unmounting', async () => {
    const wrapper = await panel()
    await wrapper.setProps({ deviceUuid: 'device-two' })
    await wrapper.setProps({ deviceUuid: 'device-one' })
    await flushPromises()
    expect(mocks.entries).toHaveBeenCalledWith('session-one', '/')
    wrapper.unmount()
    expect(mocks.close).not.toHaveBeenCalled()
  })
})
