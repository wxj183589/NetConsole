<script setup lang="ts">
import { ref, watch } from 'vue'
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

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [settings: TerminalSettings, rules: TerminalHighlightRule[]]
}>()

const loading = ref(false)
const saving = ref(false)
const settings = ref<TerminalSettings | null>(null)
const highlights = ref<TerminalHighlightRule[]>([])
const dangerous = ref<TerminalDangerousRule[]>([])
type RuleKind = 'highlight' | 'dangerous'
const ruleErrors = ref<Record<RuleKind, string>>({ highlight: '', dangerous: '' })
const repairing = { highlight: false, dangerous: false }
const ruleSnapshots = { highlight: '', dangerous: '' }
const highlightFile = ref<HTMLInputElement | null>(null)
const dangerousFile = ref<HTMLInputElement | null>(null)
const importing = ref<RuleKind | null>(null)
let settingsSnapshot = ''
let loadGeneration = 0

async function load(): Promise<void> {
  const generation = ++loadGeneration
  loading.value = true
  try {
    const [loadedSettings, loadedHighlights, loadedDangerous] = await Promise.allSettled([
      getTerminalSettings(),
      getTerminalHighlightRules(),
      getTerminalDangerousRules(),
    ])
    if (generation !== loadGeneration) return
    settings.value = loadedSettings.status === 'fulfilled' ? loadedSettings.value : null
    if (loadedSettings.status === 'rejected') ElMessage.error(errorText(loadedSettings.reason))
    highlights.value = loadedHighlights.status === 'fulfilled' ? loadedHighlights.value.rules : []
    dangerous.value = loadedDangerous.status === 'fulfilled' ? loadedDangerous.value.rules : []
    ruleErrors.value.highlight = loadedHighlights.status === 'rejected' ? errorText(loadedHighlights.reason) : ''
    ruleErrors.value.dangerous = loadedDangerous.status === 'rejected' ? errorText(loadedDangerous.reason) : ''
    settingsSnapshot = JSON.stringify(settings.value)
    ruleSnapshots.highlight = JSON.stringify(highlights.value)
    ruleSnapshots.dangerous = JSON.stringify(dangerous.value)
    repairing.highlight = false
    repairing.dangerous = false
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function save(): Promise<void> {
  if (!settings.value) return
  saving.value = true
  try {
    if (!ruleErrors.value.highlight && (repairing.highlight || ruleSnapshots.highlight !== JSON.stringify(highlights.value))) {
      highlights.value = (await replaceTerminalHighlightRules(highlights.value, repairing.highlight)).rules
      ruleSnapshots.highlight = JSON.stringify(highlights.value)
      repairing.highlight = false
    }
    if (!ruleErrors.value.dangerous && (repairing.dangerous || ruleSnapshots.dangerous !== JSON.stringify(dangerous.value))) {
      dangerous.value = (await replaceTerminalDangerousRules(dangerous.value, repairing.dangerous)).rules
      ruleSnapshots.dangerous = JSON.stringify(dangerous.value)
      repairing.dangerous = false
    }
    if (settingsSnapshot !== JSON.stringify(settings.value)) {
      settings.value = await updateTerminalSettings(settings.value)
      settingsSnapshot = JSON.stringify(settings.value)
    }
    if (!ruleErrors.value.highlight) emit('saved', settings.value, highlights.value)
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
  if (visible) void load()
  else loadGeneration += 1
}, { immediate: true })
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="终端设置"
    width="min(1120px, 94vw)"
    top="5vh"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="terminal-settings">
      <el-tabs v-if="settings">
        <el-tab-pane label="样式">
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

        <el-tab-pane :label="`关键字高亮 (${highlights.length})`">
          <el-alert v-if="ruleErrors.highlight" :title="ruleErrors.highlight" type="error" :closable="false" />
          <div class="rule-toolbar">
            <el-button :icon="Plus" :disabled="!!ruleErrors.highlight" @click="addHighlight">新增规则</el-button>
            <el-button :icon="Upload" :loading="importing === 'highlight'" :disabled="!!importing || saving" @click="highlightFile?.click()">导入 JSON</el-button>
            <el-button :icon="Download" :disabled="!!ruleErrors.highlight" @click="exportRules('highlight')">导出已保存规则</el-button>
            <input ref="highlightFile" type="file" accept=".json" hidden @change="importRules('highlight', $event)" />
          </div>
          <el-table v-if="!ruleErrors.highlight" :data="highlights" height="520px">
            <el-table-column width="65"><template #default="scope"><el-switch v-model="scope.row.enabled" /></template></el-table-column>
            <el-table-column label="匹配内容" min-width="400"><template #default="scope"><el-input v-model="scope.row.pattern" /></template></el-table-column>
            <el-table-column label="类型" width="110"><template #default="scope"><el-select v-model="scope.row.match_type"><el-option label="文本" value="TEXT" /><el-option label="正则" value="REGEX" /></el-select></template></el-table-column>
            <el-table-column label="颜色" width="100"><template #default="scope"><el-color-picker v-model="scope.row.color" /></template></el-table-column>
            <el-table-column width="55"><template #default="scope"><el-button link type="danger" title="删除" @click="highlights.splice(scope.$index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`高危命令 (${dangerous.length})`">
          <el-alert v-if="ruleErrors.dangerous" :title="ruleErrors.dangerous" type="error" :closable="false" />
          <div class="rule-toolbar">
            <el-button :icon="Plus" :disabled="!!ruleErrors.dangerous" @click="addDangerous">新增规则</el-button>
            <el-button :icon="Upload" :loading="importing === 'dangerous'" :disabled="!!importing || saving" @click="dangerousFile?.click()">导入 JSON</el-button>
            <el-button :icon="Download" :disabled="!!ruleErrors.dangerous" @click="exportRules('dangerous')">导出已保存规则</el-button>
            <input ref="dangerousFile" type="file" accept=".json" hidden @change="importRules('dangerous', $event)" />
            <el-switch v-model="settings.dangerous_command_warning" active-text="输入时提示" />
          </div>
          <el-table v-if="!ruleErrors.dangerous" :data="dangerous" height="520px">
            <el-table-column width="65"><template #default="scope"><el-switch v-model="scope.row.enabled" /></template></el-table-column>
            <el-table-column label="命令" min-width="330"><template #default="scope"><el-input v-model="scope.row.pattern" /></template></el-table-column>
            <el-table-column label="类型" width="100"><template #default="scope"><el-select v-model="scope.row.match_type"><el-option label="文本" value="TEXT" /><el-option label="正则" value="REGEX" /></el-select></template></el-table-column>
            <el-table-column label="设备类型" width="120"><template #default="scope"><el-input v-model="scope.row.device_type" /></template></el-table-column>
            <el-table-column label="厂商" width="110"><template #default="scope"><el-input v-model="scope.row.vendor" /></template></el-table-column>
            <el-table-column width="55"><template #default="scope"><el-button link type="danger" title="删除" @click="dangerous.splice(scope.$index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="日志">
          <el-form label-width="150px" class="settings-form">
            <el-form-item label="自动操作日志"><el-switch v-model="settings.automatic_recording" /></el-form-item>
            <el-form-item label="保留天数"><el-input-number v-model="settings.automatic_log_retention_days" :min="1" :max="3650" /></el-form-item>
            <el-form-item label="最大容量 (MiB)"><el-input-number :model-value="Math.round(settings.automatic_log_max_bytes / 1024 / 1024)" :min="64" :max="102400" @update:model-value="settings.automatic_log_max_bytes = Number($event) * 1024 * 1024" /></el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading || !settings || !!importing" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.terminal-settings { min-height: 590px; }
.settings-form { max-width: 460px; }
.terminal-preview { min-height: 150px; margin: 14px 0 0; padding: 16px; border-radius: 6px; line-height: 1.6; }
.rule-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
</style>
