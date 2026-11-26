<script setup lang="ts">
import { reactive, watch } from 'vue'

import type { TerminalProfile, TerminalProfileFolder, TerminalProfileValues } from '../../api/terminal'

const props = defineProps<{
  modelValue: boolean
  folders: TerminalProfileFolder[]
  loading: boolean
  profile?: TerminalProfile | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [value: TerminalProfileValues & {
    password: string
    save_profile: boolean
    remember_password: boolean | null
  }]
}>()

const form = reactive({
  name: '',
  host: '',
  backup_host: '',
  backup_port: null as number | null,
  port: 22,
  protocol: 'SSH' as 'SSH' | 'TELNET',
  username: '',
  password: '',
  encoding: 'utf-8',
  vendor: 'H3C',
  device_type: 'SW',
  folder_id: '',
  favorite: false,
  notes: '',
  tagsText: '',
  save_profile: false,
  remember_password: false,
})

watch(() => form.protocol, (protocol, previous) => {
  if ((previous === 'SSH' && form.port === 22) || (previous === 'TELNET' && form.port === 23)) {
    form.port = protocol === 'SSH' ? 22 : 23
  }
})

watch(() => form.save_profile, (enabled) => {
  if (!enabled) {
    form.remember_password = false
    form.favorite = false
    form.folder_id = ''
  }
})

watch(
  () => [props.modelValue, props.profile] as const,
  ([visible, profile]) => {
    if (!visible) return
    if (profile) {
      Object.assign(form, {
        name: profile.name,
        host: profile.host,
        backup_host: profile.backup_host || '',
        backup_port: profile.backup_host ? profile.backup_port : null,
        port: profile.port,
        protocol: profile.protocol,
        username: profile.username,
        password: '',
        encoding: profile.encoding,
        vendor: profile.vendor,
        device_type: profile.device_type,
        folder_id: profile.folder_id,
        favorite: profile.favorite,
        notes: profile.notes || '',
        tagsText: (profile.tags || []).join(', '),
        save_profile: true,
        remember_password: profile.password_configured,
      })
      return
    }
    Object.assign(form, {
      name: '', host: '', backup_host: '', backup_port: null, port: 22, protocol: 'SSH', username: '', password: '',
      encoding: 'utf-8', vendor: 'H3C', device_type: 'SW', folder_id: '',
      favorite: false, notes: '', tagsText: '', save_profile: false, remember_password: false,
    })
  },
)

function close(): void {
  emit('update:modelValue', false)
}

function submit(): void {
  const rememberPassword = props.profile
    ? (form.remember_password ? (form.password ? true : null) : false)
    : form.remember_password
  emit('submit', {
    name: form.name.trim() || form.host.trim(),
    host: form.host.trim(),
    backup_host: form.backup_host.trim(),
    backup_port: form.backup_port,
    port: Number(form.port),
    protocol: form.protocol,
    username: form.username.trim(),
    password: form.password,
    encoding: form.encoding,
    vendor: form.vendor,
    device_type: form.device_type,
    folder_id: form.folder_id,
    favorite: form.favorite,
    notes: form.notes.trim(),
    tags: form.tagsText.split(/[,，\n]/).map((tag) => tag.trim()).filter(Boolean),
    save_profile: form.save_profile,
    remember_password: rememberPassword,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="profile ? '编辑保存会话' : '快速连接'"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form label-position="top" @submit.prevent="submit">
      <div class="quick-connect-grid">
        <el-form-item label="会话名称" class="is-wide">
          <el-input v-model="form.name" placeholder="默认使用主机地址" maxlength="160" />
        </el-form-item>
        <el-form-item label="协议">
          <el-segmented v-model="form.protocol" :options="['SSH', 'TELNET']" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
        <el-form-item label="主机" class="is-wide">
          <el-input v-model="form.host" placeholder="IP 地址或主机名" maxlength="255" />
        </el-form-item>
        <el-form-item label="备用主机" class="is-wide">
          <el-input v-model="form.backup_host" placeholder="可选，故障切换时单独连接" maxlength="255" />
        </el-form-item>
        <el-form-item label="备用端口">
          <el-input-number v-model="form.backup_port" :min="1" :max="65535" controls-position="right" :disabled="!form.backup_host.trim()" placeholder="沿用主端口" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" maxlength="256" autocomplete="username" />
        </el-form-item>
        <el-form-item :label="profile ? '更新密码' : '密码'">
          <el-input v-model="form.password" type="password" show-password maxlength="4096" autocomplete="current-password" :placeholder="profile ? '留空保持当前密码' : ''" />
        </el-form-item>
        <el-form-item label="编码">
          <el-select v-model="form.encoding">
            <el-option v-for="value in ['utf-8', 'gb18030', 'gbk', 'gb2312', 'big5', 'ansi']" :key="value" :value="value" :label="value.toUpperCase()" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备厂商">
          <el-select v-model="form.vendor" filterable allow-create>
            <el-option v-for="value in ['H3C', 'Huawei', 'ZTE', 'Cisco', 'Ruijie', 'Other']" :key="value" :value="value" :label="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="form.device_type">
            <el-option v-for="value in ['SW', 'AC', 'FW', 'Route', 'Cloud-AP', 'FAT-AP', 'MR', 'Other']" :key="value" :value="value" :label="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注" class="is-wide">
          <el-input v-model="form.notes" type="textarea" :rows="2" maxlength="2000" show-word-limit />
        </el-form-item>
        <el-form-item label="标签" class="is-wide">
          <el-input v-model="form.tagsText" placeholder="逗号分隔" maxlength="1400" />
        </el-form-item>
      </div>
      <el-checkbox v-if="!profile" v-model="form.save_profile">保存为会话</el-checkbox>
      <div v-if="form.save_profile" class="profile-options">
        <el-select v-model="form.folder_id" placeholder="未分组" clearable>
          <el-option v-for="folder in folders" :key="folder.folder_id" :value="folder.folder_id" :label="folder.name" />
        </el-select>
        <el-checkbox v-model="form.favorite">收藏</el-checkbox>
        <el-checkbox v-model="form.remember_password">{{ profile && profile.password_configured ? '保留或更新 Windows DPAPI 密码' : '使用 Windows DPAPI 保存密码' }}</el-checkbox>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button
        type="primary"
        :loading="loading"
        :disabled="!form.host.trim() || (form.protocol === 'SSH' && !form.username.trim()) || (!profile && !form.password)"
        @click="submit"
      >{{ profile ? '保存' : '连接' }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.quick-connect-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 16px;
}

.is-wide { grid-column: 1 / -1; }
.quick-connect-grid :deep(.el-input-number),
.quick-connect-grid :deep(.el-select) { width: 100%; }

.profile-options {
  display: grid;
  grid-template-columns: minmax(0, 180px) auto;
  align-items: center;
  gap: 8px 16px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--nc-border);
  border-radius: 6px;
  background: var(--nc-bg-muted);
}

.profile-options > :last-child { grid-column: 1 / -1; }
</style>
