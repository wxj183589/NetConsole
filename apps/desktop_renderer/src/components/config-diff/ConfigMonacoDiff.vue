<script lang="ts">
export interface ConfigMonacoDiffProps {
  originalText: string
  modifiedText: string
  originalLabel: string
  modifiedLabel: string
  comparisonId: string
  renderSideBySide?: boolean
  wordWrap?: boolean
}

let componentSequence = 0
</script>

<script setup lang="ts">
import {
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
  watch,
} from 'vue'
import type * as Monaco from 'monaco-editor/editor/editor.api.js'

import { t } from '../../i18n/runtime'
import { NETCONSOLE_THEME_CHANGE_EVENT } from '../../theme/theme'

const props = withDefaults(defineProps<ConfigMonacoDiffProps>(), {
  renderSideBySide: true,
  wordWrap: false,
})
const emit = defineEmits<{
  ready: []
  initializationError: [message: string]
  diffUpdated: [changeCount: number]
  layoutChange: [renderSideBySide: boolean]
}>()

const container = ref<HTMLElement | null>(null)
const loadError = ref('')
let monaco: typeof Monaco | null = null
let editor: Monaco.editor.IStandaloneDiffEditor | null = null
let originalModel: Monaco.editor.ITextModel | null = null
let modifiedModel: Monaco.editor.ITextModel | null = null
let diffSubscription: Monaco.IDisposable | null = null
let resizeObserver: ResizeObserver | null = null
let listeningForTheme = false
let disposed = false
let active = true
let modelGeneration = 0

const componentId = ++componentSequence

onMounted(() => {
  void initialize()
})

onActivated(() => {
  active = true
  bindEnvironmentListeners()
  syncTheme()
  void nextTick(() => editor?.layout())
})

onDeactivated(() => {
  active = false
  unbindEnvironmentListeners()
})

onBeforeUnmount(() => {
  disposed = true
  unbindEnvironmentListeners()
  disposeEditor()
})

watch(
  () => [props.originalText, props.modifiedText] as const,
  ([originalText, modifiedText]) => {
    if (originalModel && originalModel.getValue() !== originalText) originalModel.setValue(originalText)
    if (modifiedModel && modifiedModel.getValue() !== modifiedText) modifiedModel.setValue(modifiedText)
  },
)

watch(
  () => props.comparisonId,
  () => {
    if (editor && monaco) replaceModels()
  },
)

watch(
  () => props.renderSideBySide,
  (renderSideBySide) => {
    editor?.updateOptions({ renderSideBySide })
    emit('layoutChange', renderSideBySide)
    editor?.layout()
  },
)

watch(
  () => props.wordWrap,
  (wordWrap) => {
    editor?.updateOptions({
      diffWordWrap: wordWrap ? 'on' : 'off',
      wordWrap: wordWrap ? 'on' : 'off',
    })
  },
)

async function initialize(): Promise<void> {
  try {
    const environment = await import('../../platform/monacoEnvironment')
    const loaded = await environment.loadMonacoEditor()
    if (disposed || !container.value) return
    monaco = loaded
    editor = monaco.editor.createDiffEditor(container.value, {
      readOnly: true,
      originalEditable: false,
      renderSideBySide: props.renderSideBySide,
      enableSplitViewResizing: true,
      automaticLayout: false,
      scrollBeyondLastLine: false,
      minimap: { enabled: false },
      lineNumbers: 'on',
      glyphMargin: false,
      folding: true,
      renderOverviewRuler: true,
      wordWrap: props.wordWrap ? 'on' : 'off',
      diffWordWrap: props.wordWrap ? 'on' : 'off',
      ignoreTrimWhitespace: false,
    })
    editor.getOriginalEditor().updateOptions({ largeFileOptimizations: true })
    editor.getModifiedEditor().updateOptions({ largeFileOptimizations: true })
    replaceModels()
    diffSubscription = editor.onDidUpdateDiff(() => {
      emit('diffUpdated', editor?.getLineChanges()?.length ?? 0)
    })
    bindEnvironmentListeners()
    syncTheme()
    emit('ready')
  } catch {
    if (disposed) return
    const message = t(
      'config_diff.monaco_failed',
      '高级配置对比器加载失败，已切换到基础差异视图。',
    )
    loadError.value = message
    emit('initializationError', message)
  }
}

function replaceModels(): void {
  if (!editor || !monaco) return
  const previousOriginal = originalModel
  const previousModified = modifiedModel
  modelGeneration += 1
  const identifier = encodeURIComponent(props.comparisonId || 'comparison')
  const authority = `${identifier}-${componentId}-${modelGeneration}`
  originalModel = monaco.editor.createModel(
    props.originalText,
    'plaintext',
    monaco.Uri.parse(`netconsole://config-diff/${authority}/original.cfg`),
  )
  modifiedModel = monaco.editor.createModel(
    props.modifiedText,
    'plaintext',
    monaco.Uri.parse(`netconsole://config-diff/${authority}/modified.cfg`),
  )
  editor.setModel({ original: originalModel, modified: modifiedModel })
  previousOriginal?.dispose()
  previousModified?.dispose()
}

function monacoThemeFromDocument(): 'vs' | 'vs-dark' {
  return document.documentElement.dataset.theme === 'dark' ? 'vs-dark' : 'vs'
}

function syncTheme(): void {
  if (monaco) monaco.editor.setTheme(monacoThemeFromDocument())
}

function bindEnvironmentListeners(): void {
  if (!active || !editor || !container.value) return
  if (!listeningForTheme) {
    window.addEventListener(NETCONSOLE_THEME_CHANGE_EVENT, syncTheme)
    listeningForTheme = true
  }
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver ??= new ResizeObserver(() => editor?.layout())
    resizeObserver.observe(container.value)
  }
}

function unbindEnvironmentListeners(): void {
  if (listeningForTheme) {
    window.removeEventListener(NETCONSOLE_THEME_CHANGE_EVENT, syncTheme)
    listeningForTheme = false
  }
  resizeObserver?.disconnect()
}

function disposeEditor(): void {
  diffSubscription?.dispose()
  diffSubscription = null
  editor?.dispose()
  editor = null
  originalModel?.dispose()
  originalModel = null
  modifiedModel?.dispose()
  modifiedModel = null
  resizeObserver = null
  monaco = null
}

function revealDifference(leftLine: number | null, rightLine: number | null): void {
  if (!editor) return
  if (leftLine !== null) editor.getOriginalEditor().revealLineInCenter(leftLine)
  if (rightLine !== null) editor.getModifiedEditor().revealLineInCenter(rightLine)
}

function layout(): void {
  editor?.layout()
}

function focus(): void {
  editor?.getModifiedEditor().focus()
}

defineExpose({ revealDifference, layout, focus })
</script>

<template>
  <div class="config-monaco-diff">
    <div class="diff-labels" aria-hidden="true">
      <strong data-testid="monaco-original-label">{{ originalLabel }}</strong>
      <strong data-testid="monaco-modified-label">{{ modifiedLabel }}</strong>
    </div>
    <div
      v-if="!loadError"
      ref="container"
      class="diff-editor"
      data-testid="monaco-diff-editor"
      :aria-label="t('config_diff.visual_aria', '配置差异可视化对比')"
    />
    <el-alert v-else :title="loadError" type="warning" :closable="false" show-icon />
  </div>
</template>

<style scoped>
.config-monaco-diff {
  display: flex;
  min-width: 0;
  min-height: 420px;
  height: clamp(420px, 56vh, 720px);
  flex-direction: column;
  background: var(--nc-bg-panel);
}

.diff-labels {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1px;
  border-bottom: 1px solid var(--nc-divider);
  background: var(--nc-divider);
}

.diff-labels strong {
  min-width: 0;
  padding: 8px 12px;
  overflow: hidden;
  color: var(--nc-text-secondary);
  background: var(--nc-bg-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diff-editor {
  min-width: 0;
  min-height: 0;
  flex: 1;
}

@media (max-width: 760px) {
  .config-monaco-diff {
    height: clamp(420px, 68vh, 620px);
  }
}
</style>
