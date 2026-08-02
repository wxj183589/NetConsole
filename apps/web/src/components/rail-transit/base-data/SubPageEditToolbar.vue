<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'

type EditState = 'LOCKED' | 'UNLOCKED_CLEAN' | 'UNLOCKED_DIRTY' | 'VALIDATING' | 'SAVING' | 'SAVE_FAILED' | 'READ_ONLY'

const props = withDefaults(defineProps<{
  state: EditState
  writable: boolean
  loading?: boolean
  valid?: boolean
  dirty?: boolean
}>(), {
  loading: false,
  valid: true,
  dirty: false,
})

const emit = defineEmits<{
  refresh: []
  unlock: []
  cancel: []
  save: []
}>()

function isEditing(): boolean {
  return ['UNLOCKED_CLEAN', 'UNLOCKED_DIRTY', 'VALIDATING', 'SAVING', 'SAVE_FAILED'].includes(props.state)
}

function isSaving(): boolean {
  return props.state === 'VALIDATING' || props.state === 'SAVING'
}
</script>

<template>
  <div class="subpage-edit-toolbar">
    <div class="subpage-edit-status">
      <el-tag v-if="dirty || state === 'UNLOCKED_DIRTY' || state === 'SAVE_FAILED'" type="warning">当前子页有未保存修改</el-tag>
      <el-tag v-else-if="isEditing()" type="success">当前子页已解锁</el-tag>
      <el-tag v-else-if="state === 'READ_ONLY'" type="info">只读</el-tag>
      <el-tag v-else type="info">当前子页已锁定</el-tag>
    </div>
    <div class="subpage-edit-actions">
      <el-button :icon="Refresh" :loading="loading" :disabled="isSaving()" @click="emit('refresh')">刷新</el-button>
      <el-button v-if="state === 'LOCKED' && writable" type="primary" :disabled="loading" @click="emit('unlock')">解锁当前子页</el-button>
      <template v-else-if="isEditing()">
        <el-button :disabled="isSaving()" @click="emit('cancel')">{{ dirty ? '取消修改' : '锁定当前子页' }}</el-button>
        <el-button type="primary" :loading="isSaving()" :disabled="!dirty || valid === false" @click="emit('save')">保存当前子页</el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.subpage-edit-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.subpage-edit-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
