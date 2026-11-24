<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  changeOrganizationAssets,
  getOrganizationCatalog,
  type InfrastructureNode,
  type OrganizationAsset,
  type OrganizationBatch,
  type OrganizationBatchResult,
  type OrganizationCatalog,
} from '../../../api/railInfrastructure'
import { nodeLabel } from './infrastructurePresentation'

const props = defineProps<{ siteId: string; nodes: InfrastructureNode[]; currentUid: string; add: boolean }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const catalog = ref<OrganizationCatalog>()
const selected = ref<string[]>([])
const search = ref('')
const group = ref('')
const deviceType = ref('')
const unassigned = ref(props.add)
const target = ref(props.add ? props.currentUid : '')
const collection = ref<OrganizationAsset['collection'] | ''>('')
const addProjects = ref<string[]>([])
const removeProjects = ref<string[]>([])
const pending = ref<OrganizationBatch>()
const result = ref<OrganizationBatchResult>()
const busy = ref(false)
const error = ref('')

const all = computed(() => catalog.value?.devices ?? [])
const targets = computed(() => props.nodes.filter(node => node.kind !== 'section' && node.kind !== 'train' && node.source === 'engineering'))
const groups = computed(() => [...new Set(all.value.map(asset => asset.group_name).filter(Boolean))])
const types = computed(() => [...new Set(all.value.map(asset => asset.device_type).filter(Boolean))])
const filtered = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return all.value.filter(asset => (!unassigned.value || !asset.node_uids.length)
    && (!group.value || asset.group_name === group.value)
    && (!deviceType.value || asset.device_type === deviceType.value)
    && [asset.name, asset.address, asset.mac, asset.serial].some(value => value.toLocaleLowerCase().includes(query)))
})
const canPreview = computed(() => selected.value.length > 0 && selected.value.length <= 500
  && (props.add ? Boolean(target.value) : Boolean(target.value || collection.value || addProjects.value.length || removeProjects.value.length)))

onMounted(async () => {
  busy.value = true
  try {
    catalog.value = await getOrganizationCatalog(props.siteId)
  } catch {
    error.value = '设备清单读取失败'
  } finally {
    busy.value = false
  }
})

function selectCurrent() {
  selected.value = filtered.value.filter(asset => asset.node_uids.includes(props.currentUid)).map(asset => asset.device_uuid)
}

function affiliations(ids: string[]) {
  return ids.map(id => props.nodes.find(node => node.uid === id)?.name || id).join('、') || '未分配'
}

function projects(ids: string[]) {
  return ids.map(id => catalog.value?.projects.find(project => project.project_id === id)?.name || id).join('、') || '无'
}

function collectionLabel(status: OrganizationAsset['collection']) {
  return status === 'included' ? '参与' : '不参与'
}

async function execute(action: 'preview' | 'apply') {
  if (!catalog.value || busy.value) return
  const batch = action === 'apply' ? pending.value : {
    revision: catalog.value.revision, device_uuids: [...selected.value], node_uid: target.value,
    collection: collection.value || null, add_projects: [...addProjects.value], remove_projects: [...removeProjects.value],
  }
  if (!batch) return
  busy.value = true
  error.value = ''
  try {
    const response = await changeOrganizationAssets(props.siteId, {
      ...batch, explicit_confirmation: action === 'apply',
    }, action)
    if (action === 'apply') emit('saved')
    else {
      pending.value = batch
      result.value = response
    }
  } catch (issue) {
    error.value = issue instanceof Error ? issue.message : '操作失败，请刷新组织结构后重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="true" :title="add ? '添加现有设备' : '编辑设备'" width="min(880px, 95vw)"
    :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @close="emit('close')">
    <div v-loading="busy" class="organization-assets">
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <template v-if="!result">
        <div class="filters">
          <el-input v-model="search" clearable placeholder="名称、IP、MAC、序列号" aria-label="搜索设备" />
          <el-select v-model="group" clearable placeholder="设备分组" aria-label="设备分组">
            <el-option v-for="label in groups" :key="label" :label="label" :value="label" />
          </el-select>
          <el-select v-model="deviceType" clearable placeholder="设备类型" aria-label="设备类型">
            <el-option v-for="label in types" :key="label" :label="label" :value="label" />
          </el-select>
          <el-checkbox v-model="unassigned">仅待分配</el-checkbox>
        </div>
        <el-checkbox-group v-model="selected" class="device-options" :aria-label="'设备列表'">
          <div v-for="asset in filtered" :key="asset.device_uuid" class="device-option">
            <el-checkbox :value="asset.device_uuid" :disabled="add && !!asset.node_uids.length">{{ asset.name }}</el-checkbox>
            <span>{{ asset.address }}</span><span>{{ affiliations(asset.node_uids) }}</span>
          </div>
          <el-empty v-if="!filtered.length" description="无匹配设备" :image-size="36" />
        </el-checkbox-group>
        <div class="selection"><span>已选 {{ selected.length }} 台</span>
          <el-button v-if="currentUid && !add" link @click="selectCurrent">选择当前组织设备</el-button>
        </div>
        <el-form label-width="110px">
          <el-form-item label="目标组织">
            <el-select v-model="target" clearable filterable placeholder="选择组织">
              <el-option v-for="node in targets" :key="node.uid" :label="nodeLabel(node)" :value="node.uid" />
            </el-select>
          </el-form-item>
          <template v-if="!add">
            <el-form-item label="是否参与收集">
              <el-select v-model="collection" clearable placeholder="保持当前状态">
                <el-option label="参与" value="included" /><el-option label="不参与" value="excluded" />
              </el-select>
            </el-form-item>
            <el-form-item label="添加建设项目">
              <el-select v-model="addProjects" multiple filterable clearable>
                <el-option v-for="project in catalog?.projects" :key="project.project_id" :label="project.name" :value="project.project_id" />
              </el-select>
            </el-form-item>
            <el-form-item label="移除建设项目">
              <el-select v-model="removeProjects" multiple filterable clearable>
                <el-option v-for="project in catalog?.projects" :key="project.project_id" :label="project.name" :value="project.project_id" />
              </el-select>
            </el-form-item>
          </template>
        </el-form>
      </template>
      <el-table v-else :data="result.changes" max-height="360" empty-text="没有需要提交的变更">
        <el-table-column prop="before.name" label="设备" min-width="140" />
        <el-table-column label="组织" min-width="180">
          <template #default="{ row }">{{ affiliations(row.before.node_uids) }} → {{ affiliations(row.after.node_uids) }}</template>
        </el-table-column>
        <el-table-column label="建设项目" min-width="160">
          <template #default="{ row }">{{ projects(row.before.project_ids) }} → {{ projects(row.after.project_ids) }}</template>
        </el-table-column>
        <el-table-column label="收集" min-width="110">
          <template #default="{ row }">{{ collectionLabel(row.before.collection) }} → {{ collectionLabel(row.after.collection) }}</template>
        </el-table-column>
      </el-table>
    </div>
    <template #footer>
      <el-button :disabled="busy" @click="result ? (result = undefined) : emit('close')">{{ result ? '返回编辑' : '取消' }}</el-button>
      <el-button v-if="result" type="primary" :disabled="!result.changes.length" :loading="busy" @click="execute('apply')">确认修改</el-button>
      <el-button v-else type="primary" :disabled="!canPreview" :loading="busy" @click="execute('preview')">预览变更</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.organization-assets { display: flex; flex-direction: column; gap: 12px; }
.filters { display: grid; grid-template-columns: minmax(160px, 2fr) repeat(2, minmax(105px, 1fr)) auto; gap: 8px; }
.device-options { max-height: 240px; overflow: auto; border-block: 1px solid var(--nc-border); }
.device-option { display: grid; grid-template-columns: minmax(140px, 2fr) repeat(2, minmax(92px, 1fr)); align-items: center; gap: 8px; padding-inline: 8px; }
.device-option > * { min-width: 0; overflow-wrap: anywhere; }
.selection { display: flex; align-items: center; gap: 10px; }
@media (max-width: 680px) { .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
