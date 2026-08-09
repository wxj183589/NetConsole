<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Close, DataAnalysis, Unlock } from '@element-plus/icons-vue'

export interface OnlineMrAnalysisInfoField {
  label: string
  value: string
  tone?: 'normal' | 'success' | 'warning' | 'danger'
}

export interface OnlineMrAnalysisInfoSection {
  key: string
  title: string
  fields: OnlineMrAnalysisInfoField[]
}

const props = withDefaults(defineProps<{
  sections: OnlineMrAnalysisInfoSection[]
  locked?: boolean
  parserLabel?: string
  parserMessage?: string
  parserTone?: 'success' | 'warning' | 'danger' | 'info'
}>(), {
  locked: false,
  parserLabel: '解析状态未知',
  parserMessage: '',
  parserTone: 'info',
})

const emit = defineEmits<{ unlock: [] }>()
const narrow = ref(false)
const drawerOpen = ref(true)
let media: MediaQueryList | null = null

const tagType = computed(() => props.parserTone === 'danger' ? 'danger' : props.parserTone)

function applyNarrow(value: boolean): void {
  const changed = value !== narrow.value
  narrow.value = value
  if (changed && value) drawerOpen.value = false
  if (!value) drawerOpen.value = true
}

function handleMedia(event: MediaQueryListEvent): void {
  applyNarrow(event.matches)
}

onMounted(() => {
  if (typeof window.matchMedia !== 'function') return
  media = window.matchMedia('(max-width: 1399px)')
  applyNarrow(media.matches)
  media.addEventListener('change', handleMedia)
})

onBeforeUnmount(() => {
  media?.removeEventListener('change', handleMedia)
  media = null
})
</script>

<template>
  <div class="analysis-info-host" :class="{ 'is-narrow': narrow, 'is-open': drawerOpen }">
    <el-button
      v-if="narrow && !drawerOpen"
      class="analysis-info-toggle"
      :icon="DataAnalysis"
      title="展开分析信息"
      @click="drawerOpen = true"
    >分析信息</el-button>
    <aside v-show="!narrow || drawerOpen" class="analysis-info-panel" data-testid="online-mr-analysis-info-panel">
      <header class="analysis-info-header">
        <div>
          <strong>分析信息</strong>
          <span :class="{ 'is-locked': locked }">{{ locked ? '已锁定' : '跟随指针' }}</span>
        </div>
        <div class="analysis-info-actions">
          <el-button v-if="locked" text :icon="Unlock" title="解除时刻锁定" @click="emit('unlock')" />
          <el-button v-if="narrow" text :icon="Close" title="收起分析信息" @click="drawerOpen = false" />
        </div>
      </header>

      <el-tooltip :content="parserMessage || parserLabel" placement="right">
        <el-tag class="analysis-parser-status" :type="tagType" effect="plain">{{ parserLabel }}</el-tag>
      </el-tooltip>

      <div class="analysis-info-body">
        <section v-for="section in sections" :key="section.key" class="analysis-info-section">
          <h4>{{ section.title }}</h4>
          <dl>
            <template v-for="field in section.fields" :key="`${section.key}:${field.label}`">
              <dt>{{ field.label }}</dt>
              <dd :class="field.tone ? `is-${field.tone}` : undefined">{{ field.value }}</dd>
            </template>
          </dl>
        </section>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.analysis-info-host{position:relative;min-width:0;min-height:0;height:100%}
.analysis-info-panel{display:flex;width:clamp(240px,14vw,288px);height:100%;min-height:0;flex-direction:column;border-right:1px solid var(--el-border-color-lighter);background:var(--el-bg-color)}
.analysis-info-header{display:flex;min-height:40px;flex:none;align-items:center;justify-content:space-between;gap:8px;padding:4px 10px;border-bottom:1px solid var(--el-border-color-lighter)}
.analysis-info-header>div:first-child{display:flex;min-width:0;align-items:baseline;gap:8px}.analysis-info-header strong{font-size:14px}.analysis-info-header span{color:var(--el-text-color-secondary);font-size:11px}.analysis-info-header span.is-locked{color:var(--el-color-primary)}
.analysis-info-actions{display:flex;flex:none}.analysis-info-actions :deep(.el-button){width:28px;height:28px;margin:0;padding:0}
.analysis-parser-status{align-self:flex-start;max-width:calc(100% - 20px);margin:8px 10px 2px;overflow:hidden;text-overflow:ellipsis}
.analysis-info-body{min-height:0;flex:1;overflow-y:auto;overscroll-behavior:contain;padding:0 10px 10px}
.analysis-info-section{padding:9px 0;border-bottom:1px solid var(--el-border-color-lighter)}.analysis-info-section:last-child{border-bottom:0}
.analysis-info-section h4{margin:0 0 7px;font-size:12px;line-height:1.3}.analysis-info-section dl{display:grid;grid-template-columns:86px minmax(0,1fr);gap:5px 8px;margin:0;font-size:12px;line-height:1.35}
.analysis-info-section dt{color:var(--el-text-color-secondary)}.analysis-info-section dd{min-width:0;margin:0;overflow-wrap:anywhere;color:var(--el-text-color-primary)}
.analysis-info-section dd.is-success{color:var(--el-color-success)}.analysis-info-section dd.is-warning{color:var(--el-color-warning)}.analysis-info-section dd.is-danger{color:var(--el-color-danger)}
.analysis-info-toggle{position:absolute;top:4px;left:4px;z-index:7}
.analysis-info-host.is-narrow{position:absolute;inset:0 auto 0 0;z-index:8;width:0;height:100%}.analysis-info-host.is-narrow.is-open{width:min(288px,calc(100% - 56px));filter:drop-shadow(4px 0 10px rgb(0 0 0 / 16%))}.analysis-info-host.is-narrow .analysis-info-panel{width:100%;border:1px solid var(--el-border-color)}
</style>
