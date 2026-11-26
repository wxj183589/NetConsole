<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'

import {
  issueTerminalTicket,
  terminalWebSocketUrl,
  type TerminalHighlightRule,
  type TerminalSession,
  type TerminalSettings,
} from '../../api/terminal'

const props = defineProps<{
  session: TerminalSession
  ticket?: string
  active?: boolean
  focused?: boolean
  closing?: boolean
  workspaceVisible?: boolean
  settings?: TerminalSettings | null
  highlightRules?: TerminalHighlightRule[]
}>()

const emit = defineEmits<{
  session: [value: TerminalSession]
  notice: [message: string]
}>()

const host = ref<HTMLElement | null>(null)
const connected = ref(false)
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
const terminalEnded = () => props.closing || ['CLOSING', 'CLOSED', 'FAILED', 'CANCELLED', 'DISCONNECTED'].includes(props.session.state)
const mayFocus = () => props.focused !== false && props.active !== false && props.workspaceVisible !== false

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
  terminal.writeln('\x1b[1;36mNetConsole Interactive Console\x1b[0m')
  terminal.onData((data) => {
    if (terminalEnded() || socket?.readyState !== WebSocket.OPEN) return
    socket.send(JSON.stringify({ type: 'input', data }))
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

function search(query: string, backwards = false): boolean {
  if (!query) return false
  return backwards
    ? Boolean(searchAddon?.findPrevious(query, { caseSensitive: false, incremental: true }))
    : Boolean(searchAddon?.findNext(query, { caseSensitive: false, incremental: true }))
}

function highlightOutput(data: string): string {
  const rules = (props.highlightRules || []).filter((rule) => rule.enabled && rule.pattern)
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
  void openSocket()
})
watch(() => props.workspaceVisible, visible => { if (visible) fit() })

onBeforeUnmount(() => {
  disposed = true
  if (reconnectTimer) clearTimeout(reconnectTimer)
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
defineExpose({ clear, fit, focus, search, inspect })
</script>

<template>
  <div class="terminal-pane" :data-session-id="session.session_id">
    <div ref="host" class="terminal-host" />
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
