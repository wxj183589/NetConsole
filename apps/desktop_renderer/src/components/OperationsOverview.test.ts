// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { apiRequest } from '../api/client'
import { resetRendererFeaturesForTest, setRendererFeaturesForTest } from '../features'
import { clearSiteContext, setActiveSiteContext } from '../stores/siteContext'
import OperationsOverview from './OperationsOverview.vue'

vi.mock('../api/client', () => ({ apiRequest: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

afterEach(() => {
  clearSiteContext()
  resetRendererFeaturesForTest()
  vi.resetAllMocks()
})

it('keeps late inventory from the previous site out of the current dashboard', async () => {
  setRendererFeaturesForTest({ 'module.devices': { enabled: true, visible: true } })
  setActiveSiteContext({ site_id: 'first' })
  let finishFirst!: (value: unknown) => void
  vi.mocked(apiRequest).mockReturnValueOnce(new Promise(resolve => { finishFirst = resolve }))
    .mockResolvedValueOnce({ site_id: 'second', total: 8, reachable: 0, unreachable: 0, error: 0, testing: 0, unknown: 8 })
  const view = mount(OperationsOverview, { global: { stubs: { ElButton: true, ElAlert: true } } })
  await nextTick()
  setActiveSiteContext({ site_id: 'second' })
  await flushPromises()
  finishFirst({ site_id: 'first', total: 321, unknown: 321 })
  await flushPromises()
  expect(view.findAll('dd').map(item => item.text())).toEqual(['8', '0', '0', '0', '8', '0'])
  expect(apiRequest).toHaveBeenCalledTimes(2)
  view.unmount()
})
