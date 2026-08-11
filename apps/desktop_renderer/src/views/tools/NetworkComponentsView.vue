<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { FolderOpened, Refresh, RefreshLeft } from '@element-plus/icons-vue'

import { getNetworkComponents, saveNetworkComponent } from '../../api/systemSettings'
import { SETTINGS_TOOL_DEFINITIONS } from '../../../../desktop_electron/src/shared/bridge'
import { getPlatformAdapter } from '../../platform/runtime'
import { t } from '../../i18n/runtime'
import type {
  NetworkComponentMode,
  NetworkComponentName,
  NetworkComponentStatus,
  NetworkComponentsSnapshot,
} from '../../types/systemSettings'

const snapshot = ref<NetworkComponentsSnapshot | null>(null)
const loading = ref(false)
const busy = ref<NetworkComponentName | ''>('')
const error = ref('')

const components = computed(() => snapshot.value?.components ?? [])

onMounted(() => { void reload() })

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    snapshot.value = await getNetworkComponents()
  } catch (cause) {
    error.value = message(cause, t('tools.network_components.load_failed', '网络测试组件状态加载失败'))
  } finally {
    loading.value = false
  }
}

async function chooseCustom(component: NetworkComponentStatus): Promise<void> {
  busy.value = component.component_name
  try {
    const result = await getPlatformAdapter().selectSettingsTool(component.component_name)
    if (result.cancelled || !result.path || !snapshot.value) return
    snapshot.value = await saveNetworkComponent(
      component.component_name,
      'custom',
      result.path,
      snapshot.value.version,
    )
    ElMessage.success(t('tools.network_components.custom_saved', '已切换到自定义组件'))
  } catch (cause) {
    await reload()
    ElMessage.error(message(cause, t('tools.network_components.save_failed', '网络测试组件保存失败')))
  } finally {
    busy.value = ''
  }
}

async function restoreBuiltin(component: NetworkComponentStatus): Promise<void> {
  if (!snapshot.value) return
  busy.value = component.component_name
  try {
    snapshot.value = await saveNetworkComponent(
      component.component_name,
      'builtin',
      '',
      snapshot.value.version,
    )
    ElMessage.success(t('tools.network_components.builtin_restored', '已恢复使用内置组件'))
  } catch (cause) {
    await reload()
    ElMessage.error(message(cause, t('tools.network_components.restore_failed', '恢复内置组件失败')))
  } finally {
    busy.value = ''
  }
}

async function changeMode(component: NetworkComponentStatus, mode: NetworkComponentMode): Promise<void> {
  if (mode === 'builtin') await restoreBuiltin(component)
  else await chooseCustom(component)
}

function label(component: NetworkComponentName): string {
  return SETTINGS_TOOL_DEFINITIONS[component].displayName
}

function sourceLabel(component: NetworkComponentStatus): string {
  return component.source === 'builtin'
    ? t('tools.network_components.source_builtin', '内置组件（推荐）')
    : t('tools.network_components.source_custom', '自定义组件')
}

function statusLabel(component: NetworkComponentStatus): string {
  if (!component.available) return t('tools.network_components.status_unavailable', '组件不可用')
  if (component.fallback_used) return t('tools.network_components.status_fallback', '自定义组件不可用，已回退到内置组件')
  return component.source === 'builtin'
    ? t('tools.network_components.status_builtin', '正在使用内置组件')
    : t('tools.network_components.status_custom', '正在使用自定义组件')
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
</script>

<template>
  <section class="network-components-page">
    <header class="page-heading">
      <div>
        <h1>{{ t('tools.network_components.title', '网络测试组件') }}</h1>
        <p>{{ t('tools.network_components.subtitle', '统一管理流量测试与连通性检测使用的 iperf3、fping 组件。') }}</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="reload">{{ t('common.refresh', '刷新') }}</el-button>
    </header>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <div v-loading="loading" class="component-list">
      <article v-for="component in components" :key="component.component_name" class="component-row">
        <div class="component-heading">
          <div>
            <h2>{{ label(component.component_name) }}</h2>
            <span class="component-status" :class="{ 'is-warning': component.fallback_used, 'is-error': !component.available }">
              {{ statusLabel(component) }}
            </span>
          </div>
          <el-tag :type="component.available ? (component.fallback_used ? 'warning' : 'success') : 'danger'" effect="plain">
            {{ sourceLabel(component) }}
          </el-tag>
        </div>

        <dl class="component-details">
          <div><dt>{{ t('tools.network_components.effective_path', '当前有效路径') }}</dt><dd>{{ component.effective_path || t('common.unavailable', '不可用') }}</dd></div>
          <div><dt>{{ t('tools.network_components.file_status', '文件状态') }}</dt><dd>{{ component.file_exists ? t('tools.network_components.file_exists', '文件存在') : t('tools.network_components.file_missing', '文件不存在') }}</dd></div>
          <div v-if="component.fallback_used" class="fallback-message"><dt>{{ t('tools.network_components.fallback_reason', '回退原因') }}</dt><dd>{{ component.fallback_reason }}</dd></div>
          <div v-else-if="!component.available" class="fallback-message"><dt>{{ t('tools.network_components.validation', '校验信息') }}</dt><dd>{{ component.validation_message }}</dd></div>
        </dl>

        <div class="component-actions">
          <el-radio-group :model-value="component.mode" :disabled="busy === component.component_name" @change="(value: NetworkComponentMode) => changeMode(component, value)">
            <el-radio-button value="builtin">{{ t('tools.network_components.use_builtin', '使用内置组件') }}</el-radio-button>
            <el-radio-button value="custom">{{ t('tools.network_components.use_custom', '使用自定义组件') }}</el-radio-button>
          </el-radio-group>
          <el-button :icon="FolderOpened" :loading="busy === component.component_name" @click="chooseCustom(component)">{{ t('tools.network_components.choose_custom', '选择自定义组件') }}</el-button>
          <el-button :icon="RefreshLeft" :loading="busy === component.component_name" @click="restoreBuiltin(component)">{{ t('tools.network_components.restore_builtin', '恢复内置组件') }}</el-button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.network-components-page { display: flex; flex-direction: column; gap: 16px; min-height: 100%; padding: 20px 24px 28px; box-sizing: border-box; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-heading h1 { margin: 0 0 6px; }
.page-heading p { margin: 0; color: var(--el-text-color-secondary); }
.component-list { display: grid; gap: 12px; }
.component-row { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 18px 20px; background: var(--el-bg-color); }
.component-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.component-heading h2 { margin: 0 0 4px; font-size: 18px; }
.component-status { color: var(--el-color-success); font-size: 13px; }
.component-status.is-warning { color: var(--el-color-warning); }
.component-status.is-error { color: var(--el-color-danger); }
.component-details { display: grid; gap: 8px; margin: 16px 0; }
.component-details > div { display: grid; grid-template-columns: minmax(110px, 140px) 1fr; gap: 12px; min-width: 0; }
.component-details dt { color: var(--el-text-color-secondary); }
.component-details dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.fallback-message dd { color: var(--el-color-warning); }
.component-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
@media (max-width: 700px) {
  .network-components-page { padding: 16px; }
  .page-heading { flex-direction: column; }
  .component-details > div { grid-template-columns: 1fr; gap: 2px; }
}
</style>
