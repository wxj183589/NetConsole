<script setup lang="ts">
import { computed } from 'vue'
import { Briefcase, Lock, MoreFilled, Star, StarFilled, VideoPlay, WarningFilled } from '@element-plus/icons-vue'

import type { ExternalToolView } from '../../../types/externalTools'

const props = defineProps<{ tool: ExternalToolView; launching?: boolean }>()
const emit = defineEmits<{
  launch: [tool: ExternalToolView]
  'launch-admin': [tool: ExternalToolView]
  favorite: [tool: ExternalToolView]
  edit: [tool: ExternalToolView]
  reveal: [tool: ExternalToolView]
  remove: [tool: ExternalToolView]
  relocate: [tool: ExternalToolView]
  configure: [tool: ExternalToolView]
}>()

const available = computed(() => props.tool.status === 'AVAILABLE')
const statusType = computed(() => props.tool.status === 'MISSING' ? 'danger' : 'warning')

function handleCommand(command: string): void {
  if (command === 'edit') emit('edit', props.tool)
  else if (command === 'launch-admin') emit('launch-admin', props.tool)
  else if (command === 'configure') emit('configure', props.tool)
  else if (command === 'reveal') emit('reveal', props.tool)
  else if (command === 'remove') emit('remove', props.tool)
}
</script>

<template>
  <article
    class="external-tool-card"
    :class="{ 'external-tool-card--unavailable': !available }"
    :title="tool.executable_path"
    :data-testid="`external-tool-${tool.id}`"
    @click="available && emit('launch', tool)"
  >
    <div class="tool-card-icon">
      <img v-if="tool.icon_data_url" :src="tool.icon_data_url" alt="" />
      <el-icon v-else><Briefcase /></el-icon>
    </div>
    <div class="tool-card-body">
      <div class="tool-card-heading">
        <strong>{{ tool.name }}</strong>
        <el-button
          text
          circle
          :aria-label="tool.favorite ? '取消收藏' : '收藏'"
          @click.stop="emit('favorite', tool)"
        >
          <el-icon :class="{ favorite: tool.favorite }">
            <StarFilled v-if="tool.favorite" /><Star v-else />
          </el-icon>
        </el-button>
      </div>
      <div class="tool-card-meta">{{ tool.category_name }} · {{ tool.executable_name }}</div>
      <el-tag v-if="!available" :type="statusType" size="small" effect="light">
        <el-icon><WarningFilled /></el-icon>
        {{ tool.status_message }}
      </el-tag>
      <div class="tool-card-actions">
        <el-button
          v-if="available"
          type="primary"
          link
          :loading="launching"
          :disabled="launching"
          @click.stop="emit('launch', tool)"
        >
          <el-icon><VideoPlay /></el-icon>启动
        </el-button>
        <el-button v-else-if="tool.source_type === 'system_setting'" type="primary" link @click.stop="emit('configure', tool)">配置路径</el-button>
        <el-button v-else type="primary" link @click.stop="emit('relocate', tool)">重新定位程序</el-button>
        <el-dropdown trigger="click" @command="handleCommand" @click.stop>
          <el-button text circle aria-label="更多操作" @click.stop><el-icon><MoreFilled /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="launch-admin" :disabled="!available">
                <el-icon><Lock /></el-icon>本次以管理员身份启动
              </el-dropdown-item>
              <el-dropdown-item command="edit">编辑</el-dropdown-item>
              <el-dropdown-item v-if="tool.source_type === 'system_setting'" command="configure">配置路径</el-dropdown-item>
              <el-dropdown-item command="reveal" :disabled="!available">在资源管理器中显示</el-dropdown-item>
              <el-dropdown-item v-if="tool.source_type !== 'system_setting'" command="remove" divided>删除</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
  </article>
</template>

<style scoped>
.external-tool-card {
  display: flex;
  min-width: 0;
  min-height: 132px;
  padding: 16px;
  gap: 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  background: var(--el-bg-color);
  cursor: pointer;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}
.external-tool-card:hover { border-color: var(--el-color-primary-light-5); box-shadow: var(--el-box-shadow-light); transform: translateY(-1px); }
.external-tool-card--unavailable { cursor: default; background: var(--el-fill-color-lighter); }
.tool-card-icon { width: 52px; height: 52px; flex: 0 0 52px; display: grid; place-items: center; border-radius: 10px; background: var(--el-fill-color-light); color: var(--el-color-primary); font-size: 30px; overflow: hidden; }
.tool-card-icon img { width: 40px; height: 40px; object-fit: contain; }
.tool-card-body { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 7px; }
.tool-card-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.tool-card-heading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 16px; }
.tool-card-meta { color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.tool-card-actions { display: flex; align-items: center; justify-content: space-between; margin-top: auto; }
.favorite { color: var(--el-color-warning); }
</style>
