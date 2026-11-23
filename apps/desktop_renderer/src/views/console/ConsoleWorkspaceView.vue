<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Close,
  Connection,
  Delete,
  Download,
  FolderOpened,
  FullScreen,
  Grid,
  Monitor,
  Plus,
  Refresh,
  Search,
  Setting,
  VideoPlay,
} from '@element-plus/icons-vue'

import TerminalPane from './TerminalPane.vue'
import TerminalQuickConnectDialog from './TerminalQuickConnectDialog.vue'
import TerminalSettingsDialog from './TerminalSettingsDialog.vue'
import TerminalSftpPanel from './TerminalSftpPanel.vue'
import ConsoleCommandBar from './ConsoleCommandBar.vue'
import { useConsoleWorkspace } from './useConsoleWorkspace'
const props = withDefaults(defineProps<{ workspaceVisible?: boolean }>(), { workspaceVisible: true })

const sftpWidth = ref(430)
const sidebarWidth = ref(270)
const sidebarCollapsed = ref(false)
const sftpActivity = ref(0)
const layoutKey = 'netconsole.console.layout'
function saveLayout() {
  const value = { collapsed: sidebarCollapsed.value, sidebarWidth: sidebarWidth.value, sftpWidth: sftpWidth.value }
  if (window.netconsoleDesktop?.setUiPreference) void window.netconsoleDesktop.setUiPreference('console.layout', value).catch(() => undefined)
  else localStorage.setItem(layoutKey, JSON.stringify(value))
}
onMounted(async () => {
  try {
    const value = window.netconsoleDesktop?.getUiPreference ? await window.netconsoleDesktop.getUiPreference('console.layout') : JSON.parse(localStorage.getItem(layoutKey) || 'null')
    if (value && typeof value === 'object') {
      const saved = value as { collapsed: boolean; sidebarWidth: number; sftpWidth: number }
      sidebarCollapsed.value = Boolean(saved.collapsed)
      sidebarWidth.value = Math.max(180, Math.min(500, Number(saved.sidebarWidth) || 270))
      sftpWidth.value = Math.max(280, Math.min(900, Number(saved.sftpWidth) || 430))
    }
  } catch { /* Invalid UI preference does not affect live transports. */ }
})
let stopSftpResize: (() => void) | undefined
let stopSidebarResize: (() => void) | undefined
function resizeSftp(event: PointerEvent) {
  const start = event.clientX
  const width = sftpWidth.value
  stopSftpResize?.()
  const move = (e: PointerEvent) => { sftpWidth.value = Math.max(280, Math.min(window.innerWidth * 0.5, width + e.clientX - start)) }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); stopSftpResize = undefined; saveLayout() }
  stopSftpResize = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop, { once: true })
}
function resizeSidebar(event: PointerEvent) {
  stopSidebarResize?.()
  const start = event.clientX, width = sidebarWidth.value
  const move = (e: PointerEvent) => { sidebarWidth.value = Math.max(180, Math.min(500, width + e.clientX - start)) }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); stopSidebarResize = undefined; saveLayout() }
  stopSidebarResize = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop, { once: true })
}
onBeforeUnmount(() => { stopSftpResize?.(); stopSidebarResize?.() })

const {
  sessionStateFilter,
  cloneSession,
  renameSession,
  saveConnectionTemplate,
  deleteRecording,
  addTerminalTab,
  devices,
  sessions,
  profiles,
  profileFolders,
  history,
  tabs,
  selectedDeviceUuid,
  selectedDeviceUuids,
  selectedSessionIds,
  activeTabId,
  secondaryTabId,
  navigationMode,
  deviceSearch,
  sessionSearch,
  terminalSearch,
  loadingDevices,
  loadSessions,
  openingDeviceUuid,
  splitOrientation,
  workspace,
  historyVisible,
  historyLoading,
  replayVisible,
  replayLoading,
  replaySession,
  contextDevice,
  contextMenu,
  contextSession,
  sessionContextMenu,
  settingsVisible,
  sftpVisible,
  quickConnectVisible,
  quickConnectLoading,
  editingProfile,
  terminalSettings,
  highlightRules,
  expandedGroups,
  groupedDevices,
  groupedProfiles,
  filteredSessions,
  activeTab,
  visibleTabIds,
  workspaceStyle,
  paneClass,
  setTerminalRef,
  openDevice,
  quickConnect,
  openProfile,
  editProfile,
  createProfileFolder,
  renameProfileFolder,
  removeProfileFolder,
  removeProfile,
  openSelectedDevices,
  openSession,
  toggleDeviceSelection,
  selectTab,
  closeTab,
  closeOtherTabs,
  closeAllTabs,
  startTabDrag,
  dropTab,
  terminateActiveSession,
  reconnectActiveSession,
  reconnectSession,
  terminateSession,
  updateSession,
  setSplit,
  closeSplit,
  startDividerDrag,
  clearActiveTerminal,
  searchActiveTerminal,
  toggleGroup,
  expandAllGroups,
  collapseAllGroups,
  startManualLog,
  pauseOrResumeManualLog,
  stopManualLog,
  loadDevices,
  applyTerminalPreferences,
  showHistory,
  showReplay,
  exportReplay,
  sessionStatusClass,
  showDeviceMenu,
  showSessionMenu,
  openDeviceDetail,
  hideContextMenu,
  formatTime,
  recordingText,
  replayText,
} = useConsoleWorkspace()
const sftpDevice = computed(() => {
  const id = activeTab.value?.session.device_uuid || selectedDeviceUuid.value
  return devices.value.find(item => item.device_uuid === id)
})
const sftpAvailable = computed(() => activeTab.value ? activeTab.value.session.protocol === 'SSH' && Boolean(sftpDevice.value?.capabilities.ssh) : Boolean(sftpDevice.value?.capabilities.ssh))
const showSftp = computed(() => sftpVisible.value && sftpAvailable.value)
const sftpWorkspaces = ref<Array<{ id: string; deviceUuid: string; name: string }>>([])
const sftpWorkspaceId = computed(() => activeTab.value?.id || sftpDevice.value?.device_uuid || '')
watch([showSftp, sftpWorkspaceId], () => {
  if (showSftp.value && sftpDevice.value && !sftpWorkspaces.value.some(item => item.id === sftpWorkspaceId.value)) sftpWorkspaces.value.push({ id: sftpWorkspaceId.value, deviceUuid: sftpDevice.value.device_uuid, name: sftpDevice.value.name })
}, { immediate: true })
</script>

<template>
  <section class="console-workspace">
    <header class="console-toolbar">
      <el-button title="展开或收起左侧列表" aria-label="展开或收起左侧列表" @click="sidebarCollapsed = !sidebarCollapsed; saveLayout()">☰</el-button>
      <div class="console-toolbar__title">
        <Monitor :size="18" />
        <strong>设备控制台</strong>
        <span>INTERACTIVE</span>
      </div>
      <el-button size="small" @click="quickConnectVisible = true">
        <el-icon><Connection /></el-icon>快速连接
      </el-button>
      <el-button size="small" :disabled="!selectedDeviceUuid" :loading="Boolean(openingDeviceUuid)" @click="openDevice(devices.find((item) => item.device_uuid === selectedDeviceUuid)!)">
        <el-icon><Connection /></el-icon>新建会话
      </el-button>
      <el-button size="small" :disabled="!selectedDeviceUuids.length" @click="openSelectedDevices">批量打开</el-button>
      <el-button size="small" :disabled="!activeTab" @click="terminateActiveSession">
        <el-icon><Delete /></el-icon>结束会话
      </el-button>
      <el-button size="small" :disabled="!activeTab || !['DISCONNECTED', 'FAILED', 'CLOSED'].includes(activeTab.session.state)" @click="reconnectActiveSession">
        <el-icon><Refresh /></el-icon>重连
      </el-button>
      <el-dropdown trigger="click" :disabled="tabs.length < 2">
        <el-button size="small" :disabled="tabs.length < 2"><el-icon><Grid /></el-icon>分屏</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="setSplit('horizontal')">左右分屏</el-dropdown-item>
            <el-dropdown-item @click="setSplit('vertical')">上下分屏</el-dropdown-item>
            <el-dropdown-item :disabled="splitOrientation === 'none'" @click="closeSplit">关闭分屏</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button size="small" :disabled="!activeTab" @click="clearActiveTerminal">清屏</el-button>
      <el-input v-model="terminalSearch" class="terminal-search" size="small" placeholder="搜索终端" clearable @keyup.enter="searchActiveTerminal(false)">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button size="small" title="上一个匹配" :disabled="!activeTab || !terminalSearch" @click="searchActiveTerminal(true)">上一个</el-button>
      <el-button size="small" title="下一个匹配" :disabled="!activeTab || !terminalSearch" @click="searchActiveTerminal(false)">下一个</el-button>
      <el-dropdown trigger="click" :disabled="!activeTab">
        <el-button size="small" :disabled="!activeTab"><el-icon><VideoPlay /></el-icon>会话日志</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item :disabled="activeTab?.session.manual_log_status !== 'STOPPED' && !['COMPLETE', 'INCOMPLETE'].includes(activeTab?.session.manual_log_status || '')" @click="startManualLog">开始记录</el-dropdown-item>
            <el-dropdown-item :disabled="!['RECORDING', 'PAUSED'].includes(activeTab?.session.manual_log_status || '')" @click="pauseOrResumeManualLog">
              {{ activeTab?.session.manual_log_status === 'PAUSED' ? '恢复记录' : '暂停记录' }}
            </el-dropdown-item>
            <el-dropdown-item :disabled="!['RECORDING', 'PAUSED'].includes(activeTab?.session.manual_log_status || '')" @click="stopManualLog">停止并保存</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button v-if="sftpAvailable" size="small" :type="showSftp ? 'primary' : 'default'" @click="sftpVisible = !sftpVisible"><el-icon><FolderOpened /></el-icon>SFTP<span v-if="sftpActivity"> · {{ sftpActivity }}</span></el-button>
      <el-button size="small" @click="showHistory">
        <el-icon><FullScreen /></el-icon>会话记录
      </el-button>
      <el-button size="small" title="终端设置" @click="settingsVisible = true"><el-icon><Setting /></el-icon></el-button>
      <span class="console-toolbar__spacer" />
      <span class="console-toolbar__summary">{{ tabs.length }} 个标签 · {{ sessions.filter((item) => ['CONNECTED', 'RUNNING'].includes(item.state)).length }} 个活动会话</span>
    </header>

    <div class="console-body" :class="{ 'with-sftp': showSftp, 'sidebar-collapsed': sidebarCollapsed }" :style="{ '--sftp-width': `${sftpWidth}px`, '--sidebar-width': `${sidebarWidth}px` }">
      <nav v-show="sidebarCollapsed" class="console-icon-rail"><button title="终端会话" @click="sidebarCollapsed = false; navigationMode = 'sessions'; saveLayout()">▤</button><button v-if="sftpAvailable" title="SFTP" @click="sftpVisible = !sftpVisible">⇅</button><button title="录制历史" @click="showHistory">◷</button></nav>
      <aside v-show="!sidebarCollapsed" class="console-sidebar" @pointerdown="($event.target as HTMLElement).classList.contains('sidebar-resize') && resizeSidebar($event)">
        <div class="sidebar-resize" role="separator" aria-label="调整会话列表宽度" />
        <div class="console-sidebar__tabs">
          <button :class="{ active: navigationMode === 'devices' }" @click="navigationMode = 'devices'">设备</button>
          <button title="常用连接配置，不包含活动状态或历史日志" :class="{ active: navigationMode === 'profiles' }" @click="navigationMode = 'profiles'">已保存连接</button>
          <button title="独立终端及已关闭会话" :class="{ active: navigationMode === 'sessions' }" @click="navigationMode = 'sessions'; loadSessions()">终端会话</button>
        </div>
        <label class="console-search">
          <Search :size="15" />
          <input v-if="navigationMode === 'devices'" v-model="deviceSearch" placeholder="搜索设备名称或 IP" />
          <input v-else v-model="sessionSearch" :placeholder="navigationMode === 'profiles' ? '搜索保存会话' : '搜索会话'" />
        </label>

        <div v-if="navigationMode === 'devices'" v-loading="loadingDevices" class="console-tree">
          <div class="device-tree-actions">
            <el-button link title="刷新设备" @click="loadDevices"><el-icon><Refresh /></el-icon></el-button>
            <el-button link @click="expandAllGroups">展开全部</el-button>
            <el-button link @click="collapseAllGroups">收起全部</el-button>
            <el-button link title="前往设备管理新增设备" @click="$router.push({ name: 'device-management', query: { action: 'create' } })"><el-icon><Plus /></el-icon></el-button>
          </div>
          <section v-for="group in groupedDevices" :key="group.name" class="device-group">
            <button class="device-group__title" @click="toggleGroup(group.name)">
              <span>{{ expandedGroups.includes(group.name) ? '▾' : '▸' }} {{ group.name }}</span><small>{{ group.items.length }}</small>
            </button>
            <button
              v-for="device in expandedGroups.includes(group.name) ? group.items : []"
              :key="device.device_uuid"
              class="device-row"
              :class="{ active: selectedDeviceUuid === device.device_uuid }"
              :title="`${device.primary_address} · ${device.device_vendor || '未知厂商'} · ${device.capabilities.ssh ? 'SSH' : device.capabilities.telnet ? 'Telnet' : '无终端协议'}`"
              @click="selectedDeviceUuid = device.device_uuid"
              @dblclick="openDevice(device)"
              @contextmenu="showDeviceMenu($event, device)"
            >
              <input
                type="checkbox"
                :checked="selectedDeviceUuids.includes(device.device_uuid)"
                aria-label="选择设备"
                @click.stop
                @change="toggleDeviceSelection(device.device_uuid, ($event.target as HTMLInputElement).checked)"
              />
              <span class="device-row__state" :class="device.connection_status === 'REACHABLE' ? 'is-success' : ''" />
              <span class="device-row__body">
                <strong>{{ device.name || device.system_name }}</strong>
              </span>
              <span class="device-row__protocol">{{ device.capabilities.ssh ? 'SSH' : device.capabilities.telnet ? 'TELNET' : '—' }}</span>
            </button>
          </section>
          <div v-if="!groupedDevices.length && !loadingDevices" class="console-empty">暂无匹配设备</div>
        </div>

        <div v-else-if="navigationMode === 'profiles'" class="console-tree">
          <div class="device-tree-actions">
            <el-button link title="快速连接" @click="quickConnectVisible = true"><el-icon><Plus /></el-icon></el-button>
            <el-button link @click="createProfileFolder">新建文件夹</el-button>
          </div>
          <section v-for="group in groupedProfiles" :key="group.id || 'root'" class="device-group">
            <div class="device-group__title">
              <span>{{ group.name }}</span><small>{{ group.items.length }}</small>
              <template v-if="group.id">
                <el-button link title="重命名文件夹" @click.stop="renameProfileFolder(profileFolders.find((item) => item.folder_id === group.id)!)">编辑</el-button>
                <el-button link type="danger" title="删除文件夹" @click.stop="removeProfileFolder(profileFolders.find((item) => item.folder_id === group.id)!)"><el-icon><Delete /></el-icon></el-button>
              </template>
            </div>
            <div
              v-for="profile in group.items"
              :key="profile.profile_id"
              class="profile-row"
              role="button"
              tabindex="0"
              :title="`${profile.host}:${profile.port} · ${profile.username} · ${profile.encoding.toUpperCase()}`"
              @dblclick="openProfile(profile)"
              @keyup.enter="openProfile(profile)"
            >
              <span class="profile-row__favorite">{{ profile.favorite ? '★' : '☆' }}</span>
              <span class="profile-row__body">
                <strong>{{ profile.name }}</strong>
                <small>{{ profile.protocol }} · {{ profile.host }}</small>
              </span>
              <el-button link title="连接" @click.stop="openProfile(profile)"><el-icon><Connection /></el-icon></el-button>
              <el-button link title="编辑" @click.stop="editProfile(profile)"><el-icon><Setting /></el-icon></el-button>
              <el-button link type="danger" title="删除" @click.stop="removeProfile(profile)"><el-icon><Delete /></el-icon></el-button>
            </div>
          </section>
          <div v-if="!profiles.length" class="console-empty">暂无保存会话</div>
        </div>

        <div v-else class="console-tree">
          <select v-model="sessionStateFilter" aria-label="会话状态筛选"><option value="all">全部会话</option><option value="active">活动会话</option><option value="closed">已关闭</option></select>
          <button
            v-for="session in filteredSessions"
            :key="session.session_id"
            class="session-row"
            @click="openSession(session)"
            @contextmenu="showSessionMenu($event, session)"
          >
            <input type="checkbox" :checked="selectedSessionIds.includes(session.session_id)" @click.stop @change="selectedSessionIds = ($event.target as HTMLInputElement).checked ? [...selectedSessionIds, session.session_id] : selectedSessionIds.filter(id => id !== session.session_id)" aria-label="选择终端会话" />
            <span class="session-row__state" :class="sessionStatusClass(session.state)" />
            <span>
              <strong>{{ session.session_name || session.device_name }}</strong>
              <small>{{ session.protocol }} · {{ session.state }} · {{ formatTime(session.created_at_ms) }}</small>
            </span>
          </button>
          <div v-if="!filteredSessions.length" class="console-empty">暂无匹配会话</div>
        </div>
      </aside>

      <aside v-show="showSftp" class="console-sftp">
        <div v-for="item in sftpWorkspaces" :key="item.id" v-show="item.id === sftpWorkspaceId" class="sftp-instance">
        <TerminalSftpPanel
          :device-uuid="item.deviceUuid" :device-name="item.name" :workspace-id="item.id"
          @activity="item.id === sftpWorkspaceId && (sftpActivity = $event)"
        />
        </div>
      </aside>
      <div v-show="showSftp" class="sftp-resizer" role="separator" aria-label="调整 SFTP 面板宽度" aria-orientation="vertical" @pointerdown.prevent="resizeSftp" />
      <main class="console-main">
        <div class="terminal-tabs">
          <el-dropdown
            v-for="tab in tabs"
            :key="tab.id"
            trigger="contextmenu"
            draggable="true"
            @dragstart="startTabDrag(tab.id)"
            @dragover.prevent
            @drop="dropTab(tab.id)"
          >
            <button class="terminal-tab" :class="{ active: visibleTabIds.has(tab.id) }" @click="selectTab(tab.id)">
              <span class="terminal-tab__state" :class="sessionStatusClass(tab.session.state)" />
              <span>{{ tab.session.session_name || tab.session.device_name }}</span>
              <small>{{ tab.session.protocol }}</small>
              <Close class="terminal-tab__close" :size="13" @click.stop="closeTab(tab.id)" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="cloneSession(tab.session)">新建终端会话</el-dropdown-item>
                <el-dropdown-item @click="cloneSession(tab.session)">克隆会话</el-dropdown-item>
                <el-dropdown-item @click="cloneSession(tab.session)">在新标签打开</el-dropdown-item>
                <el-dropdown-item @click="renameSession(tab.session)">重命名</el-dropdown-item>
                <el-dropdown-item @click="saveConnectionTemplate(tab.session)">保存为连接模板</el-dropdown-item>
                <el-dropdown-item @click="terminateSession(tab.session)">结束当前会话</el-dropdown-item>
                <el-dropdown-item @click="closeTab(tab.id)">关闭标签（保留会话）</el-dropdown-item>
                <el-dropdown-item @click="closeOtherTabs(tab.id)">关闭其他标签</el-dropdown-item>
                <el-dropdown-item @click="closeAllTabs">关闭全部标签</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span v-if="!tabs.length">双击左侧设备打开受控终端</span>
        </div>

        <div v-if="tabs.length" ref="workspace" class="terminal-grid" :class="`is-${splitOrientation}`" :style="workspaceStyle">
          <div v-for="tab in tabs" :key="tab.id" :class="paneClass(tab.id)">
            <div class="terminal-pane__header">
              <span>{{ tab.session.device_name }} · {{ tab.session.address }}:{{ tab.session.port }}</span>
              <span :class="sessionStatusClass(tab.session.state)">{{ tab.session.state }}</span>
              <span v-if="tab.session.automation_write_active" class="is-warning" :title="tab.session.automation_write_task_name">自动化写任务运行中</span>
              <span>{{ recordingText(tab.session) }}</span>
            </div>
            <TerminalPane
              :ref="(value) => setTerminalRef(tab.id, value)"
              :session="tab.session"
              :ticket="tab.ticket"
              :active="visibleTabIds.has(tab.id)"
              :workspace-visible="props.workspaceVisible"
              :settings="terminalSettings"
              :highlight-rules="highlightRules"
              @session="updateSession(tab.id, $event)"
              @notice="ElMessage.info($event)"
            />
          </div>
          <button v-if="splitOrientation !== 'none'" class="terminal-divider" aria-label="调整分屏大小" @pointerdown="startDividerDrag" />
        </div>
        <div v-else class="terminal-empty-state">
          <Monitor :size="46" />
          <strong>尚未打开终端会话</strong>
          <span>设备凭据由后端受控引用，终端页面不会接收密码或私钥。</span>
        </div>
        <ConsoleCommandBar :sessions="sessions" :active="activeTab?.session || null" :selected="selectedSessionIds" :selected-devices="devices.filter(item => selectedDeviceUuids.includes(item.device_uuid))" @opened="addTerminalTab" />
      </main>
    </div>

    <div
      v-if="contextMenu.visible && contextDevice"
      class="console-context-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      @click.stop
    >
      <button @click="openDevice(contextDevice); hideContextMenu()">打开终端</button>
      <button @click="openDeviceDetail(contextDevice)">查看设备详情</button>
      <button @click="selectedDeviceUuids = [contextDevice.device_uuid]; openSelectedDevices(); hideContextMenu()">作为批量目标打开</button>
    </div>

    <div
      v-if="sessionContextMenu.visible && contextSession"
      class="console-context-menu"
      :style="{ left: `${sessionContextMenu.x}px`, top: `${sessionContextMenu.y}px` }"
      @click.stop
    >
      <button @click="showReplay(contextSession); hideContextMenu()">查看会话记录</button>
      <button @click="cloneSession(contextSession); hideContextMenu()">新建终端会话</button>
      <button @click="cloneSession(contextSession); hideContextMenu()">克隆会话</button>
      <button @click="cloneSession(contextSession); hideContextMenu()">在新标签打开</button>
      <button @click="closeTab(contextSession.session_id); hideContextMenu()">关闭当前标签</button>
      <button @click="closeOtherTabs(contextSession.session_id); hideContextMenu()">关闭其他标签</button>
      <button @click="renameSession(contextSession); hideContextMenu()">重命名</button>
      <button @click="saveConnectionTemplate(contextSession); hideContextMenu()">保存为连接模板</button>
      <button
        v-if="!['CLOSED', 'FAILED', 'CANCELLED'].includes(contextSession.state)"
        @click="openSession(contextSession); hideContextMenu()"
      >重新打开终端</button>
      <button
        v-if="!['CLOSED', 'FAILED', 'CANCELLED'].includes(contextSession.state)"
        @click="terminateSession(contextSession); hideContextMenu()"
      >结束后端会话</button>
      <button
        v-if="['DISCONNECTED', 'FAILED', 'CLOSED'].includes(contextSession.state)"
        @click="reconnectSession(contextSession); hideContextMenu()"
      >重连为新会话</button>
    </div>

    <el-drawer v-model="historyVisible" title="会话历史" size="720px" @open="showHistory">
      <div class="history-toolbar">
        <label class="console-search"><Search :size="15" /><input v-model="sessionSearch" placeholder="搜索设备、IP、Session ID" @keyup.enter="showHistory" /></label>
        <el-button :loading="historyLoading" @click="showHistory">搜索</el-button>
      </div>
      <el-table v-loading="historyLoading" :data="history" height="calc(100vh - 180px)" empty-text="暂无会话历史">
        <el-table-column prop="device_name" label="设备" min-width="150" />
        <el-table-column prop="protocol" label="协议" width="90" />
        <el-table-column label="开始时间" min-width="170"><template #default="scope">{{ formatTime(scope.row.created_at_ms) }}</template></el-table-column>
        <el-table-column prop="state" label="状态" width="110" />
        <el-table-column label="录制" width="110"><template #default="scope">{{ recordingText(scope.row) }}</template></el-table-column>
        <el-table-column label="操作" width="150"><template #default="scope"><el-button link type="primary" @click="showReplay(scope.row)">查看</el-button><el-button link type="danger" :disabled="['RECORDING', 'FINALIZING', 'COMPRESSING'].includes(scope.row.recording_status)" @click="deleteRecording(scope.row)">删除</el-button></template></el-table-column>
      </el-table>
    </el-drawer>

    <el-dialog v-model="replayVisible" width="min(980px, 92vw)" title="会话记录与导出">
      <div v-if="replaySession" class="replay-summary">
        <strong>{{ replaySession.device_name }}</strong>
        <span>{{ replaySession.protocol }} · {{ replaySession.state }}</span>
        <span>{{ formatTime(replaySession.created_at_ms) }}</span>
        <span :class="replaySession.recording_status === 'INCOMPLETE' ? 'is-danger' : 'is-success'">{{ recordingText(replaySession) }}</span>
        <span class="console-toolbar__spacer" />
        <el-button size="small" :disabled="!replaySession.recording_log_name" @click="exportReplay('log')"><el-icon><Download /></el-icon>LOG</el-button>
        <el-button size="small" :disabled="!replaySession.recording_zip_name" @click="exportReplay('zip')"><el-icon><Download /></el-icon>ZIP</el-button>
        <el-button size="small" @click="exportReplay('jsonl')"><el-icon><Download /></el-icon>JSONL</el-button>
      </div>
      <pre v-loading="replayLoading" class="replay-output">{{ replayText || '暂无可回放输出' }}</pre>
    </el-dialog>

    <TerminalSettingsDialog v-model="settingsVisible" @saved="applyTerminalPreferences" />
    <TerminalQuickConnectDialog
      v-model="quickConnectVisible"
      :folders="profileFolders"
      :loading="quickConnectLoading"
      :profile="editingProfile"
      @update:model-value="!$event && (editingProfile = null)"
      @submit="quickConnect"
    />
  </section>
</template>

<style scoped>
.console-workspace {
  --console-border: var(--nc-border);
  display: grid;
  grid-template-rows: 46px minmax(0, 1fr) auto;
  height: 100%;
  min-height: 560px;
  overflow: hidden;
  border: 1px solid var(--console-border);
  border-radius: 10px;
  background: var(--nc-bg-panel);
}

.console-toolbar {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0 12px;
  border-bottom: 1px solid var(--console-border);
  background: var(--nc-bg-muted);
  scrollbar-width: thin;
  white-space: nowrap;
}

.console-toolbar__title { display: flex; align-items: center; gap: 7px; margin-right: 6px; white-space: nowrap; }
.console-toolbar__title span { color: var(--nc-text-secondary); font-size: 10px; letter-spacing: .04em; }
.console-toolbar__spacer { flex: 1; }
.console-toolbar__summary { color: var(--nc-text-secondary); font-size: 12px; white-space: nowrap; }
.console-toolbar > :deep(.el-button), .console-toolbar__title, .console-toolbar__summary { flex: 0 0 auto; }
.terminal-search { flex: 0 0 150px; min-width: 100px; }

.console-body { display: grid; grid-template-columns: var(--sidebar-width) minmax(0, 1fr); min-height: 0; }
.console-body.with-sftp { grid-template-columns: var(--sidebar-width) minmax(280px, var(--sftp-width)) 5px minmax(240px, 1fr); }
.console-body.sidebar-collapsed { --sidebar-width: 42px !important; }
.console-icon-rail { display: flex; flex-direction: column; border-right: 1px solid var(--console-border); }
.console-icon-rail button { height: 40px; border: 0; background: transparent; color: inherit; cursor: pointer; }
.console-sidebar { position: relative; }
.sidebar-resize { position: absolute; right: 0; top: 0; bottom: 0; width: 5px; z-index: 3; cursor: col-resize; }
.console-sftp { min-width: 0; min-height: 0; overflow: hidden; border-right: 1px solid var(--console-border); }
.sftp-instance { height: 100%; min-height: 0; }
.sftp-resizer { cursor: col-resize; touch-action: none; background: var(--console-border); }
#console-sftp-queue { min-width: 0; }
@media (max-width: 1200px) { .console-body.with-sftp { grid-template-columns: 170px minmax(280px, 34vw) 5px minmax(240px, 1fr); } }
.console-sidebar { display: grid; grid-template-rows: 39px 44px minmax(0, 1fr); min-height: 0; border-right: 1px solid var(--console-border); background: var(--nc-bg-panel); }
.console-sidebar__tabs { display: grid; grid-template-columns: repeat(3, 1fr); padding: 5px 8px 0; border-bottom: 1px solid var(--console-border); }
.console-sidebar__tabs button { border: 0; border-bottom: 2px solid transparent; color: var(--nc-text-secondary); background: transparent; cursor: pointer; }
.console-sidebar__tabs button.active { border-color: var(--nc-primary); color: var(--nc-primary); font-weight: 600; }
.console-search { display: flex; align-items: center; gap: 7px; margin: 8px; padding: 0 9px; border: 1px solid var(--console-border); border-radius: 7px; background: var(--nc-bg-panel); }
.console-search > svg { flex: 0 0 15px; width: 15px; height: 15px; }
.console-search input { min-width: 0; width: 100%; height: 28px; border: 0; outline: 0; color: inherit; background: transparent; }
.console-tree { min-height: 0; overflow: auto; padding: 4px 6px 10px; }
.device-tree-actions { display: flex; align-items: center; gap: 3px; min-height: 30px; padding: 0 4px; border-bottom: 1px solid var(--console-border); }
.device-group__title { display: flex; align-items: center; width: 100%; padding: 8px 8px 4px; border: 0; color: var(--nc-text-secondary); background: transparent; font-size: 11px; cursor: pointer; }
.device-group__title small { margin-left: auto; }
.device-row, .session-row { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 8px; border: 0; border-radius: 6px; text-align: left; color: inherit; background: transparent; cursor: pointer; }
.device-row:hover, .device-row.active, .session-row:hover { background: var(--nc-bg-active); }
.profile-row { display: flex; align-items: center; gap: 7px; width: 100%; min-height: 42px; padding: 5px 6px; border: 0; border-radius: 6px; color: inherit; text-align: left; background: transparent; cursor: pointer; }
.profile-row:hover { background: var(--nc-bg-active); }
.profile-row__favorite { flex: 0 0 14px; color: var(--nc-warning); }
.profile-row__body { display: grid; min-width: 0; flex: 1; gap: 2px; }
.profile-row__body strong, .profile-row__body small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-row__body strong { font-size: 12px; }
.profile-row__body small { color: var(--nc-text-secondary); font-size: 10px; }
.device-row input { accent-color: var(--nc-primary); }
.device-row__body, .session-row > span:last-child { min-width: 0; display: grid; gap: 2px; }
.device-row strong, .session-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.device-row small, .session-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--nc-text-secondary); font-size: 10px; }
.device-row__protocol { margin-left: auto; color: var(--nc-text-secondary); font-size: 9px; }
.device-row__state, .session-row__state, .terminal-tab__state { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; background: var(--nc-info); }
.is-success { color: var(--nc-success) !important; }
.is-danger { color: var(--nc-danger) !important; }
.is-warning { color: var(--nc-warning) !important; }
.is-muted { color: var(--nc-text-secondary) !important; }
.device-row__state.is-success, .session-row__state.is-success, .terminal-tab__state.is-success { background: var(--nc-success); box-shadow: 0 0 0 3px var(--nc-status-success-bg); }
.session-row__state.is-danger, .terminal-tab__state.is-danger { background: var(--nc-danger); }
.session-row__state.is-warning, .terminal-tab__state.is-warning { background: var(--nc-warning); }
.console-empty { padding: 32px 12px; color: var(--nc-text-secondary); text-align: center; font-size: 12px; }

.console-main { display: grid; grid-template-rows: 36px minmax(0, 1fr) auto; min-width: 0; min-height: 0; background: var(--nc-bg-code); }
.terminal-tabs { display: flex; align-items: stretch; min-width: 0; overflow-x: auto; border-bottom: 1px solid var(--nc-border-code); color: var(--nc-text-code-muted); background: var(--nc-bg-code-header); }
.terminal-tabs > span { align-self: center; padding: 0 12px; font-size: 12px; }
.terminal-tab { display: flex; align-items: center; gap: 7px; height: 35px; padding: 0 10px; border: 0; border-right: 1px solid var(--nc-border-code); color: var(--nc-text-code-muted); background: var(--nc-bg-code-header); white-space: nowrap; cursor: pointer; }
.terminal-tab.active { color: var(--nc-text-code); background: var(--nc-bg-code); }
.terminal-tab small { color: var(--nc-text-code-muted); font-size: 9px; }
.terminal-tab__close { opacity: .55; }
.terminal-tab__close:hover { opacity: 1; color: var(--nc-text-code-danger); }

.terminal-grid { display: grid; min-width: 0; min-height: 0; overflow: hidden; background: var(--nc-bg-code); }
.terminal-grid__pane { display: grid; grid-template-rows: 28px minmax(0, 1fr); min-width: 0; min-height: 0; overflow: hidden; }
.terminal-grid__pane.is-primary { grid-column: 1; grid-row: 1; }
.terminal-grid.is-horizontal .terminal-grid__pane.is-secondary { grid-column: 3; grid-row: 1; }
.terminal-grid.is-vertical .terminal-grid__pane.is-secondary { grid-column: 1; grid-row: 3; }
.terminal-grid__pane.is-hidden { display: none; }
.terminal-pane__header { display: flex; align-items: center; gap: 12px; padding: 0 10px; border-bottom: 1px solid var(--nc-border-code); color: var(--nc-text-code-muted); background: var(--nc-bg-code-header); font-size: 11px; }
.terminal-pane__header span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.terminal-pane__header span:nth-child(2) { margin-left: auto; }
.terminal-divider { z-index: 2; padding: 0; border: 0; background: var(--nc-border-strong); }
.terminal-grid.is-horizontal .terminal-divider { grid-column: 2; grid-row: 1; cursor: col-resize; }
.terminal-grid.is-vertical .terminal-divider { grid-column: 1; grid-row: 2; cursor: row-resize; }
.terminal-divider:hover { background: var(--nc-primary); }
.terminal-empty-state { display: grid; place-content: center; justify-items: center; gap: 10px; color: var(--nc-text-code-muted); background: var(--nc-bg-code); }
.terminal-empty-state strong { color: var(--nc-text-code); }
.terminal-empty-state span { font-size: 12px; }

.console-context-menu { position: fixed; z-index: 4000; display: grid; width: 170px; padding: 5px; border: 1px solid var(--console-border); border-radius: 7px; background: var(--nc-bg-elevated); box-shadow: var(--nc-shadow-floating); }
.console-context-menu button { padding: 7px 9px; border: 0; border-radius: 5px; text-align: left; color: inherit; background: transparent; cursor: pointer; }
.console-context-menu button:hover { background: var(--nc-bg-active); }
.history-toolbar, .replay-summary { display: flex; align-items: center; gap: 10px; }
.history-toolbar .console-search { flex: 1; margin: 0 0 12px; }
.replay-summary { margin-bottom: 10px; color: var(--nc-text-secondary); font-size: 12px; }
.replay-summary strong { color: var(--nc-text-primary); }
.replay-output { min-height: 420px; max-height: 65vh; margin: 0; padding: 14px; overflow: auto; border-radius: 8px; color: var(--nc-text-code); background: var(--nc-bg-code); font: 13px/1.45 var(--nc-font-family-mono); white-space: pre-wrap; }

@media (max-width: 1100px) {
  .console-body { grid-template-columns: 230px minmax(0, 1fr); }
  .console-toolbar__summary { display: none; }
}
</style>
