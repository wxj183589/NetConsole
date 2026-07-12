<script setup lang="ts">
import type { TaskStatus } from '../types/task'
import { taskStatusLabel, taskStatusType } from '../utils/taskStatus'

defineProps<{ status: TaskStatus }>()
</script>

<template>
  <el-tag :type="taskStatusType(status)" effect="light" round>{{ taskStatusLabel(status) }}</el-tag>
</template>
