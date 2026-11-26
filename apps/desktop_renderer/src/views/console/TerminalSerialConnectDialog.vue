<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createSerialSession,
  importSerialProfiles,
  listSerialPorts,
  listSerialProfiles,
  saveSerialProfiles,
  type SerialConnectionOptions,
  type SerialPortInfo,
  type SerialProfile,
  type TerminalSessionConnection,
} from '../../api/terminal'
import { downloadBackendResource } from '../../platform/runtime'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  opened: [value: TerminalSessionConnection]
}>()

const loading = ref(false)
const connecting = ref(false)
const error = ref('')
const ports = ref<SerialPortInfo[]>([])
const profiles = ref<SerialProfile[]>([])
const profileId = ref('h3c-console')
const fileInput = ref<HTMLInputElement | null>(null)
const options = ref<SerialConnectionOptions>(defaults())
let generation = 0

const selectedPort = computed(() => ports.value.some(item => item.port === options.value.port))
const customProfiles = computed(() => profiles.value.filter(item => !item.built_in))
const baudRatePresets = [9600, 19200, 38400, 57600, 115200]
const baudRateChoice = computed({
  get: () => baudRatePresets.includes(options.value.baud_rate) ? String(options.value.baud_rate) : 'custom',
  set: (value: string) => { if (value !== 'custom') options.value.baud_rate = Number(value) },
})

function defaults(): SerialConnectionOptions {
  return {
    port: '', baud_rate: 9600, data_bits: 8, parity: 'N', stop_bits: 1,
    flow_control: 'none', encoding: 'utf-8', line_ending: 'CR', local_echo: false,
    dtr: 'KEEP', rts: 'KEEP', timeout_seconds: 0.05,
  }
}

async function load(): Promise<void> {
  const request = ++generation
  loading.value = true
  error.value = ''
  try {
    const [portList, profileDocument] = await Promise.all([listSerialPorts(), listSerialProfiles()])
    if (request !== generation) return
    ports.value = portList.items
    profiles.value = profileDocument.profiles
    applyProfile(profileId.value)
  } catch (cause) {
    if (request === generation) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (request === generation) loading.value = false
  }
}

function applyProfile(id: string): void {
  const profile = profiles.value.find(item => item.profile_id === id)
  if (!profile) return
  const port = options.value.port
  options.value = { ...profile.options, port: port || profile.options.port }
}

async function connect(): Promise<void> {
  if (!selectedPort.value) {
    ElMessage.error('请选择当前可用的 COM 端口')
    return
  }
  connecting.value = true
  try {
    const created = await createSerialSession(options.value)
    emit('opened', created)
    emit('update:modelValue', false)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : String(cause))
  } finally {
    connecting.value = false
  }
}

async function saveTemplate(): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('串口模板名称', '保存串口模板', { inputValue: '自定义串口' })
    const profile: SerialProfile = {
      profile_id: crypto.randomUUID(),
      name: value.trim(),
      options: { ...options.value, port: '' },
    }
    const saved = await saveSerialProfiles([...customProfiles.value, profile])
    profiles.value = saved.profiles
    profileId.value = profile.profile_id
    ElMessage.success('串口模板已保存')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : String(cause))
  }
}

async function removeTemplate(): Promise<void> {
  const selected = profiles.value.find(item => item.profile_id === profileId.value)
  if (!selected || selected.built_in) return
  try {
    await ElMessageBox.confirm(`删除串口模板“${selected.name}”？`, '删除串口模板')
    const saved = await saveSerialProfiles(customProfiles.value.filter(item => item.profile_id !== selected.profile_id))
    profiles.value = saved.profiles
    profileId.value = 'h3c-console'
    applyProfile(profileId.value)
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : String(cause))
  }
}

async function importTemplates(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error('串口模板文件不能超过 2 MiB')
    const parsed: unknown = JSON.parse(await file.text())
    if (!parsed || typeof parsed !== 'object' || !('profiles' in parsed) || !Array.isArray(parsed.profiles)) {
      throw new Error('串口模板文件结构无效')
    }
    const merged = new Map(customProfiles.value.map(item => [item.profile_id, item]))
    for (const item of parsed.profiles) {
      if (!item || typeof item !== 'object' || 'built_in' in item) throw new Error('只能导入自定义串口模板')
      const profile = item as SerialProfile
      merged.set(profile.profile_id, profile)
    }
    const document = await importSerialProfiles({ schema_version: 1, profiles: [...merged.values()] })
    profiles.value = document.profiles
    ElMessage.success('串口模板已导入')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : String(cause))
  }
}

async function exportTemplates(): Promise<void> {
  try {
    await downloadBackendResource({ apiPath: '/api/terminal/serial/profiles/export', suggestedName: 'console-serial-profiles.json' })
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : String(cause))
  }
}

watch(() => props.modelValue, visible => {
  if (visible) void load()
  else generation += 1
})
</script>

<template>
  <el-dialog :model-value="modelValue" title="新建 COM 串口会话" width="min(760px, 94vw)" @update:model-value="emit('update:modelValue', $event)">
    <div v-if="error" class="serial-load-error" role="alert">
      <span>{{ error }}</span>
      <el-button :loading="loading" @click="load">重新加载</el-button>
    </div>
    <div class="serial-form">
      <el-form label-width="118px">
        <el-form-item label="串口端口">
          <el-select v-model="options.port" :loading="loading" filterable placeholder="选择已连接的端口" style="width: 100%">
            <el-option v-for="item in ports" :key="item.port" :value="item.port" :label="item.port">
              <span>{{ item.port }} · {{ item.description || item.name }}</span>
              <small v-if="item.manufacturer"> · {{ item.manufacturer }}</small>
            </el-option>
          </el-select>
          <el-button title="刷新串口列表" aria-label="刷新串口列表" :loading="loading" @click="load">刷新</el-button>
        </el-form-item>
        <el-alert v-if="!loading && !ports.length" title="未发现串口，请连接 USB 转串口设备后刷新。" type="info" :closable="false" />
        <el-form-item label="参数模板">
          <el-select v-model="profileId" style="width: 100%" @change="applyProfile">
            <el-option v-for="profile in profiles" :key="profile.profile_id" :label="profile.name" :value="profile.profile_id" />
          </el-select>
          <el-button title="保存为新模板" aria-label="保存串口模板" @click="saveTemplate">另存</el-button>
          <el-button v-if="!profiles.find(item => item.profile_id === profileId)?.built_in" title="删除模板" aria-label="删除串口模板" @click="removeTemplate">删除</el-button>
        </el-form-item>
        <el-form-item label="波特率">
          <el-select v-model="baudRateChoice" style="width: 190px"><el-option v-for="value in baudRatePresets" :key="value" :label="String(value)" :value="String(value)" /><el-option label="自定义" value="custom" /></el-select>
          <el-input-number v-if="baudRateChoice === 'custom'" v-model="options.baud_rate" :min="50" :max="4000000" :step="100" aria-label="自定义波特率" />
        </el-form-item>
        <div class="serial-form-grid">
          <el-form-item label="数据位"><el-select v-model="options.data_bits"><el-option v-for="value in [5, 6, 7, 8]" :key="value" :label="String(value)" :value="value" /></el-select></el-form-item>
          <el-form-item label="校验位"><el-select v-model="options.parity"><el-option label="无" value="N" /><el-option label="奇" value="O" /><el-option label="偶" value="E" /><el-option label="Mark" value="M" /><el-option label="Space" value="S" /></el-select></el-form-item>
          <el-form-item label="停止位"><el-select v-model="options.stop_bits"><el-option :label="String(1)" :value="1" /><el-option label="1.5" :value="1.5" /><el-option :label="String(2)" :value="2" /></el-select></el-form-item>
          <el-form-item label="流控"><el-select v-model="options.flow_control"><el-option label="无" value="none" /><el-option label="RTS/CTS" value="rtscts" /><el-option label="DTR/DSR" value="dsrdtr" /><el-option label="XON/XOFF" value="xonxoff" /></el-select></el-form-item>
          <el-form-item label="编码"><el-select v-model="options.encoding"><el-option v-for="value in ['utf-8', 'gbk', 'gb18030', 'big5', 'ansi']" :key="value" :label="value.toUpperCase()" :value="value" /></el-select></el-form-item>
          <el-form-item label="回车发送"><el-select v-model="options.line_ending"><el-option label="CR" value="CR" /><el-option label="LF" value="LF" /><el-option label="CRLF" value="CRLF" /></el-select></el-form-item>
          <el-form-item label="DTR"><el-select v-model="options.dtr" :disabled="options.flow_control === 'dsrdtr'"><el-option label="保持原状态" value="KEEP" /><el-option label="启用" value="ON" /><el-option label="关闭" value="OFF" /></el-select></el-form-item>
          <el-form-item label="RTS"><el-select v-model="options.rts" :disabled="options.flow_control === 'rtscts'"><el-option label="保持原状态" value="KEEP" /><el-option label="启用" value="ON" /><el-option label="关闭" value="OFF" /></el-select></el-form-item>
          <el-form-item label="读取间隔"><el-input-number v-model="options.timeout_seconds" :min="0.01" :max="2" :step="0.01" /></el-form-item>
        </div>
        <el-form-item label="本地回显"><el-switch v-model="options.local_echo" /></el-form-item>
      </el-form>
      <div class="serial-template-actions">
        <input ref="fileInput" hidden type="file" accept=".json,application/json" @change="importTemplates" />
        <el-button @click="fileInput?.click()">导入模板</el-button>
        <el-button @click="exportTemplates">导出模板</el-button>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="connecting" :disabled="loading || !selectedPort" @click="connect">连接</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.serial-form { min-height: 420px; }
.serial-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 18px; }
.serial-template-actions { display: flex; justify-content: flex-end; gap: 8px; }
.serial-load-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; color: var(--nc-danger); }
@media (max-width: 640px) { .serial-form-grid { grid-template-columns: 1fr; } }
</style>
