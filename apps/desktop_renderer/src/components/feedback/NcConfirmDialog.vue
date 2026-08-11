<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Lock, WarningFilled, CircleCheckFilled, InfoFilled } from '@element-plus/icons-vue'
import { confirmState, resolveConfirm } from './useConfirm'

const acknowledged = ref(false)
const confirmationValue = ref('')
const busy = ref(false)
const cancelButton = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
const request = computed(() => confirmState.request)
const visible = computed({
  get: () => Boolean(request.value),
  set: (value: boolean) => { if (!value) cancel() },
})
const type = computed(() => request.value?.options.type || 'WARNING')
const needsAcknowledgement = computed(() => Boolean(request.value?.options.requireAcknowledgement))
const needsTypedConfirmation = computed(() => Boolean(request.value?.options.confirmationText))
const canConfirm = computed(() => (
  (!needsAcknowledgement.value || acknowledged.value)
  && (!needsTypedConfirmation.value || confirmationValue.value === request.value?.options.confirmationText)
))
const icon = computed(() => type.value === 'SECURITY' ? Lock : type.value === 'INFO' ? InfoFilled : type.value === 'WARNING' || type.value === 'DANGER' || type.value === 'DESTRUCTIVE' ? WarningFilled : CircleCheckFilled)
const dialogClass = computed(() => `nc-confirm-dialog nc-confirm-${type.value.toLowerCase()}`)
const dialogWidth = computed(() => request.value?.options.width || 'min(620px, calc(100vw - 32px))')
const messageParts = computed(() => {
  const message = request.value?.message || ''
  const highlight = request.value?.options.highlight || ''
  const index = highlight ? message.indexOf(highlight) : -1
  return index < 0
    ? null
    : {
        before: message.slice(0, index),
        highlight,
        after: message.slice(index + highlight.length),
      }
})

watch(request, async (value) => {
  acknowledged.value = false
  confirmationValue.value = ''
  busy.value = false
  if (value) {
    await nextTick()
    focusCancel()
  }
})
onMounted(() => { confirmState.providerReady = true })
onBeforeUnmount(() => { confirmState.providerReady = false })

function cancel(): void { if (!busy.value) resolveConfirm('cancel') }
function focusCancel(event?: Event): void {
  event?.preventDefault()
  void nextTick(() => {
    const target = cancelButton.value
    const element = target instanceof HTMLElement ? target : target?.$el
    element?.focus()
  })
}
async function submit(result: 'confirm' | 'secondary' = 'confirm'): Promise<void> {
  if (!canConfirm.value || busy.value) return
  const activeRequest = request.value
  if (!activeRequest) return
  busy.value = true
  try {
    if (result === 'confirm') await activeRequest.options.onConfirm?.()
    if (request.value === activeRequest) resolveConfirm(result)
  } catch {
    if (request.value === activeRequest) busy.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="request?.title"
    :width="dialogWidth"
    :class="dialogClass"
    align-center
    append-to-body
    :show-close="!busy"
    :close-on-press-escape="!busy && request?.options.closeOnEscape !== false"
    :close-on-click-modal="false"
    @open-auto-focus="focusCancel"
    @opened="focusCancel"
    @close="cancel"
  >
    <div v-if="request" class="nc-confirm-body">
      <el-icon class="nc-confirm-icon"><component :is="icon" /></el-icon>
      <div class="nc-confirm-copy">
        <p class="nc-confirm-message">
          <template v-if="messageParts">
            {{ messageParts.before }}<strong>{{ messageParts.highlight }}</strong>{{ messageParts.after }}
          </template>
          <template v-else>{{ request.message }}</template>
        </p>
        <p v-if="request.options.detail" class="nc-confirm-detail">{{ request.options.detail }}</p>
        <div v-if="request.options.notice" class="nc-confirm-notice">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ request.options.notice }}</span>
        </div>
        <el-alert v-if="type === 'SECURITY' || type === 'DESTRUCTIVE'" :title="type === 'SECURITY' ? '请确认你了解该操作的安全影响。' : '该操作可能影响现有数据。'" :type="type === 'SECURITY' ? 'warning' : 'error'" show-icon :closable="false" />
        <el-checkbox v-if="needsAcknowledgement" v-model="acknowledged" class="nc-confirm-ack">{{ request.options.acknowledgementText || '我已了解上述风险' }}</el-checkbox>
        <div v-if="needsTypedConfirmation" class="nc-confirm-typed">
          <label for="nc-confirm-typed-input">{{ request.options.confirmationLabel || '请输入完整名称以确认' }}</label>
          <el-input
            id="nc-confirm-typed-input"
            v-model="confirmationValue"
            data-testid="nc-confirm-typed-input"
            :placeholder="request.options.confirmationPlaceholder || request.options.confirmationText"
            autocomplete="off"
            @keyup.enter="submit('confirm')"
          />
        </div>
      </div>
    </div>
    <template #footer>
      <div class="nc-confirm-footer">
        <el-button ref="cancelButton" autofocus :disabled="busy" @click="cancel">{{ request?.options.cancelText || '取消' }}</el-button>
        <el-button v-if="request?.options.secondaryText" :type="type === 'DANGER' || type === 'DESTRUCTIVE' ? 'danger' : 'primary'" :loading="busy" :disabled="!canConfirm" @click="submit('secondary')">
          {{ request.options.secondaryText }}
        </el-button>
        <el-button :type="type === 'DANGER' || type === 'DESTRUCTIVE' ? 'danger' : 'primary'" :loading="busy" :disabled="!canConfirm" @click="submit('confirm')">
          {{ busy ? request?.options.confirmLoadingText || request?.options.confirmText || '处理中…' : request?.options.confirmText || '确认操作' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.nc-confirm-body{display:flex;gap:14px;align-items:flex-start}.nc-confirm-icon{flex:0 0 auto;font-size:26px;color:var(--el-color-warning);margin-top:1px}.nc-confirm-security .nc-confirm-icon{color:var(--el-color-danger)}.nc-confirm-danger .nc-confirm-icon,.nc-confirm-destructive .nc-confirm-icon{color:var(--el-color-danger)}.nc-confirm-copy{min-width:0;flex:1}.nc-confirm-message{margin:0;white-space:pre-wrap;line-height:1.65}.nc-confirm-message strong{color:var(--nc-text-primary);font-weight:700}.nc-confirm-detail{margin:10px 0 0;white-space:pre-wrap;color:var(--el-text-color-secondary);line-height:1.5}.nc-confirm-notice{display:flex;align-items:flex-start;gap:8px;margin-top:14px;padding:11px 12px;border:1px solid var(--nc-border-light);border-radius:8px;background:var(--nc-bg-muted);color:var(--nc-text-secondary);font-size:12px;line-height:1.6}.nc-confirm-notice .el-icon{flex:0 0 auto;margin-top:3px;color:var(--nc-info)}.nc-confirm-ack{display:block;margin-top:14px}.nc-confirm-typed{display:grid;gap:7px;margin-top:14px}.nc-confirm-typed label{color:var(--nc-text-secondary);font-size:12px}.nc-confirm-footer{display:flex;justify-content:flex-end;gap:10px}
</style>
