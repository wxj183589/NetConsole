<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { applyTracksideIssueAction, listTracksideIssues, type TracksideIssue, type TracksideIssueAction } from '../../api/tracksideApBusiness'

const props = defineProps<{ site: string; apUuid: string; apName: string }>()
const emit = defineEmits<{ close: [] }>()
const loading = ref(true)
const pending = ref(false)
const historyAvailable = ref(false)
const items = ref<TracksideIssue[]>([])
const error = ref('')
const notes = ref<Record<string, string>>({})
const actions: TracksideIssueAction[] = ['confirm', 'handle', 'verify', 'close']
const labels = { confirm: '确认问题', handle: '记录处理', verify: '验证恢复', close: '关闭问题' }
const issueLabels: Record<string, string> = { alarm: '光衰告警', warning: '光衰预警', no_light: '无光' }

onMounted(async () => {
  try {
    const result = await listTracksideIssues(props.site, props.apUuid)
    historyAvailable.value = result.history_available
    items.value = result.items
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '无法读取问题记录'
  } finally {
    loading.value = false
  }
})

function nextAction(item: TracksideIssue): TracksideIssueAction | undefined {
  return actions[item.operations.length]
}

function hasRecovery(item: TracksideIssue): boolean {
  return item.event_status === 'RESOLVED' && Boolean(item.resolved_at
    && (item.recovered_ap_rx_dbm || item.recovered_switch_rx_dbm))
}

function lifecycleLabel(item: TracksideIssue): string {
  switch (nextAction(item)) {
    case 'confirm': return '已发现'
    case 'handle': return '已确认'
    case 'verify': return hasRecovery(item) ? '恢复待验证' : '处理中'
    case 'close': return '已恢复'
    default: return '已关闭'
  }
}

function actionDisabled(item: TracksideIssue): boolean {
  const action = nextAction(item)
  return pending.value
    || (action === 'handle' && !notes.value[item.event_uuid]?.trim())
    || (action === 'verify' && !hasRecovery(item))
}

async function advance(item: TracksideIssue) {
  const action = nextAction(item)
  if (!action || actionDisabled(item)) return
  pending.value = true
  error.value = ''
  try {
    const updated = await applyTracksideIssueAction(props.site, item.event_uuid, action, notes.value[item.event_uuid] ?? '')
    items.value = items.value.map((entry) => entry.event_uuid === updated.event_uuid ? updated : entry)
    delete notes.value[item.event_uuid]
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '无法保存问题操作'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="true" :title="`${apName || apUuid} · 光衰问题记录`" width="min(920px, 92vw)" @close="emit('close')">
    <div v-loading="loading" class="issue-history">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-empty
        v-else-if="!loading && !items.length"
        :description="historyAvailable ? '未找到此 AP 的持久化问题记录' : '此局点无可用的问题历史'"
      />
      <el-collapse v-if="items.length" accordion>
        <el-collapse-item v-for="item in items" :key="item.event_uuid" :name="item.event_uuid">
          <template #title>
            {{ item.first_detected_at || '发现时间缺失' }} · {{ issueLabels[item.issue_type] || item.issue_type || '光衰' }}
            · {{ lifecycleLabel(item) }}
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="站点">{{ item.station_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="交换机端口">{{ [item.switch_name, item.switch_interface].filter(Boolean).join(' / ') || '—' }}</el-descriptions-item>
            <el-descriptions-item label="AP UUID">{{ item.ap_uuid || '—' }}</el-descriptions-item>
            <el-descriptions-item label="交换机 UUID">{{ item.switch_device_id || '—' }}</el-descriptions-item>
            <el-descriptions-item label="首次 AP / 交换机收光 (dBm)">{{ item.first_ap_rx_dbm || '—' }} / {{ item.first_switch_rx_dbm || '—' }}</el-descriptions-item>
            <el-descriptions-item label="恢复 AP / 交换机收光 (dBm)">{{ item.recovered_ap_rx_dbm || '—' }} / {{ item.recovered_switch_rx_dbm || '—' }}</el-descriptions-item>
            <el-descriptions-item label="最后异常时间">{{ item.last_abnormal_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="恢复时间">{{ item.resolved_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="证据来源" :span="2">{{ item.evidence_quality || '—' }}</el-descriptions-item>
            <el-descriptions-item label="首次异常来源版本">{{ item.source_revision_first || '—' }}</el-descriptions-item>
            <el-descriptions-item label="最近事件来源版本">{{ item.source_revision_last || '—' }}</el-descriptions-item>
          </el-descriptions>
          <ul v-if="item.operations.length">
            <li v-for="operation in item.operations" :key="operation.action">
              {{ operation.at }} · {{ labels[operation.action] }}<template v-if="operation.note"> · {{ operation.note }}</template>
            </li>
          </ul>
          <el-space v-if="nextAction(item)" wrap class="issue-actions">
            <el-input
              v-if="nextAction(item) === 'handle'"
              v-model="notes[item.event_uuid]"
              aria-label="处理措施"
              placeholder="处理措施"
              maxlength="1000"
              type="textarea"
            />
            <el-button :disabled="actionDisabled(item)" @click="advance(item)">
              {{ labels[actions[item.operations.length]] }}
            </el-button>
          </el-space>
        </el-collapse-item>
      </el-collapse>
    </div>
  </el-dialog>
</template>

<style scoped>
.issue-history {
  min-height: 5rem;
  max-height: 65vh;
  overflow: auto;
  overflow-wrap: anywhere;
}

.issue-actions {
  margin-top: 12px;
}
</style>
