<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { t } from '../../../i18n/runtime'
import { relationshipCatalog, currentRelationships, relationshipHistory, previewRelationship, saveRelationship, saveEngineeringProject, acRelationshipResources, type RelationCatalog, type RelationRequest } from '../../../api/railRelationships'
import type { RailRelationshipRecord, RailRelationshipHistoryRecord, RailRelationshipType } from '../../../types/railTransitBaseData'
const props = defineProps<{ siteId: string; entityUid: string; entityKind: string; entityName: string }>()
const emit = defineEmits<{ saved: []; dirtyChange: [dirty: boolean]; busyChange: [busy: boolean] }>()
const router = useRouter()
const tr = (text: string) => t(`rail.relationship.${text}`, text)
const actionLabel = (action: string) => tr(({ create: '关联已有对象', update: '修改', terminate: '解除', replace: '更换 MR' } as Record<string, string>)[action] || action)
const catalog = ref<RelationCatalog>()
const rows = ref<RailRelationshipRecord[]>([]), projectRows = ref<RailRelationshipRecord[]>([])
const history = ref<RailRelationshipHistoryRecord[]>([])
const error = ref(''), loading = ref(false), saving = ref(false), open = ref(false), historyOpen = ref(false), projectOpen = ref(false)
const previewResult = ref<Awaited<ReturnType<typeof previewRelationship>>>()
const previewRequest = ref<RelationRequest>()
const historyPage = ref(1), historyTotal = ref(0), atTime = ref('')
const historicalRows = ref<RailRelationshipRecord[]>([])
const project = reactive({ name: '', stage: '', reason: '' })
const projectId = ref(''), projectKey = ref(''), projectPreview = ref(false)
const resourceCount = ref<number>()
const form = reactive<RelationRequest>({ site_id: props.siteId, relationship_type: 'device_node', action: 'create', source_uid: '', target_uid: '', values: {}, effective_from: '', effective_to: '', reason: '', base_revision: '', explicit_confirmation: false, idempotency_key: '' })
const targetSelection = ref<string | string[]>('')
let generation = 0
onUnmounted(() => { generation++; emit('dirtyChange', false); emit('busyChange', false) })
const labels = computed<Record<string, string>>(() => Object.fromEntries(Object.entries({ device_node: '物理安装节点', device_section: '区间服务范围', ac_service: 'AC 服务站点', train_mr: '列车 MR', node_project: '建设项目' }).map(([k, v]) => [k, tr(v)])))
const types = computed<RailRelationshipType[]>(() => props.entityKind === 'train' ? ['train_mr'] : props.entityKind === 'section' ? ['device_section'] : props.entityKind === 'ac' ? ['ac_service'] : props.entityKind === 'station' ? ['device_node', 'node_project'] : ['device_node'])
const options = computed(() => {
  if (!catalog.value) return []
  if (form.relationship_type === 'node_project') return catalog.value.projects.map(p => ({ value: p.project_id, label: p.name }))
  if (form.relationship_type === 'ac_service') return catalog.value.nodes.filter(n => !['train', 'section'].includes(n.kind)).map(n => ({ value: n.uid, label: `${n.code} ${n.name}`.trim() }))
  return catalog.value.devices.filter(d => form.relationship_type !== 'train_mr' || ['mr', 'cloud-ap', 'vehicle_mr'].includes(d.device_type.toLowerCase()) || d.group_name === '车载-MR').map(d => ({ value: d.device_uuid, label: d.name }))
})
function label(uid: string) { return catalog.value?.nodes.find(n => n.uid === uid)?.name || catalog.value?.sections.find(n => n.id === uid)?.name || catalog.value?.devices.find(d => d.device_uuid === uid)?.name || catalog.value?.projects.find(p => p.project_id === uid)?.name || uid }
function message(e: unknown) { return e instanceof Error ? e.message : tr('操作失败') }
async function load() {
  const token = ++generation
  loading.value = true; error.value = ''
  try {
    const [c, r] = await Promise.all([relationshipCatalog(props.siteId), currentRelationships(props.siteId, props.entityUid)])
    if (token !== generation) return
    catalog.value = c; rows.value = r.items; resourceCount.value = undefined
    if (props.entityKind === 'ac') {
      const resources = await acRelationshipResources(props.siteId, props.entityUid)
      if (token === generation) resourceCount.value = resources.total
    }
  } catch (e) { if (token === generation) error.value = message(e) }
  finally { if (token === generation) loading.value = false }
}
watch(() => [props.siteId, props.entityUid], () => { open.value = false; historyOpen.value = false; void load() }, { immediate: true })
watch(() => JSON.stringify(form), () => { previewRequest.value = undefined; previewResult.value = undefined })
watch(targetSelection, () => { previewRequest.value = undefined; previewResult.value = undefined }, { deep: true })
watch(() => form.relationship_type, () => { if (form.action === 'create') { targetSelection.value = form.relationship_type === 'ac_service' ? [] : ''; form.values = {} } })
watch(saving, value => emit('busyChange', value))
watch(() => [open.value, projectOpen.value], ([a, b]) => emit('dirtyChange', a || b))
watch(() => [project.name, project.stage, project.reason, projectId.value], () => { projectPreview.value = false })
watch(projectId, async id => {
  try {
    const result = await currentRelationships(props.siteId, id)
    if (projectId.value === id) projectRows.value = id ? result.items.filter(r => r.relationship_type === 'node_project') : []
  } catch (e) { error.value = message(e) }
})
async function closeEditor(done?: () => void) {
  if (saving.value) return
  try { await ElMessageBox.confirm(tr('放弃未保存的关系草稿？'), tr('确认'), { type: 'warning', confirmButtonText: tr('确认'), cancelButtonText: tr('取消') }); open.value = false; projectOpen.value = false; done?.() } catch { /* Keep the draft. */ }
}
onBeforeRouteLeave(async () => {
  if (!open.value && !projectOpen.value) return true
  if (saving.value) return false
  try { await ElMessageBox.confirm(tr('放弃未保存的关系草稿？'), tr('确认'), { confirmButtonText: tr('确认'), cancelButtonText: tr('取消') }); return true } catch { return false }
})
function edit(row?: RailRelationshipRecord, action: RelationRequest['action'] = 'create') {
  error.value = ''; previewRequest.value = undefined; previewResult.value = undefined
  const kind = row?.relationship_type || types.value[0]
  const allowed = kind === 'train_mr' ? ['position'] : ['device_node', 'device_section'].includes(kind) ? ['engineering_role', 'installation_location'] : ['relationship_status']
  Object.assign(form, { site_id: props.siteId, relationship_type: kind, action, relationship_id: row?.relationship_id || '', source_uid: row?.source_uid || props.entityUid, target_uid: row?.target_uid || '', values: Object.fromEntries(Object.entries(row?.values || {}).filter(([k]) => allowed.includes(k))), effective_from: action === 'replace' ? '' : row?.effective_from || '', effective_to: '', reason: '', base_revision: catalog.value?.revision || '', explicit_confirmation: false, idempotency_key: crypto.randomUUID(), target_uids: [] })
  targetSelection.value = action === 'replace' ? '' : kind === 'ac_service' && action === 'create' ? [] : row ? kind === 'device_section' ? row.source_uid : row.target_uid : ''
  open.value = true
}
function payload(): RelationRequest {
  const targets = Array.isArray(targetSelection.value) ? targetSelection.value : [targetSelection.value]
  return { ...form, values: { ...form.values }, source_uid: form.relationship_type === 'device_section' ? targets[0] || '' : form.source_uid, target_uid: form.relationship_type === 'device_section' ? props.entityUid : targets[0] || form.target_uid, target_uids: form.relationship_type === 'ac_service' && form.action === 'create' ? targets : [], explicit_confirmation: true }
}
async function preview() {
  saving.value = true; error.value = ''
  try { const request = payload(); const result = await previewRelationship(request); previewRequest.value = request; previewResult.value = result }
  catch (e) { error.value = message(e) } finally { saving.value = false }
}
async function refreshDraft() {
  saving.value = true
  try { const next = await relationshipCatalog(props.siteId); catalog.value = next; form.base_revision = next.revision; form.idempotency_key = crypto.randomUUID(); error.value = ''; previewRequest.value = undefined }
  catch (e) { error.value = message(e) } finally { saving.value = false }
}
async function save() {
  if (!previewRequest.value) return
  saving.value = true; error.value = ''
  try { await saveRelationship(previewRequest.value); open.value = false; await load(); emit('saved') }
  catch (e) { error.value = message(e); previewRequest.value = undefined; previewResult.value = undefined }
  finally { saving.value = false }
}
async function showHistory(page = 1) {
  error.value = ''
  try { const result = await relationshipHistory(props.siteId, props.entityUid, page); history.value = result.items; historyTotal.value = result.total; historyPage.value = page; historyOpen.value = true }
  catch (e) { error.value = message(e) }
}
async function queryTime() {
  try { historicalRows.value = (await currentRelationships(props.siteId, props.entityUid, atTime.value)).items }
  catch (e) { error.value = message(e) }
}
function openProject() { projectId.value = ''; project.name = ''; project.stage = ''; project.reason = ''; projectKey.value = crypto.randomUUID(); projectPreview.value = false; projectOpen.value = true }
async function saveProject(preview: boolean) {
  saving.value = true; error.value = ''
  try {
    await saveEngineeringProject({ site_id: props.siteId, project_id: projectId.value, name: project.name, stage: project.stage, reason: project.reason, idempotency_key: projectKey.value, base_revision: catalog.value!.revision, explicit_confirmation: true }, preview)
    if (preview) projectPreview.value = true
    else { projectOpen.value = false; await load(); emit('saved') }
  } catch (e) { error.value = message(e) } finally { saving.value = false }
}
</script>
<template>
  <section class="relationship-editor" v-loading="loading" :aria-label="tr('工程关系维护')">
    <header><h4>{{ tr('工程关系') }}</h4><el-button size="small" @click="showHistory()">{{ tr('历史') }}</el-button><el-button v-if="catalog?.can_write" size="small" type="primary" @click="edit()">{{ tr('关联已有对象') }}</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <p v-if="catalog && !catalog.can_write" class="muted">{{ catalog.write_denial_reason }}</p>
    <p v-if="resourceCount !== undefined">FIT-AP Current: {{ resourceCount }} · {{ tr('仅当前 AC 观测，工程服务不改变 AP 身份') }}</p>
    <ul v-if="rows.length" class="relations"><li v-for="row in rows" :key="row.relationship_id"><strong>{{ labels[row.relationship_type] }}</strong><span>{{ label(row.source_uid) }} → {{ label(row.target_uid) }}<template v-if="row.values.position"> · MR-{{ row.values.position }}</template><template v-if="row.values.engineering_role"> · {{ row.values.engineering_role }}</template><template v-if="row.values.installation_location"> · {{ row.values.installation_location }}</template></span><div v-if="catalog?.can_write"><el-button link @click="edit(row,'update')">{{ tr('修改') }}</el-button><el-button v-if="row.relationship_type === 'train_mr'" link type="primary" @click="edit(row,'replace')">{{ tr('更换 MR') }}</el-button><el-button link type="danger" @click="edit(row,'terminate')">{{ tr('解除') }}</el-button></div></li></ul>
    <p v-else class="muted">{{ tr('暂无正式工程关系') }}</p>
    <el-button v-if="catalog?.can_write && entityKind === 'station'" link @click="openProject">{{ tr('建设项目管理') }}</el-button>
    <el-dialog v-model="open" :title="`${actionLabel(form.action)} · ${entityName}`" width="min(620px, 94vw)" :before-close="closeEditor" :close-on-click-modal="false" :close-on-press-escape="!saving">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-alert v-if="form.action === 'terminate' || form.action === 'replace'" :title="tr('只结束工程关联；设备资产、采集记录、原始日志、历史会话和报告均保留。')" type="warning" :closable="false" />
      <el-form label-width="108px" class="relation-form" :disabled="saving">
        <el-form-item :label="tr('关系类型')"><el-select v-model="form.relationship_type" :disabled="form.action !== 'create'"><el-option v-for="kind in types" :key="kind" :label="labels[kind]" :value="kind" /></el-select></el-form-item>
        <el-form-item :label="tr('关联对象')"><el-select v-model="targetSelection" filterable :multiple="form.relationship_type === 'ac_service' && form.action === 'create'" :disabled="form.action === 'terminate' || form.action === 'update'"><el-option v-for="item in options" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        <el-form-item v-if="form.relationship_type === 'train_mr'" :label="tr('端位')"><el-select v-model="form.values.position" :disabled="form.action === 'replace' || form.action === 'terminate'"><el-option label="MR-CT" value="CT" /><el-option label="MR-CW" value="CW" /></el-select></el-form-item>
        <el-form-item v-if="['device_node','device_section'].includes(form.relationship_type)" :label="tr('工程角色')"><el-input v-model="form.values.engineering_role" :maxlength="300" /></el-form-item>
        <el-form-item v-if="['device_node','device_section'].includes(form.relationship_type)" :label="tr('安装位置')"><el-input v-model="form.values.installation_location" :maxlength="300" /></el-form-item>
        <el-form-item v-if="['node_project','ac_service'].includes(form.relationship_type)" :label="tr('关系状态')"><el-input v-model="form.values.relationship_status" :maxlength="300" /></el-form-item>
        <el-form-item :label="tr(form.action === 'terminate' ? '结束时间' : '生效时间')"><el-date-picker v-if="form.action === 'terminate'" v-model="form.effective_to" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /><el-date-picker v-else v-model="form.effective_from" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
        <el-form-item :label="tr('变更原因')"><el-input v-model="form.reason" type="textarea" :maxlength="1000" /></el-form-item>
      </el-form>
      <el-alert v-if="previewResult" :title="`${tr('校验通过，确认后保存当前变更')} · ${previewResult.changes.length}`" type="success" :closable="false" />
      <ul v-if="previewResult" class="preview"><li v-for="(change, index) in previewResult.changes" :key="index"><span>{{ change.after?.source_name || label(change.after?.source_uid || '') }} → {{ change.after?.target_name || label(change.after?.target_uid || '') }} · {{ tr(change.after?.status === 'terminated' ? '解除' : '生效时间') }} {{ change.after?.effective_to || change.after?.effective_from }}<template v-if="change.after?.values?.engineering_role"> · {{ change.before?.values?.engineering_role || '—' }} → {{ change.after.values.engineering_role }}</template><template v-if="change.after?.values?.installation_location"> · {{ change.after.values.installation_location }}</template></span></li></ul>
      <template #footer><el-button :disabled="saving" @click="closeEditor()">{{ tr('取消') }}</el-button><el-button v-if="error" :disabled="saving" @click="refreshDraft">{{ tr('刷新版本并保留草稿') }}</el-button><el-button :loading="saving" @click="preview">{{ tr('预览并校验') }}</el-button><el-button type="primary" :disabled="!previewRequest" :loading="saving" @click="save">{{ tr('确认保存') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="historyOpen" :title="tr('工程关系历史')" width="min(1000px, 94vw)">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <div class="history-scroll"><table><thead><tr><th>{{ tr('操作') }}</th><th>{{ tr('对象') }}</th><th>{{ tr('业务生效') }}</th><th>{{ tr('录入时间') }}</th><th>{{ tr('来源') }}</th><th>{{ tr('原因') }}</th></tr></thead><tbody><tr v-for="event in history" :key="event.event_id"><td>{{ actionLabel(event.action) }}</td><td>{{ event.after.source_name || label(event.source_uid) }} → {{ event.after.target_name || label(event.target_uid) }}</td><td>{{ event.effective_from }} / {{ event.effective_to || tr('当前') }}</td><td>{{ event.changed_at }}</td><td>{{ event.actor }}</td><td>{{ event.reason }}</td></tr></tbody></table><p v-if="!history.length">{{ tr('暂无历史') }}</p></div>
      <el-pagination v-if="historyTotal > 100" :current-page="historyPage" :page-size="100" :total="historyTotal" layout="prev, pager, next" @current-change="showHistory" />
      <div class="time-query"><el-date-picker v-model="atTime" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /><el-button :disabled="!atTime" @click="queryTime">{{ tr('查询历史时点') }}</el-button></div>
      <p v-for="r in historicalRows" :key="r.relationship_id">{{ r.source_name || label(r.source_uid) }} → {{ r.target_name || label(r.target_uid) }}</p>
      <el-button v-if="entityKind==='train'" @click="router.push('/rail-transit/online-mr-analysis')">{{ tr('历史采集会话') }}</el-button>
    </el-dialog>
    <el-dialog v-model="projectOpen" :title="tr('建设项目')" width="min(600px, 94vw)" :before-close="closeEditor" :close-on-click-modal="false">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-form :disabled="saving" label-width="108px"><el-form-item :label="tr('建设项目')"><el-select v-model="projectId" clearable :placeholder="tr('新建项目')" @change="project.name=catalog?.projects.find(p=>p.project_id===projectId)?.name || ''; project.stage=catalog?.projects.find(p=>p.project_id===projectId)?.stage || ''"><el-option v-for="p in catalog?.projects" :key="p.project_id" :label="p.name" :value="p.project_id" /></el-select></el-form-item><el-form-item :label="tr('项目名称')"><el-input v-model="project.name" :maxlength="200" /></el-form-item><el-form-item :label="tr('建设阶段')"><el-input v-model="project.stage" :maxlength="100" /></el-form-item><el-form-item :label="tr('变更原因')"><el-input v-model="project.reason" :maxlength="1000" /></el-form-item></el-form>
      <h4 v-if="projectId">{{ tr('项目涉及站点') }}</h4><p v-for="r in projectRows" :key="r.relationship_id">{{ label(r.source_uid) }}</p>
      <template #footer><el-button @click="closeEditor()">{{ tr('取消') }}</el-button><el-button :loading="saving" @click="saveProject(true)">{{ tr('预览并校验') }}</el-button><el-button type="primary" :disabled="!projectPreview" :loading="saving" @click="saveProject(false)">{{ tr('确认保存') }}</el-button></template>
    </el-dialog>
  </section>
</template>
<style scoped>
.relationship-editor { border-top: 1px solid var(--nc-border); margin-top: 12px; padding-top: 10px; min-width: 0; }
header { display:flex;align-items:center;gap:8px;flex-wrap:wrap; } h4 { margin:0 auto 0 0; } .muted { color:var(--nc-text-secondary); }
.relations { list-style:none;padding:0; } .relations li { display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--nc-border);padding:8px 0; } .relations span { overflow-wrap:anywhere; } .relations li div { margin-left:auto; }
.relation-form { margin-top:16px;max-height:55vh;overflow:auto; } .relation-form :deep(.el-select) { width:100%; } .history-scroll { overflow:auto;max-height:55vh; }
th,td { padding:8px;text-align:left;border-bottom:1px solid var(--nc-border); } .preview { max-height:120px;overflow:auto;overflow-wrap:anywhere; } .time-query { display:flex;gap:8px;flex-wrap:wrap;margin:12px 0; }
:deep(.el-dialog__footer) { display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px; }
</style>
