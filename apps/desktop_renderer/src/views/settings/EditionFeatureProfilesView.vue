<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage } from 'element-plus'

import {
  autoFixFeatureSettings,
  checkFeatureSettings,
  exitFeatureSettingsPreview,
  getFeatureSettings,
  previewFeatureSettings,
  restoreFeatureSettings,
  saveFeatureSettings,
} from '../../api/systemSettings'
import {
  getHealth,
  getRendererBuildMeta,
  type HealthResponse,
  type RendererBuildMeta,
} from '../../api/client'
import { loadRendererFeatures } from '../../features'
import { visibleVersionIdentity } from '../../platform/buildIdentity'
import { useConfirm } from '../../components/feedback/useConfirm'
import type {
  FeatureConfigurationTarget,
  FeatureSetting,
  FeatureSettingsSnapshot,
} from '../../types/systemSettings'


type ProfileTarget = Exclude<FeatureConfigurationTarget, 'runtime'>
type FeatureMode = 'enabled_visible' | 'enabled_hidden' | 'disabled'
type CustomerState = 'not_delivered' | 'delivered_visible' | 'delivered_hidden'

const { confirm } = useConfirm()
const target = ref<ProfileTarget>('customer')
const snapshot = ref<FeatureSettingsSnapshot | null>(null)
const features = ref<FeatureSetting[]>([])
const baseline = ref('')
const search = ref('')
const groupFilter = ref('all')
const modifiedOnly = ref(false)
const activeGroups = ref<string[]>([])
const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const error = ref('')
const buildIdentity = ref<HealthResponse | null>(null)
const rendererBuildIdentity = ref<RendererBuildMeta | null>(null)

const dirty = computed(() => JSON.stringify(features.value) !== baseline.value)
const baselineFeatures = computed<FeatureSetting[]>(() => (
  baseline.value ? JSON.parse(baseline.value) as FeatureSetting[] : []
))
const baselineById = computed(() => new Map(
  baselineFeatures.value.map((item) => [item.feature_id, item]),
))
const groups = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  const result = new Map<string, { id: string; title: string; items: FeatureSetting[] }>()
  for (const item of features.value) {
    if (item.configuration_layer === 'technical') continue
    if (groupFilter.value !== 'all' && item.group_id !== groupFilter.value) continue
    if (keyword && !`${item.title} ${item.feature_id}`.toLocaleLowerCase().includes(keyword)) continue
    if (modifiedOnly.value && !isModified(item)) continue
    const group = result.get(item.group_id) ?? {
      id: item.group_id,
      title: item.group_title,
      items: [],
    }
    group.items.push(item)
    result.set(item.group_id, group)
  }
  return [...result.values()]
})
const groupOptions = computed(() => [...new Map(
  features.value
    .filter((item) => item.configuration_layer !== 'technical')
    .map((item) => [item.group_id, item.group_title]),
).entries()])
const technicalFeatures = computed(() => features.value.filter((item) => item.configuration_layer === 'technical'))
const dependencyIssues = computed(() => snapshot.value?.dependency_issues ?? [])
const dependencyIssueGroups = computed(() => [...new Map(
  dependencyIssues.value.map((issue) => [issue.dependency_id, {
    dependencyId: issue.dependency_id,
    dependencyTitle: issue.dependency_title,
    issues: dependencyIssues.value.filter((candidate) => candidate.dependency_id === issue.dependency_id),
  }]),
).values()])
const changedCount = computed(() => features.value.filter(isModified).length)
const includedCount = computed(() => features.value.filter((item) => Boolean(item.package_included)).length)

const visibleBuildVersion = computed(() => (
  rendererBuildIdentity.value
    ? `v${visibleVersionIdentity(rendererBuildIdentity.value.app_version, rendererBuildIdentity.value.build_id)}`
    : import.meta.env.DEV && buildIdentity.value
      ? `v${visibleVersionIdentity(buildIdentity.value.version, buildIdentity.value.build_id)}`
    : '--'
))
const buildIdentityMismatch = computed(() => Boolean(
  buildIdentity.value
  && rendererBuildIdentity.value
  && buildIdentity.value.build_id !== rendererBuildIdentity.value.build_id,
))

onMounted(() => {
  void loadTarget('customer')
  void loadBuildIdentity()
})
onBeforeRouteLeave(async () => {
  if (dirty.value && !await confirm({
    type: 'WARNING',
    title: '模板尚未保存',
    message: '离开页面将放弃当前未保存修改，是否继续？',
    confirmText: '放弃并离开',
  })) return false
  await stopPreviewSilently()
  return true
})

async function selectTarget(value: string | number | boolean | undefined): Promise<void> {
  const next = String(value) as ProfileTarget
  if (next === target.value) return
  if (dirty.value && !await confirm({
    type: 'WARNING',
    title: '模板尚未保存',
    message: '切换版本将放弃当前未保存修改，是否继续？',
    confirmText: '放弃并切换',
  })) return
  await stopPreviewSilently()
  target.value = next
  await loadTarget(next)
}

async function loadTarget(selected: ProfileTarget): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    accept(await getFeatureSettings(selected))
    activeGroups.value = []
  } catch (cause) {
    error.value = message(cause, '版本功能模板加载失败')
  } finally {
    loading.value = false
  }
}

async function loadBuildIdentity(): Promise<void> {
  const [health, renderer] = await Promise.allSettled([
    getHealth(),
    getRendererBuildMeta(),
  ])
  buildIdentity.value = health.status === 'fulfilled' ? health.value : null
  rendererBuildIdentity.value = renderer.status === 'fulfilled' ? renderer.value : null
}

function accept(data: FeatureSettingsSnapshot, updateBaseline = true): void {
  snapshot.value = data
  features.value = normalizeItems(data.items)
  if (updateBaseline) baseline.value = JSON.stringify(features.value)
  previewing.value = data.preview_active
}

function normalizeItems(items: FeatureSetting[]): FeatureSetting[] {
  return items.map((item) => ({
    ...item,
    package_included: Boolean(item.package_included ?? item.client_package),
    package_editable: Boolean(item.package_editable),
  }))
}

async function save(): Promise<void> {
  if (!dirty.value || dependencyIssues.value.length || previewing.value) return
  const label = target.value === 'customer' ? '客户版' : '完整版'
  if (!await confirm({
    type: 'WARNING',
    title: `保存${label}打包模板`,
    message: `本次操作只修改 ${target.value}.json，不会立即改变当前运行界面。是否保存？`,
    confirmText: '保存模板',
  })) return
  saving.value = true
  try {
    accept(await saveFeatureSettings(features.value, target.value))
    ElMessage.success(`${label}功能模板已保存，下次打包时生效`)
  } catch (cause) {
    error.value = message(cause, '版本功能模板保存失败')
    ElMessage.error(error.value)
  } finally {
    saving.value = false
  }
}

async function preview(): Promise<void> {
  if (dependencyIssues.value.length || previewing.value) return
  if (!await confirm({
    type: 'WARNING',
    title: '会话预览版本模板',
    message: '预览会临时改变当前进程的导航和接口 Gate，但不会写入模板；重启后自动恢复。是否继续？',
    confirmText: '开始预览',
  })) return
  try {
    const response = await previewFeatureSettings(features.value, target.value)
    snapshot.value = response
    previewing.value = true
    await loadRendererFeatures(true)
    ElMessage.success('版本模板已进入会话预览；草稿仍保持未保存状态')
  } catch (cause) {
    error.value = message(cause, '会话预览失败')
    ElMessage.error(error.value)
  }
}

async function exitPreview(): Promise<void> {
  try {
    const response = await exitFeatureSettingsPreview(target.value)
    snapshot.value = response
    previewing.value = false
    await loadRendererFeatures(true)
    ElMessage.success('已退出版本模板预览；未保存草稿仍然保留')
  } catch (cause) {
    error.value = message(cause, '退出会话预览失败')
    ElMessage.error(error.value)
  }
}

async function stopPreviewSilently(): Promise<void> {
  if (!previewing.value) return
  try {
    await exitFeatureSettingsPreview(target.value)
    await loadRendererFeatures(true)
  } finally {
    previewing.value = false
  }
}

async function restoreDefaults(): Promise<void> {
  if (previewing.value) {
    ElMessage.warning('请先退出会话预览')
    return
  }
  const label = target.value === 'customer' ? '客户版' : '完整版'
  if (!await confirm({
    type: 'WARNING',
    title: `恢复${label}注册表默认值`,
    message: `这会覆盖当前 ${target.value}.json 模板，是否继续？`,
    confirmText: '恢复默认',
  })) return
  try {
    accept(await restoreFeatureSettings(target.value))
    ElMessage.success(`${label}模板已恢复注册表默认值`)
  } catch (cause) {
    error.value = message(cause, '恢复默认模板失败')
    ElMessage.error(error.value)
  }
}

async function runDependencyCheck(showSuccess = true): Promise<void> {
  try {
    accept(await checkFeatureSettings(features.value, target.value), false)
    if (!showSuccess) return
    if (dependencyIssues.value.length) {
      ElMessage.warning(`发现 ${dependencyIssues.value.length} 项依赖问题`)
    } else {
      ElMessage.success('构建前检查通过')
    }
  } catch (cause) {
    error.value = message(cause, '依赖检查失败')
    ElMessage.error(error.value)
  }
}

async function autoFixDependencies(showSuccess = true): Promise<void> {
  try {
    accept(await autoFixFeatureSettings(features.value, target.value), false)
    if (showSuccess) ElMessage.success('已在当前草稿中自动补齐依赖，保存后才会写入模板')
  } catch (cause) {
    error.value = message(cause, '依赖自动修复失败')
    ElMessage.error(error.value)
  }
}

function undo(): void {
  if (!baseline.value || previewing.value) return
  features.value = JSON.parse(baseline.value) as FeatureSetting[]
  void runDependencyCheck(false)
}

function featureMode(item: FeatureSetting): FeatureMode {
  if (!item.enabled) return 'disabled'
  return item.visible ? 'enabled_visible' : 'enabled_hidden'
}

async function setFeatureMode(item: FeatureSetting, value: string | number | boolean | undefined): Promise<void> {
  if (item.locked || previewing.value) return
  const mode = String(value) as FeatureMode
  if (mode === 'disabled') {
    const dependents = enabledDependents(item.feature_id)
    if (dependents.length && !await confirm({
      type: 'WARNING',
      title: '联动禁用依赖功能',
      message: `禁用“${item.title}”将同时禁用 ${dependents.map((candidate) => candidate.title).join('、')}。是否继续？`,
      confirmText: '联动禁用',
    })) return
    for (const dependent of dependents) disable(dependent)
    disable(item)
    await runDependencyCheck(false)
    return
  }

  item.enabled = true
  item.visible = mode === 'enabled_visible'
  await autoFixDependencies(false)
}

function customerState(item: FeatureSetting): CustomerState {
  if (!item.package_included) return 'not_delivered'
  return item.visible ? 'delivered_visible' : 'delivered_hidden'
}

async function setCustomerState(item: FeatureSetting, value: string | number | boolean | undefined): Promise<void> {
  if (target.value !== 'customer' || item.package_editable !== true || previewing.value) return
  const state = String(value) as CustomerState
  if (state === 'not_delivered') {
    const dependents = customerDependents(item.feature_id)
    if (dependents.length && !await confirm({
      type: 'WARNING',
      title: '移出客户版',
      message: `移出“${item.title}”将同时移出 ${dependents.map((candidate) => candidate.title).join('、')}。是否继续？`,
      confirmText: '联动移出',
    })) return
    for (const dependent of dependents) excludeFromCustomer(dependent)
    excludeFromCustomer(item)
    await runDependencyCheck(false)
    return
  }
  item.package_included = true
  item.enabled = true
  item.visible = state === 'delivered_visible'
  await autoFixDependencies(false)
}

function disable(item: FeatureSetting): void {
  item.enabled = false
  item.visible = false
}

function excludeFromCustomer(item: FeatureSetting): void {
  item.package_included = false
  disable(item)
}

function enabledDependents(featureId: string): FeatureSetting[] {
  return transitiveDependents(featureId, (candidate) => candidate.enabled)
}

function customerDependents(featureId: string): FeatureSetting[] {
  return transitiveDependents(featureId, (candidate) => Boolean(candidate.package_included), true)
}

function transitiveDependents(
  featureId: string,
  predicate: (candidate: FeatureSetting) => boolean,
  delivery = false,
): FeatureSetting[] {
  const result: FeatureSetting[] = []
  const queue = [featureId]
  const seen = new Set(queue)
  while (queue.length) {
    const current = queue.shift()!
    for (const candidate of features.value) {
      const linked = candidate.dependencies.includes(current)
        || (delivery && (candidate.delivery_dependencies.includes(current) || candidate.parent_id === current))
      if (seen.has(candidate.feature_id) || !predicate(candidate) || !linked) continue
      seen.add(candidate.feature_id)
      result.push(candidate)
      queue.push(candidate.feature_id)
    }
  }
  return result
}

function isModified(item: FeatureSetting): boolean {
  const original = baselineById.value.get(item.feature_id)
  return Boolean(original && (
    original.visible !== item.visible
    || original.enabled !== item.enabled
    || Boolean(original.package_included) !== Boolean(item.package_included)
  ))
}

function groupSummary(items: FeatureSetting[]): string {
  const enabled = items.filter((item) => item.enabled).length
  if (target.value === 'customer') {
    const included = items.filter((item) => Boolean(item.package_included)).length
    return `客户版 ${included}/${items.length} · 启用 ${enabled}`
  }
  return `启用 ${enabled}/${items.length}`
}

function statusLabel(status: FeatureSetting['status']): string {
  return status === 'ENABLED' ? '正式' : status === 'DEVELOPMENT' ? '开发中' : status === 'HIDDEN' ? '隐藏' : '停用'
}

function statusType(status: FeatureSetting['status']): 'success' | 'warning' | 'info' | 'danger' {
  return status === 'ENABLED' ? 'success' : status === 'DEVELOPMENT' ? 'warning' : status === 'DISABLED' ? 'danger' : 'info'
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
</script>

<template>
  <section class="profile-page" v-loading="loading">
    <header class="page-header">
      <div>
        <h1>版本与功能交付</h1>
        <p>唯一功能矩阵入口；正式模板持久化，会话预览仅影响当前进程。</p>
      </div>
      <div class="header-actions">
        <el-tag v-if="dirty" type="warning">{{ changedCount }} 项未保存</el-tag>
        <el-button :disabled="!dirty || previewing" @click="undo">撤销修改</el-button>
        <el-button :disabled="previewing" @click="restoreDefaults">恢复默认</el-button>
        <el-button data-testid="profile-preflight" :disabled="previewing" @click="runDependencyCheck()">构建前检查</el-button>
        <el-button type="primary" :loading="saving" :disabled="!dirty || previewing || Boolean(dependencyIssues.length)" @click="save">保存模板</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert
      v-if="snapshot"
      :title="snapshot.save_effect || '保存模板只影响下次打包，不会立即改变当前运行界面。'"
      :type="snapshot.applies_immediately ? 'warning' : 'info'"
      :closable="false"
      show-icon
    />

    <section class="profile-card build-identity" data-testid="build-identity">
      <div><span>当前构建</span><strong>{{ visibleBuildVersion }}</strong></div>
      <div><span>Backend 完整提交</span><code>{{ buildIdentity?.backend_commit || '--' }}</code></div>
      <div><span>Frontend 完整提交</span><code>{{ rendererBuildIdentity?.git_commit_full || '--' }}</code></div>
      <div><span>版本类型</span><strong>{{ buildIdentity?.edition || '--' }}</strong></div>
      <div><span>正式包状态</span><strong>{{ buildIdentity?.packaged_dirty === false ? 'clean' : buildIdentity?.packaged_dirty === true ? 'dirty' : '--' }}</strong></div>
      <div><span>构建时间（UTC）</span><code>{{ buildIdentity?.build_timestamp || '--' }}</code></div>
    </section>
    <el-alert
      v-if="buildIdentityMismatch"
      :title="`Renderer ${rendererBuildIdentity?.build_id} 与 Backend ${buildIdentity?.build_id} 不一致，请重新安装完整版本。`"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="previewing"
      title="当前处于会话预览：只影响本次进程，未写入打包模板；草稿仍保持未保存状态。"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="dependencyIssues.length"
      :title="`存在 ${dependencyIssueGroups.length} 组、${dependencyIssues.length} 项依赖问题，修复后才能保存或预览。`"
      type="error"
      :closable="false"
    />

    <section v-if="dependencyIssues.length" class="profile-card dependency-panel">
      <div class="dependency-heading">
        <strong>依赖检查</strong>
        <el-button
          data-testid="auto-fix-dependencies"
          type="primary"
          plain
          :disabled="!dependencyIssues.some((issue) => issue.auto_fix) || previewing"
          @click="autoFixDependencies()"
        >自动修复依赖</el-button>
      </div>
      <article v-for="group in dependencyIssueGroups" :key="group.dependencyId">
        <strong>{{ group.dependencyTitle }}</strong>
        <code>{{ group.dependencyId }}</code>
        <p>被以下功能需要：</p>
        <ul><li v-for="issue in group.issues" :key="`${issue.feature_id}-${issue.issue_type}`">{{ issue.feature_title }}</li></ul>
      </article>
    </section>

    <section class="profile-card">
      <div class="profile-selector">
        <el-radio-group :model-value="target" :disabled="previewing" @change="selectTarget">
          <el-radio-button value="customer">客户版交付配置</el-radio-button>
          <el-radio-button value="full">完整版默认配置</el-radio-button>
        </el-radio-group>
        <div class="profile-facts">
          <span>当前模板：<strong>{{ snapshot?.configuration_name || '--' }}</strong></span>
          <span v-if="target === 'customer'">已交付：<strong>{{ includedCount }}</strong></span>
          <span>修改项：<strong>{{ changedCount }}</strong></span>
        </div>
      </div>
      <p class="profile-help" v-if="target === 'customer'">
        客户版状态统一表示是否交付以及入口是否显示；技术依赖由 Backend 自动以“交付但隐藏”补齐。
      </p>
      <p class="profile-help" v-else>
        完整版模板控制完整版首次启动时的显示与启用状态；不改变客户版模板。
      </p>
    </section>

    <section class="profile-card">
      <div class="filters">
        <el-input v-model="search" clearable placeholder="搜索功能名称或 Feature ID" />
        <el-select v-model="groupFilter">
          <el-option label="全部业务分类" value="all" />
          <el-option v-for="[id, title] in groupOptions" :key="id" :label="title" :value="id" />
        </el-select>
        <el-switch v-model="modifiedOnly" active-text="仅显示已修改" />
      </div>

      <el-empty v-if="!groups.length" description="没有匹配的功能" />
      <el-collapse v-else v-model="activeGroups" class="feature-groups">
        <el-collapse-item v-for="group in groups" :key="group.id" :name="group.id">
          <template #title>
            <span class="group-title">{{ group.title }}</span>
            <el-tag size="small" type="info">{{ groupSummary(group.items) }}</el-tag>
          </template>
          <el-table :data="group.items" row-key="feature_id" max-height="520" border>
            <el-table-column label="功能" min-width="230" fixed="left">
              <template #default="{ row }">
                <div class="feature-title">
                  <strong>{{ row.title }} <el-tag v-if="row.configuration_layer === 'business'" size="small" type="info">业务入口</el-tag></strong>
                  <code>{{ row.feature_id }}</code>
                  <small v-if="row.lock_reason">{{ row.lock_reason }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="成熟度" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="target === 'customer' ? '客户版状态' : '完整版状态'" width="190" align="center" fixed="right">
              <template #default="{ row }">
                <el-select
                  v-if="target === 'customer'"
                  :model-value="customerState(row)"
                  :data-testid="`customer-state-${row.feature_id}`"
                  :disabled="row.package_editable !== true || previewing"
                  @change="setCustomerState(row, $event)"
                >
                  <el-option label="不交付" value="not_delivered" />
                  <el-option label="交付并显示" value="delivered_visible" />
                  <el-option label="交付但隐藏" value="delivered_hidden" />
                </el-select>
                <el-select
                  v-else
                  :model-value="featureMode(row)"
                  :disabled="row.locked || previewing"
                  @change="setFeatureMode(row, $event)"
                >
                  <el-option label="显示并启用" value="enabled_visible" />
                  <el-option label="隐藏入口但保留能力" value="enabled_hidden" />
                  <el-option label="完全禁用" value="disabled" />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </section>

    <section class="profile-card">
      <el-collapse>
        <el-collapse-item name="technical">
          <template #title>
            <span class="group-title">技术能力</span>
            <el-tag size="small" type="info">{{ technicalFeatures.length }} 项 · 只读</el-tag>
          </template>
          <el-table :data="technicalFeatures" row-key="feature_id" max-height="420" border>
            <el-table-column label="技术能力" min-width="260">
              <template #default="{ row }"><div class="feature-title"><strong>{{ row.title }}</strong><code>{{ row.feature_id }}</code></div></template>
            </el-table-column>
            <el-table-column label="运行状态" width="120" align="center">
              <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '关闭' }}</el-tag></template>
            </el-table-column>
            <el-table-column v-if="target === 'customer'" label="交付状态" width="140" align="center">
              <template #default="{ row }"><el-tag :type="row.package_included ? 'success' : 'info'" size="small">{{ row.package_included ? '交付但隐藏' : '不交付' }}</el-tag></template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </section>

    <section class="profile-card">
      <el-collapse>
        <el-collapse-item name="preview">
          <template #title>
            <span class="group-title">当前会话预览</span>
            <el-tag v-if="previewing" size="small" type="warning">预览中</el-tag>
          </template>
          <div class="preview-actions">
            <span>不持久化，立即检查当前草稿在导航、路由和 Backend Gate 中的实际效果。</span>
            <el-button :disabled="Boolean(dependencyIssues.length) || previewing" @click="preview">开始预览</el-button>
            <el-button v-if="previewing" type="warning" @click="exitPreview">退出预览</el-button>
          </div>
        </el-collapse-item>
      </el-collapse>
    </section>
  </section>
</template>

<style scoped>
.profile-page{display:flex;flex-direction:column;gap:16px;max-width:1680px;margin:0 auto}.page-header,.header-actions,.profile-selector,.profile-facts,.filters,.dependency-heading,.preview-actions{display:flex;align-items:center;gap:12px}.page-header,.profile-selector,.dependency-heading{justify-content:space-between}.page-header h1{margin:0}.page-header p,.profile-help{margin:6px 0 0;color:var(--nc-text-secondary)}.header-actions,.profile-facts{flex-wrap:wrap;justify-content:flex-end}.profile-card{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.build-identity{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 20px}.build-identity div{display:flex;min-width:0;flex-direction:column;gap:5px}.build-identity span{color:var(--nc-text-secondary);font-size:12px}.build-identity code{overflow-wrap:anywhere;font-family:Consolas,"Courier New",monospace}.filters{display:grid;grid-template-columns:minmax(280px,1fr) 240px auto;margin-bottom:16px}.feature-groups{border-top:1px solid var(--el-border-color-light)}.group-title{margin-right:10px;font-weight:600}.feature-title{display:flex;min-width:0;flex-direction:column;align-items:flex-start;gap:4px}.feature-title code,.dependency-panel code{max-width:100%;overflow:hidden;color:var(--nc-text-secondary);font-family:Consolas,"Courier New",monospace;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.feature-title small{color:var(--el-color-warning);font-size:12px}.dependency-panel{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.dependency-heading{grid-column:1/-1}.dependency-panel article{min-width:0;padding:12px;border-left:3px solid var(--el-color-danger);background:var(--el-fill-color-light)}.dependency-panel article strong,.dependency-panel article code{display:block}.dependency-panel article p{margin:10px 0 4px;color:var(--nc-text-secondary)}.dependency-panel article ul{margin:0;padding-left:20px}.preview-actions{justify-content:flex-end;flex-wrap:wrap}.preview-actions span{margin-right:auto;color:var(--nc-text-secondary)}@media(max-width:900px){.page-header,.profile-selector{align-items:flex-start;flex-direction:column}.header-actions,.profile-facts{justify-content:flex-start}.build-identity,.filters,.dependency-panel{grid-template-columns:1fr}}
</style>
