<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'

import {
  configureLocalService, listLocalServices, readLocalServiceLogs, runLocalServiceAction,
  type LocalService, type LocalServiceAction, type LocalServiceConfig,
} from '../../api/localNetworkServices'
import { localServiceLabel as label } from '../../i18n/localNetworkServices'

const groups = ['core', 'files', 'remote']
const services = ref<LocalService[]>([])
const addresses = ref<Record<string, string>>({})
const pending = ref<string[]>([])
const error = ref('')
const editing = ref<LocalService | null>(null)
const config = ref<LocalServiceConfig | null>(null)
const dns = ref('')
const passivePorts = ref('')
const logging = ref<LocalService | null>(null)
const logs = ref<string[]>([])
const ftpCredential = ref<LocalService['session_credential']>()
const ftpCredentialSecure = ref(false)
const dialogOpen = computed({
  get: () => !!editing.value || !!logging.value,
  set: (open: boolean) => { if (!open) { editing.value = null; logging.value = null } },
})
let poll: ReturnType<typeof setInterval> | undefined
const refreshing = ref(false)
let refreshNumber = 0

function title(id: string): string {
  return id === 'scheduler' ? label(id) : id === 'iperf' ? 'iPerf' : id.toUpperCase()
}

function status(service: LocalService): string {
  return label(!service.available && service.installed ? 'installed' : service.status === 'deferred' ? 'deferred_status' : service.status)
}

function canEdit(service: LocalService): boolean {
  return service.available && !['running', 'starting', 'stopping'].includes(service.status)
}

function canStart(service: LocalService): boolean {
  return canEdit(service) && service.status !== 'uninitialized'
}

async function refresh() {
  if (refreshing.value || pending.value.length) return
  refreshing.value = true
  const requestNumber = ++refreshNumber
  try {
    const data = await listLocalServices()
    if (requestNumber !== refreshNumber) return
    services.value = data.services
    addresses.value = data.addresses
  } catch {
    if (requestNumber === refreshNumber) error.value = label('requestFailed')
  } finally {
    refreshing.value = false
  }
}

async function update(service: LocalService, change: () => Promise<LocalService>) {
  if (pending.value.includes(service.id)) return
  pending.value = [...pending.value, service.id]
  refreshNumber++
  error.value = ''
  try {
    const updated = await change()
    services.value = services.value.map((row) => row.id === updated.id ? updated : row)
    if (updated.error_code) error.value = label(updated.error_code)
  } catch (cause) {
    error.value = cause instanceof Error ? label(cause.message) : label('requestFailed')
  } finally {
    pending.value = pending.value.filter((id) => id !== service.id)
  }
}

function run(service: LocalService, action: LocalServiceAction) {
  return update(service, async () => {
    const { session_credential, ...snapshot } = await runLocalServiceAction(service.id, action)
    if (session_credential) {
      ftpCredential.value = session_credential
      ftpCredentialSecure.value = Boolean(snapshot.config?.tls_enabled)
    }
    return snapshot
  })
}

function edit(service: LocalService) {
  if (!service.config) return
  error.value = ''
  config.value = { ...service.config }
  passivePorts.value = service.config.passive_ports?.join('-') ?? ''
  dns.value = Object.entries(service.config.dns_records).map(([name, ip]) => `${name} ${ip}`).join('\n')
  editing.value = service
}

async function save() {
  const service = editing.value
  if (!service || !config.value) return
  const value = { ...config.value }
  if (service.id === 'ftp') {
    const ports = passivePorts.value.trim()
    const match = /^(\d+)-(\d+)$/.exec(ports)
    if (ports && (!match || Number(match[1]) < 1024 || Number(match[2]) > 65535 || Number(match[1]) > Number(match[2]))) {
      error.value = label('passivePortsInvalid')
      return
    }
    value.passive_ports = match ? [Number(match[1]), Number(match[2])] : null
  }
  if (service.id === 'dns') {
    const rows = dns.value.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => line.split(/\s+/))
    if (rows.some((row) => row.length !== 2) || new Set(rows.map(([name]) => name.toLowerCase().replace(/\.$/, ''))).size !== rows.length) {
      error.value = label('dnsInvalid')
      return
    }
    value.dns_records = Object.fromEntries(rows)
  }
  await update(service, async () => {
    const updated = await configureLocalService(service.id, value)
    editing.value = null
    return updated
  })
}

async function showLogs(service: LocalService) {
  error.value = ''
  logs.value = []
  logging.value = service
  try {
    const result = await readLocalServiceLogs(service.id)
    if (logging.value?.id === service.id) logs.value = result.lines
  } catch {
    if (logging.value?.id === service.id) error.value = label('requestFailed')
  }
}

function activate() {
  if (poll !== undefined) return
  void refresh()
  poll = setInterval(() => void refresh(), 4000)
}

function deactivate() {
  ftpCredential.value = undefined
  ftpCredentialSecure.value = false
  if (poll === undefined) return
  clearInterval(poll)
  poll = undefined
}

onMounted(activate)
onActivated(activate)
onDeactivated(deactivate)
onUnmounted(deactivate)
</script>

<template>
  <section class="local-services">
    <header>
      <h1>{{ label('title') }}</h1>
      <el-button :loading="refreshing" @click="refresh">{{ label('refresh') }}</el-button>
    </header>
    <el-alert v-if="error && !dialogOpen" :title="error" type="error" show-icon @close="error = ''" />

    <section v-for="group in services.length ? groups : []" :key="group">
      <h2>{{ label(group) }}</h2>
      <div class="table-scroll">
        <table>
          <thead><tr>
            <th scope="col">{{ label('service') }}</th>
            <th scope="col">{{ label('status') }}</th>
            <th scope="col">{{ label('listener') }}</th>
            <th scope="col">{{ label('runtime') }}</th>
            <th scope="col">{{ label('source') }}</th>
            <th scope="col">{{ label('actions') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="service in services.filter((row) => row.group === group)" :key="service.id">
              <th scope="row" :title="['ftp', 'telnet', 'tftp'].includes(service.id) ? label('cleartext') : undefined">{{ title(service.id) }}</th>
              <td :title="service.error_code ? label(service.error_code) : undefined">
                <span class="status" :class="`status--${service.status}`">{{ status(service) }}</span>
              </td>
              <td class="endpoint">{{ service.listeners?.length ? service.listeners.map(listener => `${listener.address}:${listener.port} ${listener.transport}`).join(' · ') : service.config ? `${service.config.address}:${service.config.port} ${service.transport}` : '—' }}</td>
              <td class="runtime" :title="service.started_at || undefined">
                <template v-if="service.pid">
                  PID {{ service.pid }}<span v-if="service.process_owner === 'backend'"> · {{ label('backendProcess') }}</span><span v-if="service.uptime_seconds"> · {{ Math.floor(service.uptime_seconds / 3600) }}h {{ Math.floor(service.uptime_seconds % 3600 / 60) }}m</span><span v-if="service.process_owner === 'service'"> · CPU {{ service.cpu_percent ?? '—' }}% · {{ service.memory_bytes === null ? '—' : `${(service.memory_bytes / 1048576).toFixed(1)} MiB` }}</span>
                </template>
                <span v-else>—</span>
              </td>
              <td :title="service.capabilities?.service_state ? JSON.stringify(service.capabilities) : service.dependency || undefined">{{ label(service.source) }}<span v-if="!service.available && service.dependency"> · {{ service.dependency }}</span><span v-if="service.capabilities?.service_state"> · sshd {{ service.capabilities.service_state }}<span v-if="service.capabilities.version"> · {{ service.capabilities.version }}</span></span></td>
              <td class="actions">
                <template v-if="service.available">
                  <el-button v-if="service.status === 'uninitialized'" text :disabled="pending.includes(service.id)" @click="run(service, 'initialize')">{{ label('initialize') }}</el-button>
                  <el-button v-if="canStart(service)" text :disabled="pending.includes(service.id)" type="primary" @click="run(service, 'start')">{{ label('start') }}</el-button>
                  <el-button v-if="service.status === 'running'" text :disabled="pending.includes(service.id)" @click="run(service, 'stop')">{{ label('stop') }}</el-button>
                  <el-button v-if="service.status === 'running'" text :disabled="pending.includes(service.id)" @click="run(service, 'restart')">{{ label('restart') }}</el-button>
                  <el-button text :disabled="!canEdit(service) || pending.includes(service.id)" @click="edit(service)">{{ label('configure') }}</el-button>
                  <el-button text @click="showLogs(service)">{{ label('logs') }}</el-button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <el-dialog v-model="dialogOpen" :title="editing ? `${title(editing.id)} · ${label('configure')}` : logging ? `${title(logging.id)} · ${label('logs')}` : ''" width="min(620px, 92vw)">
      <el-alert v-if="error" :title="error" type="error" show-icon @close="error = ''" />
      <el-form v-if="editing && config" label-position="top" @submit.prevent="save">
        <div class="fields">
          <el-form-item :label="label('address')">
            <el-select v-model="config.address">
              <el-option v-for="(name, address) in addresses" :key="address" :label="name ? `${address} · ${name}` : address" :value="address" />
            </el-select>
          </el-form-item>
          <el-form-item :label="label('port')"><el-input-number v-model="config.port" :min="1" :max="65535" /></el-form-item>
          <template v-if="editing.id !== 'iperf'">
            <el-form-item :label="label('timeout')"><el-input-number v-model="config.timeout" :min="1" :max="30" /></el-form-item>
            <el-form-item :label="label('connections')"><el-input-number v-model="config.max_connections" :min="1" :max="32" /></el-form-item>
          </template>
          <el-form-item :label="label('logLevel')">
            <el-select v-model="config.log_level"><el-option value="INFO" /><el-option value="WARNING" /></el-select>
          </el-form-item>
        </div>
        <el-form-item v-if="editing.root" :label="label('root')"><el-input :model-value="editing.root" readonly /></el-form-item>
        <el-form-item v-if="editing.id === 'dns'" :label="label('dns')"><el-input v-model="dns" type="textarea" :rows="4" /></el-form-item>
        <el-form-item v-if="['tftp', 'ftp'].includes(editing.id)" :label="label('upload')"><el-switch v-model="config.allow_upload" /></el-form-item>
        <template v-if="editing.id === 'ftp'">
          <el-form-item :label="label('username')"><el-input v-model="config.ftp_username" maxlength="32" /></el-form-item>
          <el-form-item :label="label('passivePorts')"><el-input v-model="passivePorts" :placeholder="label('passivePortsHint')" /></el-form-item>
        </template>
        <el-form-item v-if="editing.id === 'ftp' && editing.tls_supported" :label="label('tlsEnabled')"><el-switch v-model="config.tls_enabled" /></el-form-item>
        <el-alert v-if="config.tls_enabled" :title="label('tlsWarning')" type="warning" :closable="false" />
        <el-form-item v-if="config.tls_enabled && editing.certificate_fingerprint" :label="label('fingerprint')"><el-input :model-value="editing.certificate_fingerprint" readonly /></el-form-item>
        <el-form-item :label="label('autoRestart')"><el-switch v-model="config.auto_restart" /></el-form-item>
      </el-form>
      <pre v-else class="log" aria-live="polite">{{ logs.length ? logs.join('\n') : label('noLogs') }}</pre>
      <template #footer>
        <el-button @click="dialogOpen = false">{{ label('cancel') }}</el-button>
        <el-button v-if="editing" type="primary" :loading="pending.includes(editing.id)" @click="save">{{ label('save') }}</el-button>
        <el-button v-if="logging" @click="showLogs(logging)">{{ label('refresh') }}</el-button>
      </template>
    </el-dialog>
    <el-dialog :model-value="!!ftpCredential" :title="label('ftpCredential')" width="min(380px, 92vw)" @close="ftpCredential = undefined">
      <div v-if="ftpCredential">
        <el-alert :title="ftpCredentialSecure ? label('tlsWarning') : label('cleartext')" :type="ftpCredentialSecure ? 'info' : 'warning'" :closable="false" />
        <el-form label-position="top">
          <el-form-item :label="label('username')"><el-input :model-value="ftpCredential.username" readonly /></el-form-item>
          <el-form-item :label="label('password')"><el-input :model-value="ftpCredential.password" readonly /></el-form-item>
        </el-form>
      </div>
    </el-dialog>
  </section>
</template>

<style scoped>
.local-services { display: flex; flex-direction: column; gap: 16px; min-width: 0; overflow: auto; }
header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
h1 { margin: 0; font-size: 20px; }
h2 { margin: 0 0 6px; font-size: 14px; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 900px; font-size: 13px; text-align: left; }
thead { background: var(--el-fill-color-light); color: var(--el-text-color-secondary); }
th, td { border-bottom: 1px solid var(--el-border-color-lighter); padding: 6px 10px; }
th { font-weight: 600; }
tbody th { width: 84px; }
td { height: 34px; }
.endpoint { font-variant-numeric: tabular-nums; white-space: nowrap; }
.runtime { min-width: 220px; font-variant-numeric: tabular-nums; }
.actions { width: 245px; white-space: nowrap; }
.actions .el-button { margin-left: 0; padding: 6px; }
.status { white-space: nowrap; }
.status--running { color: var(--el-color-success); }
.status--error, .status--port_conflict { color: var(--el-color-danger); }
.status--dependency_missing, .status--deferred { color: var(--el-text-color-secondary); }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 12px; }
.log { max-height: min(52vh, 28rem); overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
