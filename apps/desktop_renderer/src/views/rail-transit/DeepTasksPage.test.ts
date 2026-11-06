// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import DeepTasksPage from './DeepTasksPage.vue'
import { listGroundDeepTasks, listGroundDeepCollectionRecords } from '../../api/groundUnattended'

const fixture = vi.hoisted(() => ({ context: {} as Record<string, unknown> }))
vi.mock('./useGroundUnattended', () => ({ useGroundContext: () => fixture.context }))
vi.mock('../../api/groundUnattended', () => ({ listGroundDeepTasks: vi.fn(), listGroundDeepCollectionRecords: vi.fn() }))
const task = { operation_id: 'old-operation', run_id: 'run-a', train_id: 'train-a', mr_id: 'mr-a', mr_role: 'CT', state: 'RUNNING', source_state: 'RUNNING', items: [{ name: 'wmesh', label: 'WMESH', status: 'running', size_bytes: 10 }, { name: 'rssi', label: 'RSSI', status: 'failed', error: 'timeout', size_bytes: 2 }] }
afterEach(() => vi.clearAllMocks())

it('shows independent children, reads exact operation logs and closes stale drawer on run change', async () => {
  const run = ref('run-a')
  fixture.context = { selectedRunId: run, activeTab: ref('deep'), profile: ref(null), groundStatusLabel: String, bytes: String, openDeepSession: vi.fn() }
  vi.mocked(listGroundDeepTasks).mockResolvedValue({ items: [task], total: 1, page: 1, page_size: 50, statistics: { task_count: 1 } } as never)
  vi.mocked(listGroundDeepCollectionRecords).mockResolvedValue({ collector: task, records: [], next_cursor: '' } as never)
  const slot = { template: '<div><slot /></div>' }
  const wrapper = mount(DeepTasksPage, { global: { stubs: {
    NcDataTable: { props: ['data'], emits: ['row-click'], template: '<button class="open-task" @click="$emit(\'row-click\', data[0])">task</button>' },
    ElDrawer: { props: ['modelValue'], template: '<div v-if="modelValue" class="drawer"><slot /></div>' },
    ElTabs: { props: ['modelValue'], emits: ['update:modelValue'], template: '<div><button class="logs-tab" @click="$emit(\'update:modelValue\',\'logs\')">logs</button><slot /></div>' },
    ElTabPane: slot, ElDescriptions: slot, ElDescriptionsItem: slot, ElButton: slot, ElCheckbox: slot,
    ElProgress: true, ElSelect: true, ElOption: true, ElInput: true, ElDatePicker: true, ElPagination: true, ElTable: true,
  } } })
  await flushPromises()
  await wrapper.get('.open-task').trigger('click')
  expect(wrapper.get('.drawer').text()).toContain('WMESH')
  expect(wrapper.get('.drawer').text()).toContain('timeout')
  await wrapper.get('.logs-tab').trigger('click')
  await flushPromises()
  expect(listGroundDeepCollectionRecords).toHaveBeenCalledWith(expect.objectContaining({ operation_id: 'old-operation', run_id: 'run-a' }), expect.anything())
  run.value = 'run-b'
  await nextTick()
  expect(wrapper.find('.drawer').exists()).toBe(false)
  wrapper.unmount()
})
