<script setup lang="ts">
import { activeSiteContext } from '../../stores/siteContext'
import { computed, ref, watch } from 'vue'

import { listDeviceGroups, listDevices } from '../../api/deviceManagement'
import {
  deviceTaskLabels, getCommandTemplateVersions, listCommandTemplates, previewCommandTemplate,
  previewSavedTemplate, saveCommandTemplate, startDeviceTask, listTaskOrganizations, getDeviceTaskCapabilities,
  type CommandPreview, type CommandTemplate, type DeviceTaskKind, type SavedTemplate,
  type SavedTemplateDefinition, type SavedTemplatePreview, type TargetGroup,
} from '../../api/deviceOperations'
import type { DeviceGroup, DeviceListItem } from '../../types/deviceManagement'
import { isFeatureEnabled } from '../../features'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{ initialDeviceUuid?: string; initialKind?: DeviceTaskKind }>()
const emit = defineEmits<{ submitted: [id: string]; scheduled: [] }>()
const scheduledAt = ref('')
const upgradeLabEnabled = ref(false)
const configCollectionEnabled = computed(() => isFeatureEnabled('capability.config_collection.fetch'))
const kinds = computed(() => Object.entries(deviceTaskLabels).filter(
  ([value]) => {
    if (value === 'configuration') return false
    if (value === 'upgrade_lab') return upgradeLabEnabled.value
    if (value === 'backup') return configCollectionEnabled.value
    if (value === 'health') return isFeatureEnabled('capability.devices.collect')
    if (value === 'config_preview' || value === 'config_generate') return isFeatureEnabled('capability.config_collection.export')
    if (value === 'config_diff') return isFeatureEnabled('capability.config_collection.diff') && isFeatureEnabled('capability.config_collection.export')
    return true
  },
))
const kind = ref<DeviceTaskKind>(props.initialKind ?? (configCollectionEnabled.value ? 'backup' : 'diagnostic'))
const kindAvailable = computed(() => kinds.value.some(([value]) => value === kind.value))
const snapshotTask = computed(() => ['config_diff', 'config_preview'].includes(kind.value))
const immediateTask = computed(() => snapshotTask.value || ['health', 'config_generate', 'upgrade_lab'].includes(kind.value))
const scope = ref<'devices' | 'group' | 'organization'>('devices')
const organizations = ref<{ uid: string; name: string; parent_uid: string }[]>([])
const organizationUid = ref('')
const concurrency = ref(4)
const commandTimeout = ref(40)
const targets = ref<string[]>(props.initialDeviceUuid ? [props.initialDeviceUuid] : [])
const targetGroup = ref<TargetGroup | null>(null)
const devices = ref<DeviceListItem[]>([])
const groups = ref<DeviceGroup[]>([])
const labels = new Map<string, DeviceListItem>()
const source = ref('display transceiver diagnosis interface {{ interface }}')
const schema = ref('{ "interface": { "type": "interface" } }')
const values = ref('{ "interface": "GigabitEthernet1/0/1" }')
const preview = ref<CommandPreview>()
const savedPreview = ref<SavedTemplatePreview>()
const savedTemplates = ref<SavedTemplate[]>([])
const currentTemplateId = ref('')
const currentTemplate = computed(() => savedTemplates.value.find((item) => item.template_id === currentTemplateId.value))
const templateVersions = ref<SavedTemplate[]>([])
const templateName = ref('')
const templateCategory = ref('自定义')
const templateCommandType = ref<CommandPreview['risk']>('read_only')
const templateRoles = ref<string[]>([])
const templateEnabled = ref(true)
const waiting = ref(false)
const loadingDevices = ref(false)
const error = ref('')
let queryGeneration = 0
let previewGeneration = 0

const configurationPreview = computed(() => preview.value?.risk === 'configuration_change')
const commandPreviewReady = computed(() => preview.value?.risk === 'read_only' && (!currentTemplate.value || Boolean(savedPreview.value)))
const draftChanged = computed(() => {
  const current = currentTemplate.value
  if (!current) return false
  try {
    const { template_id: _id, version: _version, updated_at: _updated, ...definition } = current
    return JSON.stringify(templateDefinition()) !== JSON.stringify(definition)
  } catch {
    return true
  }
})
const dialogSite = ref('')
const canSubmit = computed(() =>
  !waiting.value && Boolean(dialogSite.value) && dialogSite.value === activeSiteContext.value?.siteId
  && kindAvailable.value
  && (scope.value === 'devices' ? targets.value.length > 0 : scope.value === 'group' ? targetGroup.value !== null : Boolean(organizationUid.value))
  && (kind.value !== 'custom' || commandPreviewReady.value)
  && (kind.value !== 'config_generate' || savedPreview.value?.risk === 'configuration_change')
  && (!snapshotTask.value || (scope.value === 'devices' && targets.value.length === 1)),
)

function template(): CommandTemplate {
  return { source: source.value, schema_fields: JSON.parse(schema.value), values: JSON.parse(values.value) }
}

function templateDefinition(): SavedTemplateDefinition {
  return {
    name: templateName.value, category: templateCategory.value,
    source: source.value, schema_fields: JSON.parse(schema.value),
    vendor: 'h3c', platform: 'comware', device_roles: templateRoles.value,
    command_type: templateCommandType.value, enabled: templateEnabled.value,
  }
}

function fillTemplate(record: SavedTemplate): void {
  templateName.value = record.name
  templateCategory.value = record.category
  source.value = record.source
  schema.value = JSON.stringify(record.schema_fields, null, 2)
  templateCommandType.value = record.command_type
  templateRoles.value = [...record.device_roles]
  templateEnabled.value = record.enabled
}

async function pickSaved(id: string): Promise<void> {
  templateVersions.value = []
  const record = savedTemplates.value.find((item) => item.template_id === id)
  if (!record) return
  fillTemplate(record)
  try {
    const history = await getCommandTemplateVersions(record.template_id)
    if (currentTemplateId.value === id) templateVersions.value = history
  } catch (cause) {
    fail(cause)
  }
}

async function saveTemplate(copy: boolean): Promise<void> {
  waiting.value = true
  error.value = ''
  try {
    const definition = templateDefinition()
    if (copy) definition.name += '（副本）'
    if (kind.value === 'config_generate') definition.command_type = 'configuration_change'
    const saved = await saveCommandTemplate(definition, copy ? undefined : currentTemplate.value, kind.value === 'config_generate')
    savedTemplates.value = [saved, ...savedTemplates.value.filter((item) => item.template_id !== saved.template_id)]
    currentTemplateId.value = saved.template_id
    await pickSaved(saved.template_id)
  } catch (cause) {
    fail(cause)
  } finally {
    waiting.value = false
  }
}

function fail(cause: unknown): void {
  error.value = cause instanceof Error ? cause.message : '设备任务操作失败'
}

async function searchDevices(search = ''): Promise<void> {
  const generation = ++queryGeneration
  loadingDevices.value = true
  try {
    const page = await listDevices({ search, vendor: 'H3C', page: 1, page_size: 50 })
    if (generation !== queryGeneration) return
    page.items.forEach((device) => labels.set(device.device_uuid, device))
    devices.value = Array.from(new Set([
      ...targets.value.map((id) => labels.get(id)).filter((item): item is DeviceListItem => Boolean(item)),
      ...page.items,
    ]))
  } catch (cause) {
    if (generation === queryGeneration) fail(cause)
  } finally {
    if (generation === queryGeneration) loadingDevices.value = false
  }
}

async function render(): Promise<void> {
  const generation = ++previewGeneration
  waiting.value = true
  error.value = ''
  preview.value = undefined
  savedPreview.value = undefined
  try {
    const current = currentTemplate.value
    if (current) {
      if (draftChanged.value) throw new Error('模板已编辑，请保存新版本后预览')
      const result = await previewSavedTemplate({
        template_id: current.template_id, version: current.version, values: JSON.parse(values.value),
      })
      if (generation === previewGeneration) {
        preview.value = result
        savedPreview.value = result
      }
    } else {
      const result = await previewCommandTemplate(template())
      if (generation === previewGeneration) preview.value = result
    }
  } catch (cause) {
    if (generation === previewGeneration) fail(cause)
  } finally {
    waiting.value = false
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  waiting.value = true
  error.value = ''
  try {
    const chosen = savedPreview.value
    const result = await startDeviceTask({
      kind: kind.value,
      device_uuids: scope.value === 'devices' ? targets.value : [],
      group_id: scope.value === 'group' ? targetGroup.value : null,
      organization_uid: scope.value === 'organization' ? organizationUid.value : null,
      concurrency: concurrency.value,
      command_timeout: commandTimeout.value,
      scheduled_at: !immediateTask.value && scheduledAt.value ? new Date(scheduledAt.value).toISOString() : undefined,
      template: kind.value === 'custom' && !chosen ? template() : undefined,
      saved_template: (kind.value === 'custom' || kind.value === 'config_generate') && chosen ? {
        template_id: chosen.template_id, version: chosen.version,
        values: JSON.parse(values.value), preview_digest: chosen.preview_digest,
      } : undefined,
    }, dialogSite.value)
    open.value = false
    if (result.scheduled_at) emit('scheduled')
    else emit('submitted', result.task_id)
  } catch (cause) {
    fail(cause)
  } finally {
    waiting.value = false
  }
}

watch([source, schema, values, currentTemplate, templateName, templateCategory, templateCommandType, templateRoles, templateEnabled], () => {
  previewGeneration += 1
  preview.value = undefined
  savedPreview.value = undefined
}, { flush: 'sync' })

watch(open, (visible) => {
  if (!visible) return
  dialogSite.value = activeSiteContext.value?.siteId || ''
  void getDeviceTaskCapabilities().then(
    (capabilities) => { upgradeLabEnabled.value = capabilities.upgrade_lab },
    () => { upgradeLabEnabled.value = false },
  )
  targets.value = props.initialDeviceUuid ? [props.initialDeviceUuid] : []
  targetGroup.value = null
  error.value = ''
  labels.clear()
  devices.value = []
  groups.value = []
  organizations.value = []
  organizationUid.value = ''
  if (isFeatureEnabled('module.rail_infrastructure')) {
    void listTaskOrganizations().then((items) => { organizations.value = items }).catch(fail)
  }
  void searchDevices()
  void listDeviceGroups().then((items) => { groups.value = items }).catch(fail)
  void listCommandTemplates().then((items) => { savedTemplates.value = items }).catch(fail)
}, { immediate: true })
</script>

<template>
  <el-dialog v-model="open" title="创建设备任务" width="min(740px, 94vw)" :close-on-click-modal="false">
    <el-form label-position="top" class="task-form">
      <el-form-item label="任务模板">
        <span v-if="initialKind">{{ deviceTaskLabels[kind] }}</span>
        <el-select v-else v-model="kind" aria-label="任务模板">
          <el-option v-for="[value, label] in kinds" :key="value" :value="value" :label="label" />
        </el-select>
      </el-form-item>
      <el-alert v-if="initialKind && !kindAvailable" type="info" :closable="false" :title="kind === 'upgrade_lab' ? '当前环境未启用模拟升级' : '当前环境未启用此任务模板'" />
      <el-form-item label="目标范围">
        <el-radio-group v-model="scope">
          <el-radio-button value="devices">选择设备</el-radio-button>
          <el-radio-button value="group">分组或局点</el-radio-button>
          <el-radio-button v-if="isFeatureEnabled('module.rail_infrastructure')" value="organization">组织及下级</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="scope === 'devices'" label="设备">
        <el-select
          v-model="targets" multiple filterable remote collapse-tags collapse-tags-tooltip
          :remote-method="searchDevices" :loading="loadingDevices" :multiple-limit="64" aria-label="目标设备"
        >
          <el-option v-for="device in devices" :key="device.device_uuid" :value="device.device_uuid" :label="`${device.name} · ${device.primary_address}`" />
        </el-select>
      </el-form-item>
      <el-form-item v-else-if="scope === 'group'" label="设备分组">
        <el-select v-model="targetGroup" aria-label="设备分组">
          <el-option label="当前局点全部设备" value="all" />
          <el-option label="未分组" value="ungrouped" />
          <el-option v-for="group in groups" :key="group.id" :value="group.id" :label="`${group.name}（${group.device_count}）`" />
        </el-select>
      </el-form-item>
      <el-form-item v-else label="组织节点">
        <el-select v-model="organizationUid" filterable aria-label="组织节点">
          <el-option v-for="node in organizations" :key="node.uid" :value="node.uid" :label="node.name" />
        </el-select>
      </el-form-item>
      <div class="template-fields">
      <details v-if="!snapshotTask" class="execution-settings">
        <summary>执行设置</summary>
        <el-form-item label="并发设备数（1 为串行）"><el-input-number v-model="concurrency" :min="1" :max="8" /></el-form-item>
        <el-form-item v-if="!immediateTask" label="定时执行"><input v-model="scheduledAt" type="datetime-local" aria-label="执行时间（本地）" /></el-form-item>
        <el-form-item v-if="!immediateTask && !['configuration', 'backup', 'optical'].includes(kind)" label="查询命令超时（秒）"><el-input-number v-model="commandTimeout" :min="5" :max="120" /></el-form-item>
      </details>
      </div>
      <template v-if="kind === 'custom' || kind === 'config_generate'">
        <el-form-item label="局点模板">
          <el-select v-model="currentTemplateId" aria-label="局点模板" @change="pickSaved">
            <el-option label="临时模板" value="" />
            <el-option
              v-for="record in savedTemplates" :key="record.template_id" :value="record.template_id"
              :label="`${record.category} / ${record.name} · v${record.version}${record.enabled ? '' : ' · 已停用'}`"
            />
          </el-select>
        </el-form-item>
        <div class="template-fields">
          <el-form-item label="模板名称"><el-input v-model="templateName" maxlength="100" /></el-form-item>
          <el-form-item label="分类"><el-input v-model="templateCategory" maxlength="64" /></el-form-item>
          <el-form-item label="适用设备（H3C Comware）">
            <el-select v-model="templateRoles" multiple collapse-tags placeholder="全部适用类型">
              <el-option label="交换机" value="switch" />
              <el-option label="无线控制器" value="wireless_controller" />
              <el-option label="移动路由器" value="mobile_router" />
            </el-select>
          </el-form-item>
          <el-form-item label="命令类型">
            <el-input :model-value="kind === 'config_generate' ? '待审阅配置' : '只读'" disabled />
          </el-form-item>
        </div>
        <el-form-item label="Jinja2 命令模板">
          <el-input v-model="source" type="textarea" :rows="4" maxlength="16384" />
        </el-form-item>
        <div class="template-fields">
          <el-form-item label="参数定义（JSON）"><el-input v-model="schema" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="参数值（JSON）"><el-input v-model="values" type="textarea" :rows="3" /></el-form-item>
        </div>
        <div class="template-actions">
          <el-switch v-model="templateEnabled" aria-label="启用模板" active-text="启用模板" />
          <el-button :loading="waiting" :disabled="!source.trim() || !templateName.trim() || !templateCategory.trim()" @click="saveTemplate(false)">{{ currentTemplate ? '保存新版本' : '保存模板' }}</el-button>
          <el-button v-if="currentTemplate" :disabled="waiting" @click="saveTemplate(true)">复制模板</el-button>
          <el-dropdown v-if="templateVersions.length > 1" @command="fillTemplate">
            <el-button>版本历史</el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item v-for="record in templateVersions" :key="record.version" :command="record">载入 v{{ record.version }}</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
          <el-button :loading="waiting" :disabled="!source.trim() || draftChanged || (!!currentTemplate && !templateEnabled)" @click="render">预览命令</el-button>
        </div>
        <pre v-if="preview" class="preview">{{ preview.commands.join('\n') }}</pre>
        <el-alert v-if="configurationPreview && kind === 'custom'" title="含配置变更命令，当前预览不可提交为只读采集" type="warning" :closable="false" />
      </template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </el-form>
    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :disabled="!canSubmit" :loading="waiting" @click="submit">{{ !immediateTask && scheduledAt ? '保存计划' : immediateTask ? '创建任务' : '开始采集' }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.task-form { max-height: 63vh; padding: 2px; overflow: auto; }
.template-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 8px; }
.execution-settings summary { cursor: pointer; margin-bottom: 8px; font-weight: 600; }
.template-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.preview { max-height: 180px; padding: 8px; overflow: auto; background: var(--el-fill-color-light); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
