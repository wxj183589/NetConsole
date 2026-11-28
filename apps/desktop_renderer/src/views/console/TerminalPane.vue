<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { Terminal } from '@xterm/xterm'
import { ElMessage, ElMessageBox } from 'element-plus'
import '@xterm/xterm/css/xterm.css'

import { getPlatformAdapter } from '../../platform/runtime'
import { t } from '../../i18n/runtime'

import {
  issueTerminalTicket,
  terminalWebSocketUrl,
  type TerminalHighlightRule,
  type TerminalSession,
  type TerminalSettings,
  getTerminalHighlightRules,
  replaceTerminalHighlightRules,
} from '../../api/terminal'
import { describeTerminalPaste, extractTerminalUrl, isMultilinePaste, quotePastedLines } from './terminalContextActions'

const props = defineProps<{
  session: TerminalSession
  ticket?: string
  active?: boolean
  focused?: boolean
  closing?: boolean
  workspaceVisible?: boolean
  settings?: TerminalSettings | null
  highlightRules?: TerminalHighlightRule[]
  syncInput?: boolean
}>()

const emit = defineEmits<{
  session: [value: TerminalSession]
  notice: [message: string]
  connection: [connected: boolean]
  input: [data: string]
  synchronizedPaste: [text: string]
}>()

const host = ref<HTMLElement | null>(null)
const connected = ref(false)
let receivingSynchronizedPaste = false
const connectionMessage = ref('正在建立终端通道…')
let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let searchAddon: SearchAddon | null = null
let socket: WebSocket | null = null
let resizeObserver: ResizeObserver | null = null
let disposed = false
let initialTicket = props.ticket || ''
let reconnectAttempts = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let lastDimensions = ''
let opening = false
const contextMenu = ref<{ left: number; top: number; selectedText: string; url: string } | null>(null)
const findVisible = ref(false)
const findQuery = ref('')
const findCaseSensitive = ref(false)
const localHighlightRules = ref<TerminalHighlightRule[]>([])
let removeContextDismiss: (() => void) | null = null
const terminalEnded = () => props.closing || ['CLOSING', 'CLOSED', 'FAILED', 'CANCELLED', 'DISCONNECTED'].includes(props.session.state)
const mayFocus = () => props.focused !== false && props.active !== false && props.workspaceVisible !== false

interface TerminalContextAction {
  id: string
  label: string
  shortcut?: string
  needsSelection?: boolean
  needsUrl?: boolean
  needsConnection?: boolean
}

const contextActions = computed<TerminalContextAction[]>(() => [
  { id: 'copy', label: t('console.context.copy', '复制'), shortcut: 'Ctrl+Shift+C', needsSelection: true },
  { id: 'paste', label: t('console.context.paste', '粘贴'), shortcut: 'Ctrl+Shift+V', needsConnection: true },
  { id: 'copy-paste', label: t('console.context.copy_paste', '复制并粘贴'), needsSelection: true, needsConnection: true },
  { id: 'quoted-paste', label: t('console.context.quoted_paste', '粘贴为引用'), needsConnection: true },
  { id: 'open-url', label: t('console.context.open_url', '打开链接'), needsUrl: true },
  { id: 'add-keyword', label: t('console.context.add_keyword', '添加关键词'), needsSelection: true },
  { id: 'find', label: t('console.context.find', '查找'), shortcut: 'Ctrl+F' },
  { id: 'select-all', label: t('console.context.select_all', '全选'), shortcut: 'Ctrl+Shift+A' },
  { id: 'print', label: t('console.context.print', '打印选中内容'), needsSelection: true },
  { id: 'clear-scrollback', label: t('console.context.clear_scrollback', '清除回滚缓冲区') },
  { id: 'clear-screen', label: t('console.context.clear_screen', '清屏') },
  { id: 'clear-all', label: t('console.context.clear_all', '清屏并清除回滚缓冲区') },
])

function openContextMenu(event: MouseEvent): void {
  event.preventDefault()
  event.stopPropagation()
  const selectedText = terminal?.getSelection() || ''
  const line = terminal?.buffer.active.getLine(terminal.buffer.active.baseY + terminal.buffer.active.cursorY)?.translateToString(true) || ''
  const left = Math.max(8, Math.min(event.clientX, window.innerWidth - 250))
  const top = Math.max(8, Math.min(event.clientY, window.innerHeight - 410))
  contextMenu.value = {
    left,
    top,
    selectedText,
    url: extractTerminalUrl(selectedText || line),
  }
}

function contextActionDisabled(action: TerminalContextAction): boolean {
  if (!contextMenu.value) return true
  if (action.needsSelection && !contextMenu.value.selectedText) return true
  if (action.needsUrl && !contextMenu.value.url) return true
  if (action.needsConnection && (!connected.value || terminalEnded())) return true
  return false
}

async function copyText(text: string): Promise<boolean> {
  const result = await getPlatformAdapter().writeClipboardText(text)
  if (!result.success) {
    ElMessage.error(result.error || '无法写入系统剪贴板')
    return false
  }
  return true
}

async function readClipboard(): Promise<string | null> {
  const result = await getPlatformAdapter().readClipboardText()
  if (!result.success) {
    ElMessage.error(result.error || '无法读取系统剪贴板')
    return null
  }
  return result.text
}

async function pasteText(text: string, quoted = false): Promise<void> {
  if (!terminal || terminalEnded() || !connected.value) return
  if (props.syncInput) {
    emit('synchronizedPaste', quoted ? quotePastedLines(text) : text)
    return
  }
  const target = terminal
  const connection = socket
  const sessionId = props.session.session_id
  const preference = 'netconsole.console.skipMultilinePasteConfirmation'
  if (isMultilinePaste(text) && localStorage.getItem(preference) !== '1') {
    const summary = describeTerminalPaste(text)
    let skipNext = false
    try {
      await ElMessageBox.confirm(
        h('div', [
          h('p', [props.session.device_name, props.session.session_name || sessionId, props.session.address].filter(Boolean).join(' · ')),
          h('p', [summary.lineCount + ' 行', summary.hasEmptyLine ? '含空行' : '无空行', summary.hasConfigCommand ? '含常见配置或危险命令特征' : '未匹配常见危险命令特征'].join(' · ')),
          h('pre', { style: { maxHeight: '32vh', overflow: 'auto', whiteSpace: 'pre-wrap' } }, summary.preview),
          h('label', [h('input', { type: 'checkbox', onChange: (event: Event) => { skipNext = (event.target as HTMLInputElement).checked } }), ' 不再提示多行粘贴']),
        ]),
        '确认多行粘贴',
        { type: 'warning', confirmButtonText: '粘贴', cancelButtonText: '取消' },
      )
      if (skipNext) localStorage.setItem(preference, '1')
    } catch {
      return
    }
  }
  if (disposed || terminalEnded() || !connected.value || !mayFocus() || socket !== connection || terminal !== target || props.session.session_id !== sessionId) return
  target.paste(quoted ? quotePastedLines(text) : text)
  target.focus()
}

function handleNativePaste(event: ClipboardEvent): void {
  event.preventDefault()
  event.stopImmediatePropagation()
  const text = event.clipboardData?.getData('text/plain')
  if (text) void pasteText(text)
}

function showFind(): void {
  findVisible.value = true
  contextMenu.value = null
  void nextTick(() => document.querySelector<HTMLInputElement>('.terminal-find input')?.focus())
}

function findNext(backwards = false): void {
  if (!findQuery.value) return
  const options = { caseSensitive: findCaseSensitive.value, incremental: true }
  const found = backwards
    ? searchAddon?.findPrevious(findQuery.value, options)
    : searchAddon?.findNext(findQuery.value, options)
  if (!found) ElMessage.info('未找到匹配内容')
}

function printSelection(text: string): void {
  const content = document.createElement('pre')
  content.className = 'nc-terminal-print-selection'
  content.textContent = text
  const style = document.createElement('style')
  style.textContent = `
    @media screen { .nc-terminal-print-selection { display: none !important; } }
    @media print {
      body > *:not(.nc-terminal-print-selection) { display: none !important; }
      body > .nc-terminal-print-selection {
        display: block !important;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        color: #000;
        background: #fff;
        font: 10pt/1.4 Consolas, monospace;
      }
    }
  `
  document.head.append(style)
  document.body.append(content)
  const cleanup = () => {
    content.remove()
    style.remove()
    window.removeEventListener('afterprint', cleanup)
  }
  window.addEventListener('afterprint', cleanup, { once: true })
  window.print()
  window.setTimeout(cleanup, 60_000)
}

async function addKeyword(text: string): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('输入要高亮的关键词', '添加终端关键词', {
      inputValue: text.trim().split(/\s+/).slice(0, 1)[0],
      inputPattern: /\S/,
      inputErrorMessage: '关键词不能为空',
    })
    const current = await getTerminalHighlightRules()
    const rule: TerminalHighlightRule = {
      id: crypto.randomUUID(),
      pattern: value,
      match_type: 'TEXT',
      color: '#f5c451',
      enabled: true,
      source_row: current.rules.length + 1,
    }
    const next = [...current.rules, rule]
    await replaceTerminalHighlightRules(next)
    localHighlightRules.value = [...localHighlightRules.value, rule]
    ElMessage.success('关键词已添加并保存')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '添加关键词失败')
  }
}

async function runContextAction(id: string): Promise<void> {
  const item = contextMenu.value
  if (!item) return
  contextMenu.value = null
  switch (id) {
    case 'copy':
      await copyText(item.selectedText)
      break
    case 'paste': {
      const text = await readClipboard()
      if (text !== null) await pasteText(text)
      break
    }
    case 'copy-paste':
      if (await copyText(item.selectedText)) await pasteText(item.selectedText)
      break
    case 'quoted-paste': {
      const text = await readClipboard()
      if (text !== null) await pasteText(text, true)
      break
    }
    case 'open-url': {
      try {
        const url = new URL(item.url)
        if (!['http:', 'https:'].includes(url.protocol)) throw new Error('只允许打开 HTTP 或 HTTPS 链接')
        const result = await getPlatformAdapter().openExternalUrl(url.href)
        if (!result.success) ElMessage.error(result.error || '无法打开链接')
      } catch (error) {
        ElMessage.error(error instanceof Error ? error.message : '链接无效')
      }
      break
    }
    case 'add-keyword':
      await addKeyword(item.selectedText)
      break
    case 'find':
      showFind()
      break
    case 'select-all':
      terminal?.selectAll()
      terminal?.focus()
      break
    case 'print':
      printSelection(item.selectedText)
      break
    case 'clear-scrollback':
      terminal?.write('\x1b[3J')
      break
    case 'clear-screen':
      terminal?.write('\x1b[2J\x1b[H')
      terminal?.focus()
      break
    case 'clear-all':
      terminal?.write('\x1b[3J')
      terminal?.write('\x1b[2J\x1b[H')
      terminal?.focus()
      break
  }
}

async function executeMenuFunction(id: 'find' | 'select-all' | 'clear-scrollback' | 'clear-screen' | 'clear-all'): Promise<void> {
  const selectedText = terminal?.getSelection() || ''
  const line = terminal?.buffer.active.getLine(terminal.buffer.active.baseY + terminal.buffer.active.cursorY)?.translateToString(true) || ''
  contextMenu.value = { left: 0, top: 0, selectedText, url: extractTerminalUrl(selectedText || line) }
  await runContextAction(id)
}

function handleTerminalKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    contextMenu.value = null
    findVisible.value = false
    return
  }
  if (event.shiftKey && event.key === 'F10') {
    event.preventDefault()
    const rect = host.value?.getBoundingClientRect()
    if (rect) openContextMenu(new MouseEvent('contextmenu', { clientX: rect.left + 12, clientY: rect.top + 12 }))
    return
  }
  if (!event.ctrlKey && event.shiftKey && event.key === 'Insert') {
    event.preventDefault()
    void readClipboard().then(async (text) => {
      if (text !== null) await pasteText(text)
    })
    return
  }
  if (!event.ctrlKey || event.altKey) return
  const key = event.key.toLowerCase()
  if (key === 'f' && !event.shiftKey) {
    event.preventDefault()
    showFind()
  } else if (key === 'c' && event.shiftKey && terminal?.hasSelection()) {
    event.preventDefault()
    void copyText(terminal.getSelection())
  } else if (key === 'v' && event.shiftKey) {
    event.preventDefault()
    void readClipboard().then(async (text) => {
      if (text !== null) await pasteText(text)
    })
  } else if (key === 'a' && event.shiftKey) {
    event.preventDefault()
    terminal?.selectAll()
  } else if (event.key === 'Insert' && terminal?.hasSelection()) {
    event.preventDefault()
    void copyText(terminal.getSelection())
  }
}

function createTerminal(): void {
  if (!host.value || terminal) return
  terminal = new Terminal({
    cursorBlink: true,
    cursorStyle: 'block',
    convertEol: false,
    scrollback: 10_000,
    fontFamily: `${props.settings?.font_family || 'Consolas'}, Microsoft YaHei UI, monospace`,
    fontSize: props.settings?.font_size || 14,
    lineHeight: 1.24,
    theme: {
      background: props.settings?.background || '#0d1117',
      foreground: props.settings?.foreground || '#d7e0ea',
      cursor: props.settings?.cursor_color || '#55d6be',
      selectionBackground: '#2a4e68aa',
      black: '#0d1117',
      brightBlack: '#657384',
      green: '#55d6be',
      cyan: '#5bc0eb',
      yellow: '#f5c451',
      red: '#ff6b6b',
    },
  })
  fitAddon = new FitAddon()
  searchAddon = new SearchAddon()
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(searchAddon)
  terminal.open(host.value)
  host.value.addEventListener('paste', handleNativePaste, true)
  host.value.addEventListener('contextmenu', openContextMenu)
  host.value.addEventListener('keydown', handleTerminalKeydown, true)
  terminal.writeln('\x1b[1;36mNetConsole Interactive Console\x1b[0m')
  terminal.onData((data) => {
    if (props.syncInput && !receivingSynchronizedPaste) emit('input', data)
    else sendInput(data)
  })
  terminal.onResize(({ cols, rows }) => {
    const dimensions = `${cols}:${rows}`
    if (socket?.readyState === WebSocket.OPEN && dimensions !== lastDimensions && props.workspaceVisible !== false) {
      socket.send(JSON.stringify({ type: 'resize', cols, rows }))
      lastDimensions = dimensions
    }
  })
  resizeObserver = new ResizeObserver(() => fit())
  resizeObserver.observe(host.value)
  fit()
}

function sendInput(data: string): void {
  if (terminalEnded() || socket?.readyState !== WebSocket.OPEN) return
  socket.send(JSON.stringify({ type: 'input', data }))
}

function receiveSynchronizedPaste(text: string): void {
  if (!terminal || terminalEnded() || socket?.readyState !== WebSocket.OPEN) return
  receivingSynchronizedPaste = true
  try {
    terminal.paste(text)
  } finally {
    receivingSynchronizedPaste = false
  }
}

async function openSocket(): Promise<void> {
  if (disposed || opening || terminalEnded() || socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return
  opening = true
  try {
    const ticket = initialTicket || (await issueTerminalTicket(props.session.session_id)).ticket
    initialTicket = ''
    if (disposed || terminalEnded()) return
    const connection = new WebSocket(terminalWebSocketUrl(props.session.session_id, ticket))
    socket = connection
    connectionMessage.value = '正在建立终端通道…'
    connection.addEventListener('open', () => {
      if (disposed || socket !== connection) return
      connected.value = true
      reconnectAttempts = 0
      lastDimensions = ''
      connectionMessage.value = '终端通道已连接'
      fit()
      if (mayFocus()) terminal?.focus()
    })
    connection.addEventListener('message', (event) => {
      if (disposed || socket !== connection) return
      const message = JSON.parse(String(event.data || '{}')) as Record<string, unknown>
      if (message.type === 'output' || message.type === 'local_echo' || message.type === 'backlog') {
        terminal?.write(highlightOutput(String(message.data || '')))
      }
      if (message.type === 'snapshot' && message.session) emit('session', message.session as TerminalSession)
      if (message.type === 'state' && message.session) emit('session', message.session as TerminalSession)
      if (message.type === 'input_notice') emit('notice', String(message.message || ''))
      if (message.type === 'risk_warning') emit('notice', String(message.message || '检测到高危命令'))
      if (message.type === 'error') {
        connectionMessage.value = String(message.message || '终端通道发生错误')
      }
    })
    connection.addEventListener('close', () => {
      if (disposed || socket !== connection) return
      connected.value = false
      socket = null
      connectionMessage.value = '终端通道已断开，会话历史仍保留'
      if (!terminalEnded() && reconnectAttempts < 3) {
        reconnectAttempts += 1
        reconnectTimer = setTimeout(() => void openSocket(), reconnectAttempts * 800)
      }
    })
    connection.addEventListener('error', () => {
      if (!disposed && socket === connection) connectionMessage.value = '终端通道连接失败'
    })
  } catch (error) {
    if (!disposed) connectionMessage.value = error instanceof Error ? error.message : '终端通道连接失败'
  } finally {
    opening = false
  }
}

function fit(): void {
  if (props.workspaceVisible === false || props.active === false || !host.value?.getBoundingClientRect().width) return
  nextTick(() => {
    try {
      fitAddon?.fit()
    } catch {
      // 页面隐藏或容器尺寸尚未稳定时等待下一次 ResizeObserver。
    }
  })
}

function clear(): void {
  terminal?.clear()
}

function focus(): void {
  terminal?.focus()
}

function closeFind(): void {
  findVisible.value = false
  terminal?.focus()
}

function search(query: string, backwards = false): boolean {
  if (!query) return false
  return backwards
    ? Boolean(searchAddon?.findPrevious(query, { caseSensitive: false, incremental: true }))
    : Boolean(searchAddon?.findNext(query, { caseSensitive: false, incremental: true }))
}

function highlightOutput(data: string): string {
  const rules = [...(props.highlightRules || []), ...localHighlightRules.value].filter((rule) => rule.enabled && rule.pattern)
  if (!rules.length || !data) return data
  return data.split(/(\x1b\[[0-?]*[ -/]*[@-~])/g).map((segment) => {
    if (!segment || segment.startsWith('\x1b[')) return segment
    const ranges: Array<{ start: number; end: number; color: string; order: number }> = []
    rules.forEach((rule, order) => {
      if (rule.match_type === 'REGEX') {
        try {
          const expression = new RegExp(rule.pattern, 'gi')
          let match: RegExpExecArray | null
          while ((match = expression.exec(segment)) !== null) {
            if (!match[0]) {
              expression.lastIndex += 1
              continue
            }
            ranges.push({ start: match.index, end: match.index + match[0].length, color: rule.color, order })
          }
        } catch {
          // 服务端保存时已校验；运行期遇到损坏规则时保持输出原样。
        }
      } else {
        const needle = rule.pattern.toLocaleLowerCase()
        const haystack = segment.toLocaleLowerCase()
        let start = 0
        while (needle && (start = haystack.indexOf(needle, start)) >= 0) {
          ranges.push({ start, end: start + needle.length, color: rule.color, order })
          start += needle.length
        }
      }
    })
    ranges.sort((left, right) => left.start - right.start || left.order - right.order || right.end - left.end)
    let cursor = 0
    let result = ''
    for (const range of ranges) {
      if (range.start < cursor) continue
      const rgb = range.color.slice(1).match(/.{2}/g)?.map((value) => Number.parseInt(value, 16)) || [255, 255, 255]
      result += segment.slice(cursor, range.start)
      result += `\x1b[38;2;${rgb[0]};${rgb[1]};${rgb[2]}m${segment.slice(range.start, range.end)}\x1b[39m`
      cursor = range.end
    }
    return result + segment.slice(cursor)
  }).join('')
}

watch(() => props.active, (active) => { if (active) fit() })
watch(mayFocus, (focused) => { if (focused) terminal?.focus() })

watch(() => props.settings, (value) => {
  if (!terminal || !value) return
  terminal.options.fontFamily = `${value.font_family}, Microsoft YaHei UI, monospace`
  terminal.options.fontSize = value.font_size
  terminal.options.theme = {
    ...terminal.options.theme,
    background: value.background,
    foreground: value.foreground,
    cursor: value.cursor_color,
  }
  fit()
}, { deep: true })

onMounted(() => {
  createTerminal()
  const dismissContext = () => { contextMenu.value = null }
  document.addEventListener('pointerdown', dismissContext)
  removeContextDismiss = () => document.removeEventListener('pointerdown', dismissContext)
  void openSocket()
})
watch(() => props.workspaceVisible, visible => { if (visible) fit() })
watch(connected, (value) => emit('connection', value), { flush: 'sync' })

onBeforeUnmount(() => {
  disposed = true
  if (reconnectTimer) clearTimeout(reconnectTimer)
  removeContextDismiss?.()
  host.value?.removeEventListener('contextmenu', openContextMenu)
  host.value?.removeEventListener('paste', handleNativePaste, true)
  host.value?.removeEventListener('keydown', handleTerminalKeydown, true)
  resizeObserver?.disconnect()
  socket?.close()
  terminal?.dispose()
  searchAddon = null
})

function inspect() {
  if (!import.meta.env.DEV || !terminal) return null
  const buffer = terminal.buffer.active
  return { lines: Array.from({ length: buffer.length }, (_, index) => buffer.getLine(index)?.translateToString(true) || ''), cursorX: buffer.cursorX, cursorY: buffer.cursorY, viewportY: buffer.viewportY, cols: terminal.cols, rows: terminal.rows, connected: connected.value }
}
defineExpose({ clear, fit, focus, search, inspect, executeMenuFunction, sendInput, receiveSynchronizedPaste })
</script>

<template>
  <div class="terminal-pane" :data-session-id="session.session_id">
    <div ref="host" class="terminal-host" />
    <div v-if="findVisible" class="terminal-find" @pointerdown.stop>
      <input v-model="findQuery" aria-label="查找终端内容" placeholder="查找" @keydown.enter.prevent="findNext(false)" />
      <label><input v-model="findCaseSensitive" type="checkbox" />Aa</label>
      <button type="button" aria-label="查找上一个" @click="findNext(true)">↑</button>
      <button type="button" aria-label="查找下一个" @click="findNext(false)">↓</button>
      <button type="button" aria-label="关闭查找" @click="closeFind">×</button>
    </div>
    <div
      v-if="contextMenu"
      class="terminal-context-menu"
      role="menu"
      aria-label="终端操作"
      :style="{ left: `${contextMenu.left}px`, top: `${contextMenu.top}px` }"
      @pointerdown.stop
      @contextmenu.prevent.stop
    >
      <button
        v-for="action in contextActions"
        :key="action.id"
        type="button"
        role="menuitem"
        :disabled="contextActionDisabled(action)"
        @click="runContextAction(action.id)"
      >
        <span>{{ action.label }}</span><kbd v-if="action.shortcut">{{ action.shortcut }}</kbd>
      </button>
    </div>
    <div v-if="!connected" class="terminal-connection-overlay">
      <span class="terminal-connection-dot" />
      {{ session.error_message || connectionMessage }}
    </div>
  </div>
</template>

<style scoped>
.terminal-pane {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: var(--nc-bg-code);
}

.terminal-host {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: 10px 8px 4px;
}

.terminal-context-menu {
  position: fixed;
  z-index: 3000;
  display: grid;
  min-width: 238px;
  padding: 5px;
  border: 1px solid var(--nc-border);
  border-radius: 7px;
  background: var(--nc-bg-panel);
  box-shadow: var(--nc-shadow-floating);
}

.terminal-context-menu button {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding: 6px 9px;
  border: 0;
  border-radius: 4px;
  color: var(--nc-text-primary);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.terminal-context-menu button:hover:not(:disabled) {
  background: var(--nc-bg-hover);
}

.terminal-context-menu button:disabled {
  color: var(--nc-text-code-muted);
  cursor: not-allowed;
}

.terminal-context-menu kbd {
  color: var(--nc-text-code-muted);
  font-size: 11px;
}

.terminal-find {
  position: absolute;
  z-index: 5;
  top: 12px;
  right: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px;
  border: 1px solid var(--nc-border);
  border-radius: 6px;
  background: var(--nc-bg-panel);
}

.terminal-find input:not([type='checkbox']) {
  width: 190px;
  padding: 5px 7px;
  border: 1px solid var(--nc-border);
  border-radius: 4px;
  color: var(--nc-text-primary);
  background: var(--nc-bg-code);
}

.terminal-find label {
  display: flex;
  align-items: center;
  gap: 3px;
  color: var(--nc-text-code-muted);
  font-size: 11px;
}

.terminal-find button {
  min-width: 26px;
  border: 0;
  color: var(--nc-text-primary);
  background: transparent;
  cursor: pointer;
}

.terminal-connection-overlay {
  position: absolute;
  top: 10px;
  right: 14px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 9px;
  border: 1px solid var(--nc-border-code);
  border-radius: 999px;
  color: var(--nc-text-code-muted);
  background: var(--nc-bg-code-header);
  font-size: 12px;
  pointer-events: none;
}

.terminal-connection-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--nc-warning);
}
</style>
