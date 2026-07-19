<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Lock, WarningFilled, CircleCheckFilled, InfoFilled } from '@element-plus/icons-vue'
import { confirmState, resolveConfirm } from './useConfirm'

const acknowledged = ref(false)
const busy = ref(false)
const request = computed(() => confirmState.request)
const visible = computed({
  get: () => Boolean(request.value),
  set: (value: boolean) => { if (!value) resolveConfirm('cancel') },
})
const type = computed(() => request.value?.options.type || 'WARNING')
const needsAcknowledgement = computed(() => Boolean(request.value?.options.requireAcknowledgement))
const canConfirm = computed(() => !needsAcknowledgement.value || acknowledged.value)
const icon = computed(() => type.value === 'SECURITY' ? Lock : type.value === 'INFO' ? InfoFilled : type.value === 'WARNING' ? WarningFilled : CircleCheckFilled)
const dialogClass = computed(() => `nc-confirm-dialog nc-confirm-${type.value.toLowerCase()}`)

watch(request, () => {
  acknowledged.value = false
  busy.value = false
})
onMounted(() => { confirmState.providerReady = true })
onBeforeUnmount(() => { confirmState.providerReady = false })

function cancel(): void { if (!busy.value) resolveConfirm('cancel') }
function submit(result: 'confirm' | 'secondary' = 'confirm'): void {
  if (!canConfirm.value || busy.value) return
  busy.value = true
  resolveConfirm(result)
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="request?.title"
    :width="'min(620px, calc(100vw - 32px))'"
    :class="dialogClass"
    align-center
    append-to-body
    :close-on-press-escape="request?.options.closeOnEscape !== false"
    :close-on-click-modal="false"
    @close="cancel"
  >
    <div v-if="request" class="nc-confirm-body">
      <el-icon class="nc-confirm-icon"><component :is="icon" /></el-icon>
      <div class="nc-confirm-copy">
        <p class="nc-confirm-message">{{ request.message }}</p>
        <p v-if="request.options.detail" class="nc-confirm-detail">{{ request.options.detail }}</p>
        <el-alert v-if="type === 'SECURITY' || type === 'DESTRUCTIVE'" :title="type === 'SECURITY' ? '请确认你了解该操作的安全影响。' : '该操作可能影响现有数据。'" :type="type === 'SECURITY' ? 'warning' : 'error'" show-icon :closable="false" />
        <el-checkbox v-if="needsAcknowledgement" v-model="acknowledged" class="nc-confirm-ack">{{ request.options.acknowledgementText || '我已了解上述风险' }}</el-checkbox>
      </div>
    </div>
    <template #footer>
      <div class="nc-confirm-footer">
        <el-button :disabled="busy" @click="cancel">{{ request?.options.cancelText || '取消' }}</el-button>
        <el-button v-if="request?.options.secondaryText" :type="type === 'DANGER' || type === 'DESTRUCTIVE' ? 'danger' : 'primary'" :loading="busy" :disabled="!canConfirm" @click="submit('secondary')">
          {{ request.options.secondaryText }}
        </el-button>
        <el-button :type="type === 'DANGER' || type === 'DESTRUCTIVE' ? 'danger' : 'primary'" :loading="busy" :disabled="!canConfirm" @click="submit('confirm')">
          {{ request?.options.confirmText || '确认操作' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.nc-confirm-body{display:flex;gap:14px;align-items:flex-start}.nc-confirm-icon{font-size:28px;color:var(--el-color-warning);margin-top:2px}.nc-confirm-security .nc-confirm-icon{color:var(--el-color-danger)}.nc-confirm-danger .nc-confirm-icon,.nc-confirm-destructive .nc-confirm-icon{color:var(--el-color-danger)}.nc-confirm-copy{min-width:0;flex:1}.nc-confirm-message{margin:0;white-space:pre-wrap;line-height:1.6}.nc-confirm-detail{margin:10px 0 0;white-space:pre-wrap;color:var(--el-text-color-secondary);line-height:1.5}.nc-confirm-ack{display:block;margin-top:14px}.nc-confirm-footer{display:flex;justify-content:flex-end;gap:10px}
</style>
