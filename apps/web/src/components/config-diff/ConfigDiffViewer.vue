<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { t } from '../../i18n/runtime'
import ConfigMonacoDiff from './ConfigMonacoDiff.vue'
import {
  configDiffNavigationTargets,
  correctConfigDiffChangeIndex,
  exceedsMonacoDiffLimit,
  filteredConfigDiffRows,
  nextConfigDiffChangeIndex,
} from './configDiffNavigation'
import type { ConfigDiffFilter, SharedConfigDiffModel } from './configDiffTypes'

const props = defineProps<{ model: SharedConfigDiffModel }>()
type MonacoDiffExposed = {
  revealDifference: (originalLine: number | null, modifiedLine: number | null) => void
}

const viewMode = ref<'visual' | 'details'>('visual')
const renderSideBySide = ref(true)
const wordWrap = ref(false)
const filter = ref<ConfigDiffFilter>('all')
const currentChange = ref(0)
const monacoError = ref('')
const viewport = ref<HTMLElement | null>(null)
const monacoRef = ref<MonacoDiffExposed | null>(null)

const rows = computed(() => props.model.rows || [])
const filteredRows = computed(() => filteredConfigDiffRows(rows.value, filter.value))
const navigation = computed(() => configDiffNavigationTargets(rows.value, filter.value))
const changeCount = computed(() => navigation.value.length)
const limitExceeded = computed(() => exceedsMonacoDiffLimit(props.model))
const fallbackMessage = computed(() => {
  if (monacoError.value) return monacoError.value
  if (limitExceeded.value) {
    return t('config_diff.monaco_too_large', '配置内容过大，已切换为结构化差异明细。')
  }
  return ''
})

watch(
  () => props.model.comparisonId,
  () => {
    viewMode.value = limitExceeded.value ? 'details' : 'visual'
    renderSideBySide.value = true
    wordWrap.value = false
    filter.value = 'all'
    currentChange.value = 0
    monacoError.value = ''
  },
  { immediate: true },
)

async function scrollToCurrent(): Promise<void> {
  await nextTick()
  currentChange.value = correctConfigDiffChangeIndex(currentChange.value, changeCount.value)
  const target = navigation.value[currentChange.value]
  if (viewMode.value === 'visual' && target && monacoRef.value) {
    monacoRef.value.revealDifference(target.originalLine, target.modifiedLine)
    return
  }
  viewport.value?.querySelectorAll<HTMLElement>('[data-diff-change="true"]')
    [currentChange.value]?.scrollIntoView({ block: 'center' })
}

function changeView(value: 'visual' | 'details'): void {
  if (value === 'visual' && fallbackMessage.value) return
  viewMode.value = value
  void scrollToCurrent()
}

function changeFilter(value: ConfigDiffFilter): void {
  filter.value = value
  currentChange.value = 0
  void scrollToCurrent()
}

function move(step: -1 | 1): void {
  currentChange.value = nextConfigDiffChangeIndex(currentChange.value, changeCount.value, step)
  void scrollToCurrent()
}

function handleMonacoError(message: string): void {
  monacoError.value = message
  viewMode.value = 'details'
  void scrollToCurrent()
}
</script>

<template>
  <section class="config-diff-viewer">
    <div class="diff-summary">
      新增 {{ model.summary.added }} · 删除 {{ model.summary.removed }} · 修改块 {{ model.summary.modified }}
      <span v-if="model.truncated"> · 基础差异文本已截断</span>
    </div>
    <div class="result-toolbar" aria-label="配置差异视图工具栏">
      <el-button-group>
        <el-button :type="viewMode === 'visual' ? 'primary' : 'default'" :disabled="Boolean(fallbackMessage)" @click="changeView('visual')">{{ t('config_diff.visual', '可视化对比') }}</el-button>
        <el-button :type="viewMode === 'details' ? 'primary' : 'default'" @click="changeView('details')">{{ t('config_diff.details', '差异明细') }}</el-button>
      </el-button-group>
      <el-button-group v-if="viewMode === 'visual'">
        <el-button :type="renderSideBySide ? 'primary' : 'default'" @click="renderSideBySide = true">{{ t('config_diff.side_by_side', '并排') }}</el-button>
        <el-button :type="!renderSideBySide ? 'primary' : 'default'" @click="renderSideBySide = false">{{ t('config_diff.inline', '内联') }}</el-button>
      </el-button-group>
      <el-checkbox v-if="viewMode === 'visual'" v-model="wordWrap">{{ t('config_diff.word_wrap', '自动换行') }}</el-checkbox>
      <el-select v-if="viewMode === 'details'" :model-value="filter" size="small" @update:model-value="changeFilter">
        <el-option :label="t('config_diff.filter_all', '全部行')" value="all" />
        <el-option :label="t('config_diff.filter_added', '仅新增')" value="added" />
        <el-option :label="t('config_diff.filter_removed', '仅删除')" value="removed" />
        <el-option :label="t('config_diff.filter_modified', '仅修改')" value="modified" />
      </el-select>
      <div class="diff-navigation">
        <el-button :disabled="!changeCount" @click="move(-1)">{{ t('config_diff.previous', '上一处差异') }}</el-button>
        <span>{{ changeCount ? currentChange + 1 : 0 }} / {{ changeCount }}</span>
        <el-button :disabled="!changeCount" @click="move(1)">{{ t('config_diff.next', '下一处差异') }}</el-button>
      </div>
    </div>
    <el-alert v-if="fallbackMessage" :title="fallbackMessage" type="warning" :closable="false" show-icon class="fallback-alert diff-fallback-alert" />
    <ConfigMonacoDiff
      v-if="viewMode === 'visual' && !fallbackMessage"
      ref="monacoRef"
      :original-text="model.original.content"
      :modified-text="model.modified.content"
      :original-label="model.original.label"
      :modified-label="model.modified.label"
      :comparison-id="model.comparisonId"
      :render-side-by-side="renderSideBySide"
      :word-wrap="wordWrap"
      @ready="scrollToCurrent"
      @initialization-error="handleMonacoError"
    />
    <div v-else-if="rows.length" ref="viewport" class="diff-table" role="table" aria-label="配置差异双栏视图">
      <div class="diff-row diff-header" role="row"><span>#</span><strong>{{ model.original.label }}</strong><span>状态</span><span>#</span><strong>{{ model.modified.label }}</strong></div>
      <div
        v-for="(row, index) in filteredRows"
        :key="`${row.originalLine}-${row.modifiedLine}-${index}`"
        class="diff-row"
        :class="`is-${row.status}`"
        :data-diff-change="row.status !== 'equal' ? 'true' : 'false'"
        role="row"
      >
        <span class="line-number">{{ row.originalLine ?? '' }}</span><code>{{ row.originalText }}</code><span class="diff-status">{{ row.status === 'equal' ? '=' : row.status === 'added' ? '+' : row.status === 'removed' ? '-' : '~' }}</span><span class="line-number">{{ row.modifiedLine ?? '' }}</span><code>{{ row.modifiedText }}</code>
      </div>
    </div>
    <pre v-else-if="model.rawDiff" class="raw-diff">{{ model.rawDiff }}</pre>
    <div v-else class="empty">{{ model.original.content || model.modified.content ? t('config_diff.no_difference', '左右配置无差异') : t('config_diff.empty_content', '配置内容为空') }}</div>
  </section>
</template>

<style scoped>
.config-diff-viewer { min-width: 0; background: var(--nc-bg-panel); }
.diff-summary { padding: 10px 16px; color: var(--nc-text-secondary); font-size: 12px; }
.result-toolbar { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 16px; border-block: 1px solid var(--nc-divider); background: var(--nc-bg-muted); }
.diff-navigation { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.fallback-alert { margin: 10px 16px 0; }
.diff-table { max-height: 720px; overflow: auto; background: var(--nc-bg-code); }
.diff-row { display: grid; grid-template-columns: 70px minmax(360px, 1fr) 70px 70px minmax(360px, 1fr); min-width: 1100px; color: var(--nc-text-code); background: var(--nc-bg-code-muted); font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; }
.diff-row > * { min-width: 0; padding: 4px 8px; border-right: 1px solid var(--nc-divider); white-space: pre-wrap; overflow-wrap: anywhere; }
.diff-header { position: sticky; z-index: 1; top: 0; color: var(--nc-text-primary); background: var(--nc-bg-muted); }
.line-number, .diff-status { color: var(--nc-text-code-muted); text-align: center; }
.is-added { color: var(--nc-text-code-success); background: var(--nc-bg-code-added); }
.is-removed { color: var(--nc-text-code-danger); background: var(--nc-bg-code-removed); }
.is-modified { color: var(--nc-text-code-warning); background: var(--nc-bg-code-modified); }
.raw-diff { max-height: 720px; margin: 0; padding: 16px; overflow: auto; color: var(--nc-text-code); background: var(--nc-bg-code); font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; white-space: pre; }
.empty { display: grid; min-height: 160px; place-items: center; padding: 24px; color: var(--nc-text-secondary); background: var(--nc-bg-muted); }
</style>
