<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'

import {
  getTerminalDangerousRules,
  getTerminalHighlightRules,
  getTerminalSettings,
  replaceTerminalDangerousRules,
  replaceTerminalHighlightRules,
  updateTerminalSettings,
  type TerminalDangerousRule,
  type TerminalHighlightRule,
  type TerminalSettings,
} from '../../api/terminal'

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

async function load(): Promise<void> {
  loading.value = true
  try {
    const [loadedSettings, loadedHighlights, loadedDangerous] = await Promise.all([
      getTerminalSettings(),
      getTerminalHighlightRules(),
      getTerminalDangerousRules(),
    ])
    settings.value = loadedSettings
    highlights.value = loadedHighlights.rules
    dangerous.value = loadedDangerous.rules
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '终端设置读取失败')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!settings.value) return
  saving.value = true
  try {
    const [savedSettings, savedHighlights] = await Promise.all([
      updateTerminalSettings(settings.value),
      replaceTerminalHighlightRules(highlights.value),
      replaceTerminalDangerousRules(dangerous.value),
    ])
    settings.value = savedSettings
    highlights.value = savedHighlights.rules
    emit('saved', savedSettings, savedHighlights.rules)
    emit('update:modelValue', false)
    ElMessage.success('终端设置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '终端设置保存失败')
  } finally {
    saving.value = false
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
})
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
          <div class="rule-toolbar"><el-button @click="addHighlight"><el-icon><Plus /></el-icon>新增规则</el-button></div>
          <el-table :data="highlights" height="520px">
            <el-table-column width="65"><template #default="scope"><el-switch v-model="scope.row.enabled" /></template></el-table-column>
            <el-table-column label="匹配内容" min-width="400"><template #default="scope"><el-input v-model="scope.row.pattern" /></template></el-table-column>
            <el-table-column label="类型" width="110"><template #default="scope"><el-select v-model="scope.row.match_type"><el-option label="文本" value="TEXT" /><el-option label="正则" value="REGEX" /></el-select></template></el-table-column>
            <el-table-column label="颜色" width="100"><template #default="scope"><el-color-picker v-model="scope.row.color" /></template></el-table-column>
            <el-table-column width="55"><template #default="scope"><el-button link type="danger" title="删除" @click="highlights.splice(scope.$index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`高危命令 (${dangerous.length})`">
          <div class="rule-toolbar">
            <el-button @click="addDangerous"><el-icon><Plus /></el-icon>新增规则</el-button>
            <el-switch v-model="settings.dangerous_command_warning" active-text="输入时提示" />
          </div>
          <el-table :data="dangerous" height="520px">
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
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.terminal-settings { min-height: 590px; }
.settings-form { max-width: 460px; }
.terminal-preview { min-height: 150px; margin: 14px 0 0; padding: 16px; border-radius: 6px; line-height: 1.6; }
.rule-toolbar { display: flex; align-items: center; gap: 18px; margin-bottom: 10px; }
</style>
