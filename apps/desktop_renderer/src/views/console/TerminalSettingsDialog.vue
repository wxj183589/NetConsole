<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Download, Plus, Upload } from '@element-plus/icons-vue'

import {
  getTerminalDangerousRules,
  getTerminalHighlightRules,
  getTerminalSettings,
  previewTerminalRulesImport,
  replaceTerminalDangerousRules,
  replaceTerminalHighlightRules,
  updateTerminalSettings,
  type TerminalDangerousRule,
  type TerminalHighlightRule,
  type TerminalSettings,
} from '../../api/terminal'
import { downloadBackendResource } from '../../platform/runtime'

const props = defineProps<{
  modelValue: boolean
  initialSettings?: TerminalSettings | null
  initialHighlights?: TerminalHighlightRule[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [settings: TerminalSettings, rules: TerminalHighlightRule[]]
}>()

const loading = ref(false)
const loadError = ref('')
const activeTab = ref('style')
const pageSize = 25
const pages = ref({ highlight: 1, dangerous: 1 })
const rulesLoading = ref<Record<RuleKind, boolean>>({ highlight: false, dangerous: false })
const saving = ref(false)
const settings = ref<TerminalSettings | null>(null)
const highlights = ref<TerminalHighlightRule[]>([])
const dangerous = ref<TerminalDangerousRule[]>([])
type RuleKind = 'highlight' | 'dangerous'
const ruleErrors = ref<Record<RuleKind, string>>({ highlight: '', dangerous: '' })
const repairing = { highlight: false, dangerous: false }
const ruleSnapshots = ref({ highlight: '', dangerous: '' })
const highlightPage = computed(() => highlights.value.slice((pages.value.highlight - 1) * pageSize, pages.value.highlight * pageSize))
const dangerousPage = computed(() => dangerous.value.slice((pages.value.dangerous - 1) * pageSize, pages.value.dangerous * pageSize))
let reads: AbortController | undefined
const highlightFile = ref<HTMLInputElement | null>(null)
const dangerousFile = ref<HTMLInputElement | null>(null)
const importing = ref<RuleKind | null>(null)
let settingsSnapshot = ''
let loadGeneration = 0
let performanceObserver: PerformanceObserver | null = null
let longTaskDuration = 0
let openStartedAt = 0
let openFrame = 0

function measure(name: string, startedAt: number): void {
  const elapsed = Math.round(performance.now() - startedAt)
  if (performance.getEntriesByName(`console.settings.${name}`, 'measure').length >= 120) {
    performance.clearMeasures(`console.settings.${name}`)
  }
  performance.measure(`console.settings.${name}`, { start: startedAt, end: performance.now() })
  console.debug(`[console-settings-performance] ${name}=${elapsed}ms`)
}

async function load(): Promise<void> {
  const generation = ++loadGeneration
  loadError.value = ''
  if (!props.initialSettings) loading.value = true
  const dataStartedAt = performance.now()
  try {
    const loadedSettings = props.initialSettings
      ? { ...props.initialSettings }
      : await getTerminalSettings(reads?.signal)
    if (generation !== loadGeneration) return
    settings.value = loadedSettings
    settingsSnapshot = JSON.stringify(settings.value)
    repairing.highlight = false
    repairing.dangerous = false
    measure('settings-read', dataStartedAt)
    const renderStartedAt = performance.now()
    await nextTick()
    if (generation === loadGeneration) measure('form-render', renderStartedAt)
  } catch (cause) {
    if (generation === loadGeneration) {
      settings.value = null
      loadError.value = errorText(cause)
    }
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function loadRules(kind: RuleKind): Promise<void> {
  if (ruleSnapshots.value[kind] || rulesLoading.value[kind]) return
  const generation = loadGeneration
  const startedAt = performance.now()
  rulesLoading.value[kind] = true
  ruleErrors.value[kind] = ''
  try {
    if (kind === 'highlight') {
      const rules = (await getTerminalHighlightRules(reads?.signal)).rules
      if (generation !== loadGeneration) return
      highlights.value = rules.map(rule => ({ ...rule }))
      ruleSnapshots.value.highlight = JSON.stringify(highlights.value)
    } else {
      const rules = (await getTerminalDangerousRules(reads?.signal)).rules
      if (generation !== loadGeneration) return
      dangerous.value = rules.map(rule => ({ ...rule }))
      ruleSnapshots.value.dangerous = JSON.stringify(dangerous.value)
    }
    measure(`${kind}-rules-read`, startedAt)
    await nextTick()
    if (generation === loadGeneration) measure(`${kind}-render`, startedAt)
  } catch (cause) {
    if (generation === loadGeneration) ruleErrors.value[kind] = errorText(cause)
  } finally {
    if (generation === loadGeneration) rulesLoading.value[kind] = false
  }
}

function handleTabChange(name: string | number): void {
  activeTab.value = String(name)
  if (name === 'highlight') void loadRules('highlight')
  else if (name === 'dangerous') void loadRules('dangerous')
  else if (name === 'logs') {
    const start = performance.now()
    void nextTick().then(() => measure('logs-render', start))
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function save(): Promise<void> {
  if (!settings.value) return
  saving.value = true
  try {
    const saveStartedAt = performance.now()
    if (ruleSnapshots.value.highlight && !ruleErrors.value.highlight && (repairing.highlight || ruleSnapshots.value.highlight !== JSON.stringify(highlights.value))) {
      highlights.value = (await replaceTerminalHighlightRules(highlights.value, repairing.highlight)).rules
      ruleSnapshots.value.highlight = JSON.stringify(highlights.value)
      repairing.highlight = false
    }
    if (ruleSnapshots.value.dangerous && !ruleErrors.value.dangerous && (repairing.dangerous || ruleSnapshots.value.dangerous !== JSON.stringify(dangerous.value))) {
      dangerous.value = (await replaceTerminalDangerousRules(dangerous.value, repairing.dangerous)).rules
      ruleSnapshots.value.dangerous = JSON.stringify(dangerous.value)
      repairing.dangerous = false
    }
    if (settingsSnapshot !== JSON.stringify(settings.value)) {
      settings.value = await updateTerminalSettings(settings.value)
      settingsSnapshot = JSON.stringify(settings.value)
    }
    emit('saved', settings.value, ruleSnapshots.value.highlight ? highlights.value : props.initialHighlights || [])
    measure('save', saveStartedAt)
    emit('update:modelValue', false)
    ElMessage.success('终端设置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '终端设置保存失败')
  } finally {
    saving.value = false
  }
}

async function importRules(kind: RuleKind, event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.error(`${file.name} 规则文件超过 2 MiB`)
    return
  }
  const generation = loadGeneration
  importing.value = kind
  try {
    const document = await previewTerminalRulesImport(kind, file)
    if (generation !== loadGeneration) return
    if (kind === 'highlight') highlights.value = document.rules as TerminalHighlightRule[]
    else dangerous.value = document.rules as TerminalDangerousRule[]
    repairing[kind] ||= !!ruleErrors.value[kind]
    ruleErrors.value[kind] = ''
    ElMessage.success(`已读取 ${document.actual_rule_count} 条规则`)
  } catch (error) {
    if (generation === loadGeneration) ElMessage.error(errorText(error))
  } finally {
    importing.value = null
  }
}

async function exportRules(kind: RuleKind): Promise<void> {
  try {
    await downloadBackendResource({
      apiPath: `/api/terminal/rules/${kind}/export`,
      suggestedName: `terminal-${kind}-rules.json`,
    })
  } catch (error) {
    ElMessage.error(errorText(error))
  }
}

function addHighlight(): void {
  highlights.value.push({
    id: `highlight-${crypto.randomUUID()}`,
    pattern: '',
    match_type: 'TEXT',
    color: '#f2c94c',
    enabled: true,
    source_row: 0,
  })
}

function addDangerous(): void {
  dangerous.value.push({
    id: `danger-${crypto.randomUUID()}`,
    pattern: '',
    match_type: 'TEXT',
    device_type: '通用',
    vendor: '通用',
    enabled: true,
    source_row: 0,
  })
}

watch(() => props.modelValue, (visible) => {
  if (visible) {
    reads = new AbortController()
    activeTab.value = 'style'
    pages.value = { highlight: 1, dangerous: 1 }
    openStartedAt = performance.now()
    void nextTick().then(() => measure('dialog-shell', openStartedAt))
    if (typeof PerformanceObserver !== 'undefined') {
      longTaskDuration = 0
      performanceObserver = new PerformanceObserver(entries => {
        longTaskDuration += entries.getEntries().reduce((total, entry) => total + entry.duration, 0)
      })
      try { performanceObserver.observe({ type: 'longtask', buffered: false }) } catch { performanceObserver = null }
    }
    const generation = loadGeneration
    if (props.initialSettings) {
      void load()
    } else {
      openFrame = requestAnimationFrame(() => {
        openFrame = requestAnimationFrame(() => {
          if (props.modelValue && generation === loadGeneration) void load()
        })
      })
    }
  } else {
    cancelAnimationFrame(openFrame)
    reads?.abort()
    reads = undefined
    loadGeneration += 1
    loading.value = false
    settings.value = null
    highlights.value = []
    dangerous.value = []
    ruleSnapshots.value = { highlight: '', dangerous: '' }
    rulesLoading.value = { highlight: false, dangerous: false }
    ruleErrors.value = { highlight: '', dangerous: '' }
    performanceObserver?.disconnect()
    performanceObserver = null
    if (openStartedAt) console.debug(`[console-settings-performance] renderer-long-tasks=${Math.round(longTaskDuration)}ms`)
  }
}, { immediate: true })
onBeforeUnmount(() => {
  cancelAnimationFrame(openFrame)
  reads?.abort()
  loadGeneration += 1
  performanceObserver?.disconnect()
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="终端设置"
    destroy-on-close
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    width="min(1120px, 94vw)"
    top="5vh"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="terminal-settings">
      <div v-if="loading" class="terminal-settings-state terminal-settings-load-state" role="status">正在读取终端设置…</div>
      <div v-else-if="!settings" class="terminal-settings-state terminal-settings-load-error" role="alert">
        <span>{{ loadError ? `终端设置未能加载：${loadError}` : '正在读取终端设置…' }}</span><el-button v-if="loadError" :loading="loading" @click="load">重新加载</el-button>
      </div>
      <el-tabs v-else :model-value="activeTab" @tab-change="handleTabChange">
        <el-tab-pane name="style" label="样式">
          <el-form label-width="100px" class="settings-form">
            <el-form-item label="字体">
              <el-select v-model="settings.font_family">
                <el-option v-for="font in ['Consolas', 'Courier New', '微软雅黑', 'JetBrains Mono', 'Fira Code', 'Terminal']" :key="font" :label="font" :value="font" />
              </el-select>
            </el-form-item>
            <el-form-item label="字号"><el-input-number v-model="settings.font_size" :min="8" :max="32" /></el-form-item>
            <el-form-item label="文字颜色"><el-color-picker v-model="settings.foreground" /></el-form-item>
            <el-form-item label="背景颜色"><el-color-picker v-model="settings.background" /></el-form-item>
            <el-form-item label="光标颜色"><el-color-picker v-model="settings.cursor_color" /></el-form-item>
            <el-form-item label="编码">
              <el-select v-model="settings.encoding">
                <el-option v-for="encoding in ['utf-8', 'gbk', 'ansi', 'big5', 'gb2312', 'gb18030']" :key="encoding" :label="encoding.toUpperCase()" :value="encoding" />
              </el-select>
            </el-form-item>
          </el-form>
          <pre class="terminal-preview" :style="{ color: settings.foreground, background: settings.background, fontFamily: settings.font_family, fontSize: `${settings.font_size}px` }">&lt;H3C&gt; display interface brief
Interface                Link  Speed
GigabitEthernet1/0/1     UP    1000M
Error: packet loss detected</pre>
        </el-tab-pane>

        <el-tab-pane name="highlight" lazy :label="`关键字高亮${ruleSnapshots.highlight ? ` (${highlights.length})` : ''}`">
          <el-alert v-if="ruleErrors.highlight" :title="ruleErrors.highlight" type="error" :closable="false" />
          <div v-if="rulesLoading.highlight" class="terminal-settings-state terminal-rules-loading" role="status">正在读取关键字规则…</div>
          <el-button v-if="ruleErrors.highlight" @click="loadRules('highlight')">重新加载规则</el-button>
          <template v-if="ruleSnapshots.highlight">
          <div class="rule-toolbar">
            <el-button :icon="Plus" :disabled="!!ruleErrors.highlight" @click="addHighlight">新增规则</el-button>
            <el-button :icon="Upload" :loading="importing === 'highlight'" :disabled="!!importing || saving" @click="highlightFile?.click()">导入 JSON</el-button>
            <el-button :icon="Download" :disabled="!!ruleErrors.highlight" @click="exportRules('highlight')">导出已保存规则</el-button>
            <input ref="highlightFile" type="file" accept=".json" hidden @change="importRules('highlight', $event)" />
          </div>
          <el-table v-if="activeTab === 'highlight' && !ruleErrors.highlight" :data="highlightPage" row-key="id" height="min(520px, 53vh)">
            <el-table-column width="65"><template #default="scope"><input v-model="scope.row.enabled" type="checkbox" aria-label="启用规则" /></template></el-table-column>
            <el-table-column label="匹配内容" min-width="220"><template #default="scope"><input v-model="scope.row.pattern" class="rule-input" aria-label="匹配内容" /></template></el-table-column>
            <el-table-column label="类型" width="110"><template #default="scope"><select v-model="scope.row.match_type" class="rule-input" aria-label="匹配类型"><option value="TEXT">文本</option><option value="REGEX">正则</option></select></template></el-table-column>
            <el-table-column label="颜色" width="100"><template #default="scope"><input v-model="scope.row.color" type="color" aria-label="高亮颜色" /></template></el-table-column>
            <el-table-column width="55"><template #default="scope"><el-button link type="danger" title="删除" @click="highlights.splice(highlights.indexOf(scope.row), 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="pages.highlight" :page-size="pageSize" :total="highlights.length" layout="prev, pager, next" />
          </template>
        </el-tab-pane>

        <el-tab-pane name="dangerous" lazy :label="`高危命令${ruleSnapshots.dangerous ? ` (${dangerous.length})` : ''}`">
          <el-alert v-if="ruleErrors.dangerous" :title="ruleErrors.dangerous" type="error" :closable="false" />
          <div v-if="rulesLoading.dangerous" class="terminal-settings-state terminal-rules-loading" role="status">正在读取高危命令规则…</div>
          <el-button v-if="ruleErrors.dangerous" @click="loadRules('dangerous')">重新加载规则</el-button>
          <template v-if="ruleSnapshots.dangerous">
          <div class="rule-toolbar">
            <el-button :icon="Plus" :disabled="!!ruleErrors.dangerous" @click="addDangerous">新增规则</el-button>
            <el-button :icon="Upload" :loading="importing === 'dangerous'" :disabled="!!importing || saving" @click="dangerousFile?.click()">导入 JSON</el-button>
            <el-button :icon="Download" :disabled="!!ruleErrors.dangerous" @click="exportRules('dangerous')">导出已保存规则</el-button>
            <input ref="dangerousFile" type="file" accept=".json" hidden @change="importRules('dangerous', $event)" />
            <el-switch v-model="settings.dangerous_command_warning" active-text="输入时提示" />
          </div>
          <el-table v-if="activeTab === 'dangerous' && !ruleErrors.dangerous" :data="dangerousPage" row-key="id" height="min(520px, 53vh)">
            <el-table-column width="65"><template #default="scope"><input v-model="scope.row.enabled" type="checkbox" aria-label="启用规则" /></template></el-table-column>
            <el-table-column label="命令" min-width="220"><template #default="scope"><input v-model="scope.row.pattern" class="rule-input" aria-label="匹配命令" /></template></el-table-column>
            <el-table-column label="类型" width="100"><template #default="scope"><select v-model="scope.row.match_type" class="rule-input" aria-label="匹配类型"><option value="TEXT">文本</option><option value="REGEX">正则</option></select></template></el-table-column>
            <el-table-column label="设备类型" width="120"><template #default="scope"><input v-model="scope.row.device_type" class="rule-input" aria-label="设备类型" /></template></el-table-column>
            <el-table-column label="厂商" width="110"><template #default="scope"><input v-model="scope.row.vendor" class="rule-input" aria-label="厂商" /></template></el-table-column>
            <el-table-column width="55"><template #default="scope"><el-button link type="danger" title="删除" @click="dangerous.splice(dangerous.indexOf(scope.row), 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="pages.dangerous" :page-size="pageSize" :total="dangerous.length" layout="prev, pager, next" />
          </template>
        </el-tab-pane>

        <el-tab-pane name="logs" label="日志" lazy>
          <el-form label-width="150px" class="settings-form">
            <el-form-item label="自动操作日志"><el-switch v-model="settings.automatic_recording" /></el-form-item>
            <el-form-item label="保留天数"><el-input-number v-model="settings.automatic_log_retention_days" :min="1" :max="3650" /></el-form-item>
            <el-form-item label="最大容量 (MiB)"><el-input-number :model-value="Math.round(settings.automatic_log_max_bytes / 1024 / 1024)" :min="64" :max="102400" @update:model-value="settings.automatic_log_max_bytes = Number($event) * 1024 * 1024" /></el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading || !settings || !!importing" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.terminal-settings { min-height: 360px; }
.terminal-settings-state { display: flex; min-height: 120px; align-items: center; justify-content: center; gap: 14px; }
.terminal-settings-error { color: var(--nc-danger); }
.settings-form { max-width: 460px; }
.terminal-preview { min-height: 150px; margin: 14px 0 0; padding: 16px; border-radius: 6px; line-height: 1.6; }
.rule-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
.rule-input { width: 100%; min-width: 0; color: inherit; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 4px; padding: 4px 6px; }
</style>
