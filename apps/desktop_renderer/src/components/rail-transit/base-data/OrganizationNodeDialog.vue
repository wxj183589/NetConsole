<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  getOrganizationCatalog,
  saveOrganizationNode,
  type InfrastructureNode,
  type OrganizationNodeEdit,
  type OrganizationNodeKind,
} from '../../../api/railInfrastructure'
import { nodeLabel } from './infrastructurePresentation'

const props = defineProps<{ siteId: string; nodes: InfrastructureNode[]; current?: InfrastructureNode; editing: boolean }>()
const emit = defineEmits<{ close: []; saved: [uid: string] }>()
const kindOptions: { kind: OrganizationNodeKind; label: string }[] = [
  { kind: 'cocc', label: 'COCC' }, { kind: 'bocc', label: 'BOCC' },
  { kind: 'station', label: '正线车站' }, { kind: 'depot', label: '车辆段' },
  { kind: 'parking_yard', label: '停车场' },
]
const current = props.current
const currentKind = kindOptions.find(option => option.kind === current?.kind)?.kind
const draft = reactive<OrganizationNodeEdit>({
  node_uid: props.editing ? current?.uid ?? '' : '',
  parent_uid: props.editing ? current?.parent_uid ?? '' : currentKind ? current?.uid ?? '' : '',
  kind: currentKind ?? 'station',
  name: props.editing ? current?.name ?? '' : '',
  code: props.editing ? current?.code ?? '' : '',
  sort_order: props.editing ? current?.sort_order ?? 0 : 0,
})
const parents = computed(() => props.nodes.filter(node => node.kind === draft.kind && node.uid !== draft.node_uid && node.source === 'engineering'))
const revision = ref('')
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    revision.value = (await getOrganizationCatalog(props.siteId)).revision
  } catch {
    error.value = '组织当前修订不可用'
  }
})

async function save() {
  if (busy.value || !revision.value || !draft.name.trim()) return
  busy.value = true
  error.value = ''
  try {
    const saved = await saveOrganizationNode(props.siteId, { ...draft, parent_uid: draft.parent_uid || '' }, revision.value)
    emit('saved', saved.node_uid)
  } catch (issue) {
    error.value = issue instanceof Error ? issue.message : '组织保存失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="true" :title="editing ? '编辑组织' : '新增组织'" width="min(470px, 95vw)"
    :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @close="emit('close')">
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <el-form label-width="85px" @submit.prevent="save">
      <el-form-item label="组织类型">
        <el-select v-model="draft.kind" :disabled="editing" @change="draft.parent_uid = ''">
          <el-option v-for="choice in kindOptions" :key="choice.kind" :label="choice.label" :value="choice.kind" />
        </el-select>
      </el-form-item>
      <el-form-item label="上级组织">
        <el-select v-model="draft.parent_uid" filterable clearable placeholder="线路直属">
          <el-option v-for="parent in parents" :key="parent.uid" :label="nodeLabel(parent)" :value="parent.uid" />
        </el-select>
      </el-form-item>
      <el-form-item label="组织名称"><el-input v-model="draft.name" :maxlength="120" /></el-form-item>
      <el-form-item label="组织编号"><el-input v-model="draft.code" :maxlength="50" /></el-form-item>
      <el-form-item label="排序"><el-input-number v-model="draft.sort_order" :min="-10000" :max="10000" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="busy" @click="emit('close')">取消</el-button>
      <el-button type="primary" :disabled="!revision || !draft.name.trim()" :loading="busy" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
