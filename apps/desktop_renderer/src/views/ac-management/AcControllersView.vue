<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getAcDeployments, listAcControllers, saveAcDeployments, type AcController, type AcDeployment, type AcDeployments } from '../../api/acManagement'
import { isFeatureEnabled } from '../../features'
import { currentAppLocale } from '../../i18n/runtime'
import { apiErrorDetail } from '../../api/client'
import { SITE_CONTEXT_CHANGED_EVENT } from '../../workspace/site-switch'

const controllers = ref<AcController[]>([])
const loading = ref(false)
const error = ref('')
let generation = 0
let reader: AbortController | undefined
const deployments = ref<AcDeployments | null>(null)
const draft = ref<AcDeployment[]>([])
const editing = ref(false)
const saving = ref(false)
const local = (zh: string, en: string) => currentAppLocale() === 'en_US' ? en : zh
const modes = computed(() => ({ standalone: local('独立 AC', 'Standalone'), stack: local('堆叠', 'Stack'), cluster: local('集群', 'Cluster'), one_plus_one: '1+1' }))
function describeError(cause: unknown) {
  const code = apiErrorDetail(cause).code
  if (code === 'AC_DEPLOYMENTS_CORRUPT') return local('无线部署记录损坏', 'Wireless deployment records are damaged.')
  if (code === 'AC_SITE_CHANGED' || code === 'AC_DEPLOYMENT_CONFLICT') return local('局点或部署版本已变化，请刷新', 'The site or deployment changed. Refresh before saving.')
  return local('操作失败，请检查部署名称、类型和成员', 'Operation failed. Check the deployment name, mode, and members.')
}
const membership = computed(() => new Map((deployments.value?.groups ?? []).flatMap(
  group => group.members.map(id => [id, group] as const),
)))

function edit() {
  draft.value = (deployments.value?.groups ?? []).map(group => ({ ...group, members: [...group.members] }))
  editing.value = true
}

async function save() {
  if (!deployments.value || saving.value) return
  const request = generation
  saving.value = true
  error.value = ''
  try {
    const updated = await saveAcDeployments({ ...deployments.value, groups: draft.value })
    if (request === generation) { deployments.value = updated; editing.value = false }
  } catch (cause) {
    if (request === generation) error.value = describeError(cause)
  } finally {
    if (request === generation) saving.value = false
  }
}

async function load() {
  const request = ++generation
  reader?.abort()
  const controller = new AbortController()
  reader = controller
  controllers.value = []
  deployments.value = null
  editing.value = false
  saving.value = false
  error.value = ''
  loading.value = true
  try {
    const groups = await getAcDeployments({ signal: controller.signal })
    const rows = await listAcControllers(groups.site_id, { signal: controller.signal })
    if (generation === request) { controllers.value = rows; deployments.value = groups }
  } catch (cause) {
    if (generation === request) error.value = describeError(cause)
  } finally {
    if (generation === request) loading.value = false
  }
}

onMounted(() => {
  window.addEventListener(SITE_CONTEXT_CHANGED_EVENT, load)
  void load()
})
onUnmounted(() => {
  generation++
  reader?.abort()
  window.removeEventListener(SITE_CONTEXT_CHANGED_EVENT, load)
})
</script>

<template>
  <section class="ac-controllers">
    <header><h1>{{ local('AC 管理', 'AC management') }}</h1><div>
      <RouterLink v-if="isFeatureEnabled('capability.ac.extensions')" :to="{ name: 'ac-extensions' }">{{ local('AP 扩展信息', 'AP extensions') }}</RouterLink>
      <el-button v-if="isFeatureEnabled('capability.ac.open_management')" :disabled="!deployments" @click="edit">{{ local('登记部署关系', 'Edit deployments') }}</el-button>
      <el-button @click="load" :loading="loading">{{ local('刷新', 'Refresh') }}</el-button>
    </div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="controllers" v-loading="loading" row-key="id" height="100%" :empty-text="local('当前局点暂无 AC', 'No controllers in the current site')">
      <el-table-column prop="name" :label="local('控制器', 'Controller')" min-width="160">
        <template #default="{ row }">
          <RouterLink v-if="isFeatureEnabled('module.devices')" :to="{ name: 'device-detail', params: { deviceId: row.id } }">{{ row.name }}</RouterLink>
          <span v-else>{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="management_ip" :label="local('管理 IP', 'Management IP')" min-width="130" />
      <el-table-column prop="model" :label="local('型号', 'Model')" min-width="120" />
      <el-table-column prop="software_version" :label="local('软件版本', 'Software version')" min-width="160" show-overflow-tooltip />
      <el-table-column prop="updated_at" :label="local('采集时间', 'Collected at')" min-width="160" />
      <el-table-column :label="local('登记部署', 'Deployment')" min-width="160"><template #default="{ row }">
        {{ membership.has(row.id) ? modes[membership.get(row.id)!.mode] + ' · ' + membership.get(row.id)!.name : local('未登记', 'Unassigned') }}
      </template></el-table-column>
      <el-table-column v-if="isFeatureEnabled('module.fit_ap')" width="130">
        <template #default="{ row }"><RouterLink :to="{ name: 'ac-fit-aps', query: { ac_id: row.id } }">{{ local('FIT-AP 资源', 'FIT-AP resources') }}</RouterLink></template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="editing" :title="local('登记无线部署关系', 'Wireless deployments')" width="min(840px, 94vw)" destroy-on-close>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <div v-for="(group, index) in draft" :key="index" class="deployment">
        <el-input v-model="group.name" :aria-label="local('部署名称', 'Deployment name')" :placeholder="local('部署名称', 'Deployment name')" maxlength="80" />
        <el-select v-model="group.mode" :aria-label="local('部署方式', 'Deployment mode')"><el-option v-for="(label, mode) in modes" :key="mode" :value="mode" :label="label" /></el-select>
        <el-select v-model="group.members" multiple filterable :aria-label="local('选择控制器', 'Select controllers')" :placeholder="local('选择控制器', 'Select controllers')"><el-option v-for="ac in controllers" :key="ac.id" :value="ac.id" :label="ac.name" /></el-select>
        <el-button @click="draft.splice(index, 1)">{{ local('移除', 'Remove') }}</el-button>
      </div>
      <el-button @click="draft.push({ name: '', mode: 'standalone', members: [] })">{{ local('添加部署', 'Add deployment') }}</el-button>
      <template #footer><el-button @click="editing = false">{{ local('取消', 'Cancel') }}</el-button><el-button type="primary" :loading="saving" @click="save">{{ local('保存', 'Save') }}</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.ac-controllers { display: flex; flex-direction: column; gap: 12px; height: 100%; min-height: 0; }
.ac-controllers header { display: flex; align-items: center; justify-content: space-between; }
.ac-controllers h1 { margin: 0; }
.deployment { display: grid; gap: 8px; grid-template-columns: 1fr 110px 1.7fr auto; margin-bottom: 8px; }
@media (max-width: 620px) { .deployment { grid-template-columns: 1fr 1fr; } }
</style>
