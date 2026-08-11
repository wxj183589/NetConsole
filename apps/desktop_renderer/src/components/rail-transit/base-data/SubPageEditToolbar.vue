<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'

type DraftState = 'VIEW' | 'EDITING' | 'DIRTY' | 'VALIDATING' | 'SAVING' | 'SAVE_FAILED' | 'READ_ONLY'

const props = withDefaults(defineProps<{
  state: DraftState
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
  discard: []
  save: []
}>()

function isSaving(): boolean {
  return props.state === 'VALIDATING' || props.state === 'SAVING'
}
</script>

<template>
  <div class="subpage-edit-toolbar">
    <div class="subpage-edit-status">
      <el-tag v-if="loading" type="info">正在加载草稿</el-tag>
      <el-tag v-else-if="state === 'VALIDATING'" type="info">正在校验</el-tag>
      <el-tag v-else-if="state === 'SAVING'" type="info">正在保存</el-tag>
      <el-tag v-else-if="state === 'SAVE_FAILED'" type="danger">保存失败，草稿已保留</el-tag>
      <el-tag v-else-if="dirty || state === 'DIRTY'" type="warning">当前子页有未保存修改</el-tag>
      <el-tag v-else-if="state === 'READ_ONLY'" type="info">只读</el-tag>
      <el-tag v-else-if="state === 'EDITING'" type="warning">当前子页编辑中</el-tag>
      <el-tag v-else type="info">当前子页查看中</el-tag>
    </div>
    <div class="subpage-edit-actions">
      <el-button :icon="Refresh" :loading="loading" :disabled="isSaving()" @click="emit('refresh')">刷新</el-button>
      <template v-if="state === 'VIEW'">
        <el-button type="primary" :disabled="loading || isSaving()" @click="emit('unlock')">解锁当前子页</el-button>
        <el-button type="primary" disabled>保存当前子页</el-button>
      </template>
      <template v-else-if="state !== 'READ_ONLY'">
        <el-button :disabled="loading || isSaving()" @click="emit('discard')">放弃修改</el-button>
        <el-button type="primary" :loading="isSaving()" :disabled="loading || !dirty || valid === false" @click="emit('save')">保存当前子页</el-button>
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
