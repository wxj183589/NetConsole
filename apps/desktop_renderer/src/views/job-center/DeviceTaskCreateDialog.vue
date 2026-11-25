<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { listDeviceGroups, listDevices } from '../../api/deviceManagement'
import {
  deviceTaskLabels, getCommandTemplateVersions, listCommandTemplates, previewCommandTemplate,
  previewSavedTemplate, saveCommandTemplate, startDeviceTask, listTaskOrganizations,
  type CommandPreview, type CommandTemplate, type DeviceTaskKind, type SavedTemplate,
  type SavedTemplateDefinition, type SavedTemplatePreview, type TargetGroup,
} from '../../api/deviceOperations'
import type { DeviceGroup, DeviceListItem } from '../../types/deviceManagement'
import { isFeatureEnabled } from '../../features'

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ submitted: [id: string] }>()
const configCollectionEnabled = computed(() => isFeatureEnabled('capability.config_collection.fetch'))
const kinds = computed(() => Object.entries(deviceTaskLabels).filter(
  ([value]) => configCollectionEnabled.value ? value !== 'configuration' : !['configuration', 'backup'].includes(value),
))
const kind = ref<DeviceTaskKind>(configCollectionEnabled.value ? 'backup' : 'diagnostic')
const scope = ref<'devices' | 'group' | 'organization'>('devices')
const organizations = ref<{ uid: string; name: string; parent_uid: string }[]>([])
const organizationUid = ref('')
const concurrency = ref(4)
const commandTimeout = ref(40)
const targets = ref<string[]>([])
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
const canSubmit = computed(() =>
  (scope.value === 'devices' ? targets.value.length > 0 : scope.value === 'group' ? targetGroup.value !== null : Boolean(organizationUid.value))
  && (kind.value !== 'custom' || commandPreviewReady.value),
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
    const saved = await saveCommandTemplate(definition, copy ? undefined : currentTemplate.value)
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
      template: kind.value === 'custom' && !chosen ? template() : undefined,
      saved_template: kind.value === 'custom' && chosen ? {
        template_id: chosen.template_id, version: chosen.version,
        values: JSON.parse(values.value), preview_digest: chosen.preview_digest,
      } : undefined,
    })
    open.value = false
    emit('submitted', result.task_id)
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
  targets.value = []
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
        <el-select v-model="kind" aria-label="任务模板">
          <el-option v-for="[value, label] in kinds" :key="value" :value="value" :label="label" />
        </el-select>
      </el-form-item>
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
        <el-form-item label="并发设备数（1 为串行）"><el-input-number v-model="concurrency" :min="1" :max="8" /></el-form-item>
        <el-form-item v-if="!['configuration', 'backup', 'optical'].includes(kind)" label="查询命令超时（秒）"><el-input-number v-model="commandTimeout" :min="5" :max="120" /></el-form-item>
      </div>
      <template v-if="kind === 'custom'">
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
            <el-input :model-value="templateCommandType === 'read_only' ? '只读' : '配置变更（仅历史模板）'" disabled />
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
          <el-button :loading="waiting" :disabled="templateCommandType !== 'read_only' || !source.trim() || !templateName.trim() || !templateCategory.trim()" @click="saveTemplate(false)">{{ currentTemplate ? '保存新版本' : '保存模板' }}</el-button>
          <el-button v-if="currentTemplate" :disabled="waiting || templateCommandType !== 'read_only'" @click="saveTemplate(true)">复制模板</el-button>
          <el-dropdown v-if="templateVersions.length > 1" @command="fillTemplate">
            <el-button>版本历史</el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item v-for="record in templateVersions" :key="record.version" :command="record">载入 v{{ record.version }}</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
          <el-button :loading="waiting" :disabled="!source.trim() || draftChanged || (!!currentTemplate && !templateEnabled)" @click="render">预览命令</el-button>
        </div>
        <pre v-if="preview" class="preview">{{ preview.commands.join('\n') }}</pre>
        <el-alert v-if="configurationPreview" title="含配置变更命令，当前预览不可提交为只读采集" type="warning" :closable="false" />
      </template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </el-form>
    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :disabled="!canSubmit" :loading="waiting" @click="submit">开始采集</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.task-form { max-height: 63vh; padding: 2px; overflow: auto; }
.template-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 8px; }
.template-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.preview { max-height: 180px; padding: 8px; overflow: auto; background: var(--el-fill-color-light); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
