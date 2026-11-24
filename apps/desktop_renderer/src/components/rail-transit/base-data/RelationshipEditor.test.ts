// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus, { ElSelect, ElInput } from 'element-plus'
import RelationshipEditor from './RelationshipEditor.vue'
import { setRendererFeaturesForTest } from '../../../features'
const api = vi.hoisted(() => ({ relationshipCatalog: vi.fn(), currentRelationships: vi.fn(), relationshipHistory: vi.fn(), previewRelationship: vi.fn(), saveRelationship: vi.fn(), saveEngineeringProject: vi.fn(), acRelationshipResources: vi.fn() }))
vi.mock('../../../api/railRelationships', () => api)
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), onBeforeRouteLeave: vi.fn() }))
const catalog = { nodes: [{ uid: 's1', kind: 'station', code: '01', name: '车站一' }, { uid: 's2', kind: 'station', code: '02', name: '车站二' }], devices: [{ device_uuid: 'mr-new', name: '新 MR', device_type: 'MR', group_name: '' }], sections: [{ id: 'section-1', name: '区间一' }], projects: [], revision: 'r1', can_write: true, write_denial_reason: '' }
const mounts: ReturnType<typeof mount>[] = []
function render(kind = 'section', uid = 'section-1') {
  const w = mount(RelationshipEditor, { props: { siteId: 'demo', entityUid: uid, entityKind: kind, entityName: '工程对象' }, global: { plugins: [ElementPlus], stubs: { ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' } } } })
  mounts.push(w); return w
}
async function click(w: ReturnType<typeof render>, text: string) { const button = w.findAll('button').find(b => b.text() === text); expect(button).toBeDefined(); await button!.trigger('click'); await flushPromises() }
beforeEach(() => {
  setRendererFeaturesForTest({ 'capability.rail_infrastructure.write': { visible: true, enabled: true } })
  vi.clearAllMocks()
  api.relationshipCatalog.mockResolvedValue(structuredClone(catalog))
  api.currentRelationships.mockResolvedValue({ items: [], revision: 'r1' })
  api.previewRelationship.mockResolvedValue({ changes: [], revision: 'r2' })
  api.saveRelationship.mockResolvedValue({ revision: 'r2' })
  api.relationshipHistory.mockResolvedValue({ items: [], total: 0 })
  api.acRelationshipResources.mockResolvedValue({ total: 4, items: [] })
})
afterEach(() => { for (const w of mounts.splice(0)) w.unmount() })
describe('Engineering relationship editing', () => {
  it('does not expose writes when only base-data write permission is enabled', async () => {
    setRendererFeaturesForTest({ 'capability.rail_base_data.write': { visible: true, enabled: true } })
    const w = render(); await flushPromises()
    expect(w.findAll('button').some(b => b.text() === '关联已有对象')).toBe(false)
    expect(api.saveRelationship).not.toHaveBeenCalled()
  })
  it('requires server preview, invalidates it on edits, and saves the exact draft', async () => {
    const w = render(); await flushPromises(); await click(w, '关联已有对象')
    w.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'mr-new'); await flushPromises()
    const save = () => w.findAll('button').find(b => b.text() === '确认保存')!
    expect(save().attributes('disabled')).toBeDefined()
    await click(w, '预览并校验')
    expect(api.previewRelationship).toHaveBeenCalledWith(expect.objectContaining({ source_uid: 'mr-new', target_uid: 'section-1', relationship_type: 'device_section', base_revision: 'r1' }))
    w.findAllComponents(ElInput).at(-1)!.vm.$emit('update:modelValue', '现场更换'); await flushPromises()
    expect(save().attributes('disabled')).toBeDefined()
    await click(w, '预览并校验'); await click(w, '确认保存')
    expect(api.saveRelationship).toHaveBeenCalledWith(api.previewRelationship.mock.calls.at(-1)![0])
    expect(w.emitted('saved')).toHaveLength(1)
  })
  it('keeps failed drafts and refreshes revision only on explicit user action', async () => {
    const w = render(); await flushPromises(); await click(w, '关联已有对象')
    w.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'mr-new'); await flushPromises()
    await click(w, '预览并校验')
    api.saveRelationship.mockRejectedValueOnce(new Error('BASE_DATA_REVISION_CONFLICT'))
    await click(w, '确认保存')
    expect(w.text()).toContain('BASE_DATA_REVISION_CONFLICT')
    api.relationshipCatalog.mockResolvedValue({ ...catalog, revision: 'r3' })
    await click(w, '刷新版本并保留草稿'); await click(w, '预览并校验')
    expect(api.previewRelationship).toHaveBeenLastCalledWith(expect.objectContaining({ source_uid: 'mr-new', base_revision: 'r3' }))
  })
  it('sends AC batch stations as one preview transaction', async () => {
    const w = render('ac', 'ac-1'); await flushPromises(); await click(w, '关联已有对象')
    w.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', ['s1', 's2']); await flushPromises(); await click(w, '预览并校验')
    expect(api.previewRelationship).toHaveBeenCalledWith(expect.objectContaining({ source_uid: 'ac-1', target_uids: ['s1', 's2'] }))
    expect(w.text()).toContain('FIT-AP Current: 4')
  })
  it('replaces MR with explicit preservation notice and stable old assignment ID', async () => {
    api.currentRelationships.mockResolvedValue({ items: [{ relationship_type: 'train_mr', relationship_id: 'old-assignment', source_uid: 'train-1', target_uid: 'mr-old', status: 'active', values: { position: 'CT', assignment_id: 'old-assignment', active_from: '2026-01-01' }, effective_from: '2026-01-01', effective_to: '' }], revision: 'r1' })
    const w = render('train', 'train-1'); await flushPromises(); await click(w, '更换 MR')
    expect(w.text()).toContain('历史会话和报告均保留')
    w.findAllComponents(ElSelect)[1].vm.$emit('update:modelValue', 'mr-new'); await flushPromises(); await click(w, '预览并校验')
    expect(api.previewRelationship).toHaveBeenCalledWith(expect.objectContaining({ action: 'replace', relationship_id: 'old-assignment', target_uid: 'mr-new', values: { position: 'CT' } }))
  })
  it('reads history and hides write controls when the server denies writes', async () => {
    api.relationshipCatalog.mockResolvedValue({ ...catalog, can_write: false, write_denial_reason: '只读' })
    const w = render(); await flushPromises(); expect(w.text()).not.toContain('关联已有对象'); await click(w, '历史')
    expect(api.relationshipHistory).toHaveBeenCalledWith('demo', 'section-1', 1)
    expect(w.text()).toContain('暂无历史')
  })
})
