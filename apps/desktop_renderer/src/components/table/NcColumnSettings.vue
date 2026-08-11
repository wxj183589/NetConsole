<script setup lang="ts">
import { ArrowDown, ArrowUp, MagicStick, Refresh, Setting } from '@element-plus/icons-vue'

import { t } from '../../i18n/runtime'

export interface NcColumnSettingItem {
  key: string
  label: string
  visible: boolean
  hideable: boolean
  fixed: 'left' | 'right' | false
}

withDefaults(defineProps<{
  columns: readonly NcColumnSettingItem[]
  preferenceState?: 'saved' | 'saving' | 'error'
}>(), {
  preferenceState: 'saved',
})

const emit = defineEmits<{
  toggle: [key: string, visible: boolean]
  move: [key: string, direction: -1 | 1]
  pin: [key: string]
  reset: []
  autofit: []
}>()
</script>

<template>
  <el-popover placement="bottom-end" :width="330" trigger="click">
    <template #reference>
      <span class="nc-column-settings__trigger">
        <el-tooltip :content="t('table.column_settings', '列设置')" placement="top">
          <el-button :icon="Setting" circle :aria-label="t('table.column_settings', '列设置')" />
        </el-tooltip>
      </span>
    </template>
    <div class="nc-column-settings">
      <div class="nc-column-settings__header">
        <strong>{{ t('table.column_settings', '列设置') }}</strong>
        <div>
          <el-tooltip :content="t('table.autofit', '自动适应列宽')" placement="top"><el-button :icon="MagicStick" link :aria-label="t('table.autofit', '自动适应列宽')" @click="emit('autofit')" /></el-tooltip>
          <el-tooltip :content="t('table.reset_layout', '恢复默认布局')" placement="top"><el-button :icon="Refresh" link :aria-label="t('table.reset_layout', '恢复默认布局')" @click="emit('reset')" /></el-tooltip>
        </div>
      </div>
      <div class="nc-column-settings__list">
        <div v-for="(column, index) in columns" :key="column.key" class="nc-column-settings__item">
          <el-checkbox
            :model-value="column.visible"
            :disabled="!column.hideable"
            @change="emit('toggle', column.key, Boolean($event))"
          >{{ column.label }}</el-checkbox>
          <div class="nc-column-settings__actions">
            <el-tooltip :content="t('table.pin', '固定位置')" placement="top">
              <el-button link :type="column.fixed ? 'primary' : ''" @click="emit('pin', column.key)">
                {{ column.fixed === 'left' ? t('table.pin_left', '左') : column.fixed === 'right' ? t('table.pin_right', '右') : t('table.unpinned', '不固定') }}
              </el-button>
            </el-tooltip>
            <el-button :icon="ArrowUp" link :disabled="index === 0" :aria-label="t('table.move_up', '上移')" @click="emit('move', column.key, -1)" />
            <el-button :icon="ArrowDown" link :disabled="index === columns.length - 1" :aria-label="t('table.move_down', '下移')" @click="emit('move', column.key, 1)" />
          </div>
        </div>
      </div>
      <div class="nc-column-settings__status" :class="`is-${preferenceState}`">
        {{ preferenceState === 'saving'
          ? t('table.preference_saving', '正在保存列设置')
          : preferenceState === 'error'
            ? t('table.preference_save_failed', '保存失败，当前设置仅在本次运行有效')
            : t('table.preference_saved', '已保存到本地配置') }}
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.nc-column-settings__header,
.nc-column-settings__item,
.nc-column-settings__actions { display: flex; align-items: center; }
.nc-column-settings__trigger { display: inline-flex; }
.nc-column-settings__header { justify-content: space-between; padding-bottom: 8px; border-bottom: 1px solid var(--nc-divider); }
.nc-column-settings__list { max-height: 360px; overflow-y: auto; }
.nc-column-settings__item { justify-content: space-between; gap: 12px; min-height: 38px; border-bottom: 1px solid var(--nc-divider); }
.nc-column-settings__item :deep(.el-checkbox) { min-width: 0; }
.nc-column-settings__item :deep(.el-checkbox__label) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-column-settings__actions { flex: 0 0 auto; gap: 2px; }
.nc-column-settings__status { padding-top: 8px; color: var(--nc-text-tertiary); font-size: 12px; }
.nc-column-settings__status.is-error { color: var(--nc-color-danger); }
</style>
