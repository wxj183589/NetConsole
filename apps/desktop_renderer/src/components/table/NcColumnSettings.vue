<script setup lang="ts">
import { ArrowDown, ArrowUp, MagicStick, Refresh, Setting } from '@element-plus/icons-vue'

import { t } from '../../i18n/runtime'
import { ref } from 'vue'

export interface NcColumnSettingItem {
  key: string
  label: string
  visible: boolean
  hideable: boolean
  fixed: 'left' | 'right' | false
}
export interface NcColumnDraftOptions { reset: boolean; autofit: boolean }

const props = withDefaults(defineProps<{
  columns: readonly NcColumnSettingItem[]
  defaultColumns?: readonly NcColumnSettingItem[]
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
  apply: [columns: NcColumnSettingItem[], options?: NcColumnDraftOptions]
}>()
const opened = ref(false)
const draft = ref<NcColumnSettingItem[]>([])
const draftOptions = ref<NcColumnDraftOptions>({ reset: false, autofit: false })
function begin(): void { draft.value = props.columns.map(column => ({ ...column })); draftOptions.value = { reset: false, autofit: false } }
function resetDraft(): void { draft.value = (props.defaultColumns ?? props.columns).map(column => ({ ...column })); draftOptions.value = { reset: true, autofit: true } }
function toggle(key: string, visible: boolean): void {
  const item = draft.value.find(column => column.key === key)
  if (item?.hideable && (visible || draft.value.filter(column => column.visible).length > 1)) item.visible = visible
}
function move(index: number, direction: number): void {
  const target = index + direction
  if (target >= 0 && target < draft.value.length) [draft.value[index], draft.value[target]] = [draft.value[target]!, draft.value[index]!]
}
function pin(column: NcColumnSettingItem): void { column.fixed = column.fixed === 'left' ? 'right' : column.fixed === 'right' ? false : 'left' }
function apply(): void { emit('apply', draft.value.map(column => ({ ...column })), { ...draftOptions.value }); opened.value = false }
</script>

<template>
  <el-popover v-model:visible="opened" placement="bottom-end" :width="370" trigger="click" @show="begin">
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
          <el-tooltip :content="t('table.autofit', '自动适应列宽')" placement="top"><el-button :icon="MagicStick" link :aria-label="t('table.autofit', '自动适应列宽')" :type="draftOptions.autofit ? 'primary' : ''" @click="draftOptions.autofit = true" /></el-tooltip>
          <el-tooltip :content="t('table.reset_layout', '恢复默认布局')" placement="top"><el-button :icon="Refresh" link :aria-label="t('table.reset_layout', '恢复默认布局')" @click="resetDraft" /></el-tooltip>
        </div>
      </div>
      <div class="nc-column-settings__list">
        <div v-for="(column, index) in draft" :key="column.key" class="nc-column-settings__item">
          <el-checkbox
            :model-value="column.visible"
            :disabled="!column.hideable"
            @change="toggle(column.key, Boolean($event))"
          >{{ column.label }}</el-checkbox>
          <div class="nc-column-settings__actions">
            <el-tooltip :content="t('table.pin', '固定位置')" placement="top">
              <el-button link :type="column.fixed ? 'primary' : ''" @click="pin(column)">
                {{ column.fixed === 'left' ? t('table.pin_left', '左') : column.fixed === 'right' ? t('table.pin_right', '右') : t('table.unpinned', '不固定') }}
              </el-button>
            </el-tooltip>
            <el-button :icon="ArrowUp" link :disabled="index === 0" :aria-label="t('table.move_up', '上移')" @click="move(index, -1)" />
            <el-button :icon="ArrowDown" link :disabled="index === draft.length - 1" :aria-label="t('table.move_down', '下移')" @click="move(index, 1)" />
          </div>
        </div>
      </div>
      <div class="nc-column-settings__footer"><el-button @click="opened = false">{{ t('common.cancel', '取消') }}</el-button><el-button type="primary" @click="apply">{{ t('table.apply_query', '应用并查询') }}</el-button></div>
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
