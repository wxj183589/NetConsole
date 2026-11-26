import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listDevices } from '../../api/deviceManagement'
import {
  closeTerminalSession,
  cloneTerminalSession,
  renameTerminalSession,
  deleteTerminalRecording,
  connectTerminalProfile,
  createTerminalProfileFolder,
  createTerminalSession,
  deleteTerminalProfile,
  deleteTerminalProfileFolder,
  getTerminalHighlightRules,
  getTerminalHistoryEvents,
  getTerminalSettings,
  importTerminalProfiles,
  issueTerminalTicket,
  listTerminalHistory,
  listTerminalProfiles,
  listTerminalSessions,
  quickConnectTerminalSession,
  reconnectTerminalSession,
  renameTerminalProfileFolder,
  pauseTerminalManualLog,
  resumeTerminalManualLog,
  saveTerminalProfile,
  startTerminalManualLog,
  stopTerminalManualLog,
  terminalManualLogDownloadRequest,
  terminalExportDownloadRequest,
  updateTerminalSettings,
  type TerminalHighlightRule,
  type TerminalProfile,
  type TerminalProfileFolder,
  type TerminalProfileValues,
  type TerminalProfileDocument,
  type TerminalRecordingEvent,
  type TerminalSession,
  type TerminalSettings,
} from '../../api/terminal'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import { prepareLocalSaveDestination } from '../../composables/useUserSelectedExport'
import { useExternalTerminalLauncher } from '../../composables/useExternalTerminalLauncher'
import type { DeviceListItem } from '../../types/deviceManagement'
import TerminalPane from './TerminalPane.vue'

type SplitOrientation = 'none' | 'horizontal' | 'vertical'
const endedStates = ['CLOSED', 'FAILED', 'CANCELLED', 'DISCONNECTED']

interface TerminalTab {
  id: string
  session: TerminalSession
  ticket: string
}


export function useConsoleWorkspace() {
  const router = useRouter()
  const externalTerminalLauncher = useExternalTerminalLauncher()
  const devices = ref<DeviceListItem[]>([])
  const sessions = ref<TerminalSession[]>([])
  const profiles = ref<TerminalProfile[]>([])
  const profileFolders = ref<TerminalProfileFolder[]>([])
  const history = ref<TerminalSession[]>([])
  const tabs = ref<TerminalTab[]>([])
  const selectedDeviceUuid = ref('')
  const selectedDeviceUuids = ref<string[]>([])
  const selectedSessionIds = ref<string[]>([])
  const activeTabId = ref('')
  const primaryTabId = ref('')
  const secondaryTabId = ref('')
  const closingTabIds = ref(new Set<string>())
  const reconnectingIds = new Set<string>()
  const navigationMode = ref<'devices' | 'profiles' | 'sessions'>('devices')
  const deviceSearch = ref('')
  const sessionSearch = ref('')
  const sessionStateFilter = ref('all')
  const terminalSearch = ref('')
  const loadingDevices = ref(false)
  const openingDeviceUuid = ref('')
  const splitOrientation = ref<SplitOrientation>('none')
  const splitRatio = ref(0.5)
  const workspace = ref<HTMLElement | null>(null)
  const terminalRefs = ref<Record<string, InstanceType<typeof TerminalPane>>>({})
  const historyVisible = ref(false)
  const historyLoading = ref(false)
  const replayVisible = ref(false)
  const replayLoading = ref(false)
  const replaySession = ref<TerminalSession | null>(null)
  const replayEvents = ref<TerminalRecordingEvent[]>([])
  const contextDevice = ref<DeviceListItem | null>(null)
  const contextMenu = ref({ visible: false, x: 0, y: 0 })
  const contextSession = ref<TerminalSession | null>(null)
  const sessionContextMenu = ref({ visible: false, x: 0, y: 0 })
  const settingsVisible = ref(false)
  const sftpVisible = ref(false)
  const quickConnectVisible = ref(false)
  const quickConnectLoading = ref(false)
  const editingProfile = ref<TerminalProfile | null>(null)
  const contextProfile = ref<TerminalProfile | null>(null)
  const profileContextMenu = ref({ visible: false, x: 0, y: 0 })
  const collapsedProfileGroups = ref<string[]>([])
  const draggedProfile = ref<TerminalProfile | null>(null)
  const draggedTabId = ref('')
  const manualLogTargets = new Map<string, { destinationPath: string; suggestedName: string }>()
  let activityTimer: ReturnType<typeof setInterval> | undefined
  let stopDividerDrag: (() => void) | undefined
  let refreshingSessions = false
  let disposed = false
  const terminalSettings = ref<TerminalSettings | null>(null)
  const highlightRules = ref<TerminalHighlightRule[]>([])
  const expandedGroups = ref<string[]>([])

  const filteredDevices = computed(() => {
    const needle = deviceSearch.value.trim().toLowerCase()
    if (!needle) return devices.value
    return devices.value.filter((device) => [
      device.name,
      device.system_name,
      device.primary_address,
      device.station,
      device.group_name,
      device.device_vendor,
    ].join(' ').toLowerCase().includes(needle))
  })

  const groupedDevices = computed(() => {
    const groups = new Map<string, DeviceListItem[]>()
    for (const device of filteredDevices.value) {
      const key = device.group_name || device.station || '未分组'
      const values = groups.get(key) || []
      values.push(device)
      groups.set(key, values)
    }
    return [...groups.entries()].map(([name, items]) => ({ name, items }))
  })

  const groupedProfiles = computed(() => {
    const needle = sessionSearch.value.trim().toLowerCase()
    const visible = profiles.value.filter((profile) => !needle || [
      profile.name,
      profile.host,
      profile.backup_host,
      profile.username,
      profile.vendor,
      profile.device_type,
      profile.notes,
      ...(profile.tags || []),
    ].join(' ').toLowerCase().includes(needle))
    const groups = profileFolders.value.map((folder) => ({
      id: folder.folder_id,
      name: folder.name,
      items: visible.filter((profile) => profile.folder_id === folder.folder_id),
    }))
    const root = visible.filter((profile) => !profile.folder_id)
    return profiles.value.length ? [{ id: '', name: '未分组', items: root }, ...groups] : groups
  })

  function syncExpandedGroups(): void {
    const available = groupedDevices.value.map((group) => group.name)
    if (!expandedGroups.value.length) expandedGroups.value = available
    else expandedGroups.value = expandedGroups.value.filter((name) => available.includes(name))
  }

  const filteredSessions = computed(() => {
    const needle = sessionSearch.value.trim().toLowerCase()
    return sessions.value.filter(session => sessionStateFilter.value === 'all' || (sessionStateFilter.value === 'active' ? !['CLOSED', 'FAILED', 'CANCELLED', 'DISCONNECTED'].includes(session.state) : ['CLOSED', 'FAILED', 'CANCELLED', 'DISCONNECTED'].includes(session.state))).filter((session) => !needle || [
      session.session_name,
      session.device_name,
      session.address,
      session.session_id,
      session.state,
    ].join(' ').toLowerCase().includes(needle))
  })

  const activeTab = computed(() => tabs.value.find((tab) => tab.id === activeTabId.value) || null)
  const secondaryTab = computed(() => tabs.value.find((tab) => tab.id === secondaryTabId.value) || null)
  const visibleTabIds = computed(() => {
    const result = new Set<string>()
    if (primaryTabId.value) result.add(primaryTabId.value)
    if (splitOrientation.value !== 'none' && secondaryTabId.value) result.add(secondaryTabId.value)
    return result
  })

  const workspaceStyle = computed(() => {
    const primary = `minmax(0, ${splitRatio.value}fr)`
    const secondary = `minmax(0, ${1 - splitRatio.value}fr)`
    if (splitOrientation.value === 'horizontal') {
      return { gridTemplateColumns: `${primary} 5px ${secondary}`, gridTemplateRows: 'minmax(0, 1fr)' }
    }
    if (splitOrientation.value === 'vertical') {
      return { gridTemplateRows: `${primary} 5px ${secondary}`, gridTemplateColumns: 'minmax(0, 1fr)' }
    }
    return { gridTemplateColumns: 'minmax(0, 1fr)', gridTemplateRows: 'minmax(0, 1fr)' }
  })

  function paneClass(tabId: string): string[] {
    const focusClass = tabId === activeTabId.value ? 'is-focused' : ''
    if (tabId === primaryTabId.value) return ['terminal-grid__pane', 'is-primary', focusClass]
    if (splitOrientation.value !== 'none' && tabId === secondaryTabId.value) return ['terminal-grid__pane', 'is-secondary', focusClass]
    return ['terminal-grid__pane', 'is-hidden']
  }

  function setTerminalRef(id: string, value: unknown): void {
    if (value) terminalRefs.value[id] = value as InstanceType<typeof TerminalPane>
    else delete terminalRefs.value[id]
  }

  async function loadDevices(): Promise<void> {
    loadingDevices.value = true
    try {
      const page = await listDevices({ page: 1, page_size: 200, work_scope_status: 'all' })
      devices.value = page.items
      syncExpandedGroups()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '设备列表读取失败')
    } finally {
      loadingDevices.value = false
    }
  }

  async function loadSessions(): Promise<void> {
    try {
      const [active, recent] = await Promise.all([
        listTerminalSessions(),
        listTerminalHistory('', 50),
      ])
      const merged = new Map(recent.items.map((item) => [item.session_id, item]))
      for (const item of active.items) merged.set(item.session_id, item)
      sessions.value = [...merged.values()].sort((left, right) => right.created_at_ms - left.created_at_ms)
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话列表读取失败')
    }
  }

  async function refreshActiveSessions(): Promise<void> {
    if (refreshingSessions) return
    refreshingSessions = true
    try {
      const active = await listTerminalSessions()
      const byId = new Map(active.items.map((item) => [item.session_id, item]))
      for (const tab of [...tabs.value]) {
        const updated = byId.get(tab.id)
        if (updated) updateSession(tab.id, updated)
      }
      sessions.value = sessions.value.map((item) => byId.get(item.session_id) || item)
      if (tabs.value.some((tab) => !byId.has(tab.id) && !endedStates.includes(tab.session.state))) {
        const recent = await listTerminalHistory('', 50)
        for (const session of recent.items) {
          if (!byId.has(session.session_id) && endedStates.includes(session.state)) updateSession(session.session_id, session)
        }
      }
    } catch {
      // The WebSocket owns terminal connectivity; status polling is best effort.
    } finally {
      refreshingSessions = false
    }
  }

  async function loadProfiles(): Promise<void> {
    try {
      const document = await listTerminalProfiles()
      profiles.value = document.profiles
      profileFolders.value = document.folders
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '保存会话读取失败')
    }
  }

  function addTerminalTab(created: { session: TerminalSession; ticket: string }): void {
    if (disposed) {
      void closeTerminalSession(created.session.session_id).catch(() => undefined)
      return
    }
    if (tabs.value.some((tab) => tab.id === created.session.session_id)) {
      selectTab(created.session.session_id)
      return
    }
    if (!sessions.value.some(item => item.session_id === created.session.session_id)) sessions.value.push(created.session)
    const tab: TerminalTab = {
      id: created.session.session_id,
      session: created.session,
      ticket: created.ticket,
    }
    tabs.value.push(tab)
    selectTab(tab.id)
  }

  async function openDevice(device: DeviceListItem, addressRole?: 'primary' | 'backup'): Promise<void> {
    selectedDeviceUuid.value = device.device_uuid
    openingDeviceUuid.value = device.device_uuid
    try {
      const created = await createTerminalSession(device.device_uuid, 'AUTO', 120, 32, addressRole)
      addTerminalTab(created)
      await loadSessions()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '终端会话创建失败')
    } finally {
      openingDeviceUuid.value = ''
    }
  }

  async function openDeviceExternalTerminal(device: DeviceListItem): Promise<void> {
    try {
      const preflight = await externalTerminalLauncher.preflightDeviceTerminalTargets([device.device_uuid])
      if (!preflight) return
      if (!preflight.launchableDevices.length) {
        externalTerminalLauncher.showPreflightSkipped(preflight.skippedDevices)
        return
      }
      const result = await externalTerminalLauncher.launchDeviceTerminalTargets(preflight.launchableDevices, preflight.terminalType)
      if (result) externalTerminalLauncher.showLaunchResult(result)
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '打开外部终端失败')
    }
  }

  async function copyConnectionAddress(address: string): Promise<void> {
    const result = await getPlatformAdapter().writeClipboardText(address)
    if (result.success) ElMessage.success('已复制连接地址')
    else ElMessage.error(result.error || '复制连接地址失败')
  }

  async function quickConnect(
    values: TerminalProfileValues & {
      password: string
      save_profile: boolean
      remember_password: boolean | null
    },
  ): Promise<void> {
    if (editingProfile.value) {
      await saveProfileEdits(values)
      return
    }
    quickConnectLoading.value = true
    try {
      const created = await quickConnectTerminalSession({
        ...values,
        remember_password: Boolean(values.remember_password),
      })
      addTerminalTab(created)
      quickConnectVisible.value = false
      await Promise.all([loadProfiles(), loadSessions()])
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '快速连接失败')
    } finally {
      quickConnectLoading.value = false
    }
  }

  function editProfile(profile: TerminalProfile): void {
    editingProfile.value = profile
    quickConnectVisible.value = true
  }

  async function saveProfileEdits(
    values: TerminalProfileValues & {
      password: string
      remember_password: boolean | null
    },
  ): Promise<void> {
    const profile = editingProfile.value
    if (!profile) return
    quickConnectLoading.value = true
    try {
      await saveTerminalProfile({
        ...values,
        password: values.password,
        remember_password: values.remember_password,
      }, profile.profile_id)
      quickConnectVisible.value = false
      editingProfile.value = null
      await loadProfiles()
      ElMessage.success('保存会话已更新')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '保存会话更新失败')
    } finally {
      quickConnectLoading.value = false
    }
  }

  async function openProfile(profile: TerminalProfile): Promise<void> {
    return connectProfileAtAddress(profile, 'primary')
  }

  async function connectProfileAtAddress(profile: TerminalProfile, addressRole: 'primary' | 'backup'): Promise<void> {
    if (addressRole === 'backup' && !profile.backup_host) return
    try {
      let password = ''
      if (!profile.password_configured) {
        const result = await ElMessageBox.prompt(
          `输入 ${profile.name} 的登录密码${addressRole === 'backup' ? '（备用地址）' : ''}`,
          addressRole === 'backup' ? '连接备用地址' : '连接保存会话',
          { inputType: 'password', confirmButtonText: '连接', cancelButtonText: '取消' },
        )
        password = result.value
      }
      const created = await connectTerminalProfile(profile.profile_id, password, addressRole)
      addTerminalTab(created)
      await loadSessions()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error(error instanceof Error ? error.message : '保存会话连接失败')
      }
    }
  }

  async function importProfiles(file: File | null): Promise<void> {
    if (!file) return
    if (file.size > 2 * 1024 * 1024) {
      ElMessage.error(`${file.name} 会话配置文件超过 2 MiB`)
      return
    }
    try {
      const parsed: unknown = JSON.parse(await file.text())
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('会话配置文件根节点必须是 JSON 对象')
      }
      const result = await importTerminalProfiles(parsed as TerminalProfileDocument)
      profiles.value = result.profiles
      profileFolders.value = result.folders
      ElMessage.success(`已导入配置，当前共 ${result.profiles.length} 个保存会话`)
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话配置导入失败')
    }
  }

  async function exportProfiles(): Promise<void> {
    try {
      const result = await downloadBackendResource({
        apiPath: '/api/terminal/profiles/export',
        suggestedName: 'console-sessions.json',
      })
      if (result.status === 'saved') ElMessage.success('会话配置已保存')
      else if (result.status === 'failed') ElMessage.error(result.error || '会话配置保存失败')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话配置导出失败')
    }
  }

  async function createProfileFolder(): Promise<void> {
    try {
      const { value } = await ElMessageBox.prompt('输入文件夹名称', '新建会话文件夹', {
        confirmButtonText: '新建',
        cancelButtonText: '取消',
      })
      await createTerminalProfileFolder(value)
      await loadProfiles()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error(error instanceof Error ? error.message : '会话文件夹创建失败')
      }
    }
  }

  async function renameProfileFolder(folder: TerminalProfileFolder): Promise<void> {
    try {
      const { value } = await ElMessageBox.prompt('输入新的文件夹名称', '重命名会话文件夹', {
        inputValue: folder.name,
        confirmButtonText: '保存',
        cancelButtonText: '取消',
      })
      await renameTerminalProfileFolder(folder.folder_id, value)
      await loadProfiles()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error(error instanceof Error ? error.message : '会话文件夹重命名失败')
      }
    }
  }

  async function removeProfileFolder(folder: TerminalProfileFolder): Promise<void> {
    try {
      await ElMessageBox.confirm(`删除文件夹“${folder.name}”？其中的会话将移到未分组。`, '删除会话文件夹', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
      await deleteTerminalProfileFolder(folder.folder_id)
      await loadProfiles()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error(error instanceof Error ? error.message : '会话文件夹删除失败')
      }
    }
  }

  async function removeProfile(profile: TerminalProfile): Promise<void> {
    try {
      await ElMessageBox.confirm(`删除保存会话“${profile.name}”？`, '删除保存会话', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
      await deleteTerminalProfile(profile.profile_id)
      await loadProfiles()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error(error instanceof Error ? error.message : '保存会话删除失败')
      }
    }
  }

  function toggleProfileGroup(folderId: string): void {
    collapsedProfileGroups.value = collapsedProfileGroups.value.includes(folderId)
      ? collapsedProfileGroups.value.filter((value) => value !== folderId)
      : [...collapsedProfileGroups.value, folderId]
  }

  async function saveProfileAction(profile: TerminalProfile, action: 'rename' | 'copy' | 'move', folderId = ''): Promise<void> {
    try {
      let name = profile.name
      if (action !== 'move') {
        const copy = action === 'copy'
        const result = await ElMessageBox.prompt('连接名称', copy ? '复制保存连接' : '重命名保存连接', {
          inputValue: copy ? `${profile.name} 副本` : profile.name,
          confirmButtonText: copy ? '复制' : '保存',
          cancelButtonText: '取消',
        })
        name = result.value
      }
      const { host, port, protocol, username, encoding, vendor, device_type, favorite } = profile
      await saveTerminalProfile({
        name, host, port, protocol, username, encoding, vendor, device_type, favorite,
        folder_id: action === 'move' ? folderId : profile.folder_id,
        remember_password: action === 'copy' ? false : null,
      }, action === 'copy' ? undefined : profile.profile_id)
      await loadProfiles()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '保存连接操作失败')
    }
  }

  function showProfileMenu(event: MouseEvent, profile: TerminalProfile): void {
    event.preventDefault()
    hideContextMenu()
    contextProfile.value = profile
    profileContextMenu.value = { visible: true, x: event.clientX, y: event.clientY }
  }

  function startProfileDrag(profile: TerminalProfile | null): void {
    draggedProfile.value = profile
  }

  function dropProfileOnFolder(folderId: string): void {
    const profile = draggedProfile.value
    draggedProfile.value = null
    if (profile && profile.folder_id !== folderId) void saveProfileAction(profile, 'move', folderId)
  }

  async function openSelectedDevices(): Promise<void> {
    const selected = devices.value.filter((device) => selectedDeviceUuids.value.includes(device.device_uuid))
    for (const device of selected) await openDevice(device)
  }

  async function openSession(session: TerminalSession): Promise<void> {
    if (session.detached_window && String(router.currentRoute.value.query.terminal_session || '') !== session.session_id) {
      ElMessage.info('此会话在独立窗口中运行，可克隆为新会话')
      return
    }
    const existing = tabs.value.find((tab) => tab.id === session.session_id)
    if (existing) {
      selectTab(existing.id)
      return
    }
    if (['CLOSED', 'FAILED', 'CANCELLED'].includes(session.state)) {
      await showReplay(session)
      return
    }
    try {
      const ticket = await issueTerminalTicket(session.session_id)
      if (!disposed) addTerminalTab({ session, ticket: ticket.ticket })
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '活动会话重新打开失败')
    }
  }

  async function cloneSession(session: TerminalSession): Promise<void> {
    try { addTerminalTab(await cloneTerminalSession(session.session_id)); await loadSessions() }
    catch (error) { ElMessage.error(error instanceof Error ? error.message : '克隆会话失败') }
  }

  async function renameSession(session: TerminalSession) {
    try {
      const { value } = await ElMessageBox.prompt('会话名称', '重命名终端会话', { inputValue: session.session_name || session.device_name })
      updateSession(session.session_id, await renameTerminalSession(session.session_id, value))
      await loadSessions()
    } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '重命名失败') }
  }

  async function saveConnectionTemplate(session: TerminalSession) {
    try {
      // Resolve credentials in Python; renderer only requests a template by ID.
      await import('../../api/client').then(({ apiRequest }) => apiRequest(`/api/terminal/sessions/${session.session_id}/save-profile`, { method: 'POST' }))
      await loadProfiles()
    } catch (error) { ElMessage.error(error instanceof Error ? error.message : '保存连接失败') }
  }

  async function deleteRecording(session: TerminalSession) {
    try {
      await ElMessageBox.confirm(`删除 ${session.device_name} 在 ${formatTime(session.created_at_ms)} 的录制？`, '删除录制记录', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
      await deleteTerminalRecording(session.session_id)
      if (replaySession.value?.session_id === session.session_id) replayVisible.value = false
      await Promise.all([showHistory(), loadSessions()])
    } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '删除录制失败，可重试') }
  }

  function toggleDeviceSelection(deviceUuid: string, checked: boolean): void {
    selectedDeviceUuids.value = checked
      ? [...new Set([...selectedDeviceUuids.value, deviceUuid])]
      : selectedDeviceUuids.value.filter((value) => value !== deviceUuid)
  }

  function selectTab(tabId: string): void {
    if (!tabs.value.some((tab) => tab.id === tabId) || closingTabIds.value.has(tabId)) return
    if (splitOrientation.value === 'none') {
      primaryTabId.value = tabId
    } else if (tabId !== primaryTabId.value && tabId !== secondaryTabId.value) {
      if (activeTabId.value === primaryTabId.value) secondaryTabId.value = tabId
      else primaryTabId.value = tabId
    }
    activeTabId.value = tabId
    nextTick(() => terminalRefs.value[tabId]?.focus())
  }

  function removeTab(tabId: string): void {
    closingTabIds.value.delete(tabId)
    const index = tabs.value.findIndex((tab) => tab.id === tabId)
    if (index < 0) return
    tabs.value.splice(index, 1)
    if (primaryTabId.value === tabId) {
      primaryTabId.value = tabs.value.find((tab) => tab.id !== secondaryTabId.value)?.id || secondaryTabId.value
    }
    if (secondaryTabId.value === tabId) secondaryTabId.value = tabs.value.find((tab) => tab.id !== primaryTabId.value)?.id || ''
    const focusRemoved = activeTabId.value === tabId
    if (focusRemoved) activeTabId.value = primaryTabId.value || tabs.value[0]?.id || ''
    if (tabs.value.length < 2 || primaryTabId.value === secondaryTabId.value || !secondaryTabId.value) closeSplit()
    if (focusRemoved && activeTabId.value) nextTick(() => terminalRefs.value[activeTabId.value]?.focus())
  }

  async function closeTab(tabId: string): Promise<void> {
    const tab = tabs.value.find((item) => item.id === tabId)
    if (!tab || closingTabIds.value.has(tabId)) return
    if (['CLOSED', 'FAILED', 'CANCELLED'].includes(tab.session.state)) {
      removeTab(tabId)
      return
    }
    closingTabIds.value.add(tabId)
    try {
      updateSession(tabId, await closeTerminalSession(tabId))
    } catch (error) {
      closingTabIds.value.delete(tabId)
      ElMessage.error(error instanceof Error ? error.message : '结束终端会话失败')
    }
  }

  async function closeOtherTabs(tabId: string): Promise<void> {
    if (!tabs.value.some(tab => tab.id === tabId)) return
    const removed = tabs.value.filter((tab) => tab.id !== tabId)
    await Promise.all(removed.map((tab) => closeTab(tab.id)))
    if (tabs.value.some((tab) => tab.id === tabId)) {
      activeTabId.value = tabId
      primaryTabId.value = tabId
      secondaryTabId.value = ''
      splitOrientation.value = 'none'
    }
  }

  async function closeAllTabs(): Promise<void> {
    try { await ElMessageBox.confirm('关闭所有标签并结束对应终端会话？', '关闭所有标签', { confirmButtonText: '关闭并结束', cancelButtonText: '取消' }) }
    catch { return }
    await Promise.all(tabs.value.map((tab) => closeTab(tab.id)))
  }

  function startTabDrag(tabId: string): void {
    draggedTabId.value = tabId
  }

  function dropTab(beforeTabId: string): void {
    const tabId = draggedTabId.value
    draggedTabId.value = ''
    if (!tabId || tabId === beforeTabId) return
    const sourceIndex = tabs.value.findIndex((tab) => tab.id === tabId)
    const targetIndex = tabs.value.findIndex((tab) => tab.id === beforeTabId)
    if (sourceIndex < 0 || targetIndex < 0) return
    const [tab] = tabs.value.splice(sourceIndex, 1)
    tabs.value.splice(targetIndex, 0, tab)
  }

  async function terminateActiveSession(): Promise<void> {
    const tab = activeTab.value
    if (!tab) return
    try {
      await ElMessageBox.confirm(
        `结束 ${tab.session.device_name} 的后端会话？录制与历史将保留。`,
        '结束会话',
        { type: 'warning', confirmButtonText: '结束会话', cancelButtonText: '取消' },
      )
      await closeTab(tab.id)
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '会话关闭失败')
    }
  }

  async function reconnectActiveSession(): Promise<void> {
    const tab = activeTab.value
    if (!tab) return
    await reconnectSession(tab.session, true)
  }

  async function reconnectSession(session: TerminalSession, closeExistingTab = false): Promise<void> {
    if (reconnectingIds.has(session.session_id) || closingTabIds.value.has(session.session_id)) return
    reconnectingIds.add(session.session_id)
    try {
      const created = await reconnectTerminalSession(session.session_id)
      if (closeExistingTab) removeTab(session.session_id)
      addTerminalTab(created)
      await loadSessions()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话重连失败')
    } finally {
      reconnectingIds.delete(session.session_id)
    }
  }

  async function terminateSession(session: TerminalSession): Promise<void> {
    if (tabs.value.some((tab) => tab.id === session.session_id)) {
      await closeTab(session.session_id)
      return
    }
    if (['CLOSED', 'FAILED', 'CANCELLED'].includes(session.state)) return
    try {
      const closed = await closeTerminalSession(session.session_id)
      updateSession(session.session_id, closed)
      await loadSessions()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话关闭失败')
    }
  }

  function updateSession(tabId: string, session: TerminalSession): void {
    if (session.state === 'CLOSED' || session.state === 'CANCELLED'
      || (closingTabIds.value.has(tabId) && endedStates.includes(session.state))) removeTab(tabId)
    const tab = tabs.value.find((item) => item.id === tabId)
    if (tab) tab.session = session
    const stored = sessions.value.findIndex((item) => item.session_id === session.session_id)
    if (stored >= 0) sessions.value[stored] = session
  }

  function setSplit(orientation: Exclude<SplitOrientation, 'none'>): void {
    if (tabs.value.length < 2) {
      ElMessage.info('至少打开两个终端后才能分屏')
      return
    }
    if (splitOrientation.value === 'none') {
      secondaryTabId.value = tabs.value.find((tab) => tab.id !== primaryTabId.value)?.id || ''
    }
    splitOrientation.value = orientation
    splitRatio.value = 0.5
    void nextTick(fitVisibleTerminals)
  }

  function closeSplit(): void {
    stopDividerDrag?.()
    splitOrientation.value = 'none'
    secondaryTabId.value = ''
    primaryTabId.value = activeTabId.value || primaryTabId.value
    void nextTick(fitVisibleTerminals)
  }

  function fitVisibleTerminals(): void {
    for (const id of visibleTabIds.value) terminalRefs.value[id]?.fit()
  }

  function startDividerDrag(event: PointerEvent): void {
    event.preventDefault()
    const element = workspace.value
    if (!element || splitOrientation.value === 'none') return
    const move = (moveEvent: PointerEvent) => {
      const rect = element.getBoundingClientRect()
      const ratio = splitOrientation.value === 'horizontal'
        ? (moveEvent.clientX - rect.left) / rect.width
        : (moveEvent.clientY - rect.top) / rect.height
      splitRatio.value = Math.max(0.2, Math.min(0.8, ratio))
      void nextTick(fitVisibleTerminals)
    }
    stopDividerDrag?.()
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      stopDividerDrag = undefined
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
    window.addEventListener('pointercancel', stop, { once: true })
    stopDividerDrag = stop
  }

  function clearActiveTerminal(): void {
    if (activeTabId.value) terminalRefs.value[activeTabId.value]?.clear()
  }

  function executeActiveTerminalMenuFunction(id: 'find' | 'select-all' | 'clear-scrollback' | 'clear-screen' | 'clear-all'): void {
    if (!activeTabId.value) return
    void terminalRefs.value[activeTabId.value]?.executeMenuFunction(id)
  }

  function searchActiveTerminal(backwards = false): void {
    if (!activeTabId.value || !terminalSearch.value) return
    const found = terminalRefs.value[activeTabId.value]?.search(terminalSearch.value, backwards)
    if (!found) ElMessage.info('未找到匹配内容')
  }

  function toggleGroup(name: string): void {
    expandedGroups.value = expandedGroups.value.includes(name)
      ? expandedGroups.value.filter((value) => value !== name)
      : [...expandedGroups.value, name]
  }

  function expandAllGroups(): void {
    expandedGroups.value = groupedDevices.value.map((group) => group.name)
  }

  function collapseAllGroups(): void {
    expandedGroups.value = []
  }

  async function startManualLog(): Promise<void> {
    const tab = activeTab.value
    if (!tab) return
    try {
      const { value } = await ElMessageBox.prompt('输入会话日志文件名', '开始会话日志', {
        inputValue: `${tab.session.device_name}-${new Date().toISOString().slice(0, 10)}`,
        confirmButtonText: '开始记录',
        cancelButtonText: '取消',
      })
      let directoryPath = terminalSettings.value?.manual_log_recent_directory || ''
      const adapter = getPlatformAdapter()
      if (adapter.hostType === 'electron' && !directoryPath) {
        const selected = await adapter.selectDirectory()
        if (selected.cancelled || !selected.path) return
        directoryPath = selected.path
        terminalSettings.value = await updateTerminalSettings({ manual_log_recent_directory: directoryPath })
      }
      const suggestedName = `${value.replace(/\.(txt|jsonl)$/i, '')}.txt`
      let destination
      try {
        destination = await prepareLocalSaveDestination({
          suggestedName,
          extensions: ['txt'],
          filters: [{ name: '终端会话日志', extensions: ['txt'] }],
          ...(directoryPath ? { directoryPath } : {}),
        })
      } catch (error) {
        if (adapter.hostType !== 'electron') throw error
        const selected = await adapter.selectDirectory()
        if (selected.cancelled || !selected.path) return
        directoryPath = selected.path
        terminalSettings.value = await updateTerminalSettings({ manual_log_recent_directory: directoryPath })
        destination = await prepareLocalSaveDestination({
          suggestedName,
          extensions: ['txt'],
          filters: [{ name: '终端会话日志', extensions: ['txt'] }],
          directoryPath,
        })
      }
      if (!destination) return
      manualLogTargets.set(tab.id, {
        destinationPath: destination.path,
        suggestedName: destination.fileName,
      })
      updateSession(tab.id, await startTerminalManualLog(tab.id, value, 'txt'))
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '会话日志启动失败')
    }
  }

  async function pauseOrResumeManualLog(): Promise<void> {
    const tab = activeTab.value
    if (!tab) return
    try {
      const updated = tab.session.manual_log_status === 'PAUSED'
        ? await resumeTerminalManualLog(tab.id)
        : await pauseTerminalManualLog(tab.id)
      updateSession(tab.id, updated)
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话日志状态更新失败')
    }
  }

  async function stopManualLog(): Promise<void> {
    const tab = activeTab.value
    if (!tab) return
    try {
      const updated = await stopTerminalManualLog(tab.id)
      updateSession(tab.id, updated)
      const request = terminalManualLogDownloadRequest(
        tab.id,
        updated.manual_log_id,
        updated.manual_log_filename,
      )
      const target = manualLogTargets.get(tab.id)
      const adapter = getPlatformAdapter()
      if (adapter.hostType === 'electron' && target?.destinationPath) {
        request.suggestedName = target.suggestedName
        request.destinationPath = target.destinationPath
      }
      const result = await downloadBackendResource(request)
      manualLogTargets.delete(tab.id)
      ElMessage.success(result.status === 'saved' ? '会话日志已保存' : '浏览器已开始下载')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话日志停止或保存失败')
    }
  }

  async function loadTerminalPreferences(): Promise<void> {
    try {
      const [settings, rules] = await Promise.all([getTerminalSettings(), getTerminalHighlightRules()])
      terminalSettings.value = settings
      highlightRules.value = rules.rules
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '终端设置读取失败')
    }
  }

  function applyTerminalPreferences(settings: TerminalSettings, rules: TerminalHighlightRule[]): void {
    terminalSettings.value = settings
    highlightRules.value = rules
  }

  async function showHistory(): Promise<void> {
    historyVisible.value = true
    historyLoading.value = true
    try {
      history.value = (await listTerminalHistory(sessionSearch.value, 200)).items
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话历史读取失败')
    } finally {
      historyLoading.value = false
    }
  }

  async function showReplay(session: TerminalSession): Promise<void> {
    replaySession.value = session
    replayVisible.value = true
    replayLoading.value = true
    replayEvents.value = []
    try {
      const { apiRequest } = await import('../../api/client')
      const result = await apiRequest<{ text: string; truncated: boolean }>(`/api/terminal/history/${session.session_id}/transcript`)
      replayEvents.value = [{ at_ms: 0, event_type: 'OUTPUT', data: result.text + (result.truncated ? '\n[预览已截断，请导出完整 LOG]' : '') }]
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话录制读取失败')
    } finally {
      replayLoading.value = false
    }
  }

  async function exportReplay(format: 'txt' | 'jsonl' | 'log' | 'zip', session = replaySession.value): Promise<void> {
    if (!session) return
    try {
      const name = format === 'log' ? session.recording_log_name : format === 'zip' ? session.recording_zip_name : undefined
      const result = await downloadBackendResource(terminalExportDownloadRequest(session.session_id, format, name))
      if (result.status === 'saved') ElMessage.success('会话记录已保存')
      else if (result.status === 'started') ElMessage.info('浏览器已开始下载')
      else if (result.status === 'failed') ElMessage.error(result.error || '保存失败')
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话记录导出失败')
    }
  }

  function sessionStatusClass(state: string): string {
    if (['CONNECTED', 'RUNNING'].includes(state)) return 'is-success'
    if (['FAILED', 'CANCELLED'].includes(state)) return 'is-danger'
    if (['CLOSED', 'DISCONNECTED'].includes(state)) return 'is-muted'
    return 'is-warning'
  }

  function showDeviceMenu(event: MouseEvent, device: DeviceListItem): void {
    event.preventDefault()
    hideContextMenu()
    selectedDeviceUuid.value = device.device_uuid
    contextDevice.value = device
    contextMenu.value = { visible: true, x: event.clientX, y: event.clientY }
    sessionContextMenu.value.visible = false
  }

  function showSessionMenu(event: MouseEvent, session: TerminalSession): void {
    event.preventDefault()
    hideContextMenu()
    contextSession.value = session
    sessionContextMenu.value = { visible: true, x: event.clientX, y: event.clientY }
    contextMenu.value.visible = false
  }

  function openDeviceDetail(device: DeviceListItem): void {
    void router.push({ name: 'device-detail', params: { deviceId: device.device_uuid } })
    hideContextMenu()
  }

  function hideContextMenu(): void {
    contextMenu.value.visible = false
    sessionContextMenu.value.visible = false
    profileContextMenu.value.visible = false
  }

  function formatTime(value: number | null): string {
    return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
  }

  function recordingText(session: TerminalSession): string {
    return ({ RECORDING: '录制中', FINALIZING: '整理中', COMPRESSING: '压缩中', COMPLETED: '录制完成', COMPLETE: '历史录制', FAILED: '录制失败', INCOMPLETE: '录制中断' })[session.recording_status] || session.recording_status
  }

  const replayText = computed(() => replayEvents.value
    .filter((event) => event.event_type === 'OUTPUT' || event.event_type === 'INPUT')
    .map((event) => event.event_type === 'INPUT' ? `\n> ${event.data || ''}\n` : String(event.data || ''))
    .join(''))

  onMounted(async () => {
    window.addEventListener('click', hideContextMenu)
    await Promise.all([loadDevices(), loadSessions(), loadProfiles(), loadTerminalPreferences()])
    if (disposed) return
    const detachedId = String(router.currentRoute.value.query.terminal_session || '')
    if (/^[a-f0-9]{32}$/.test(detachedId)) {
      try {
        const { apiRequest } = await import('../../api/client')
        const session = await apiRequest<TerminalSession>(`/api/terminal/history/${detachedId}`)
        await openSession(session)
      } catch (error) { ElMessage.error(String(error)) }
    }
    const requestedDeviceUuid = String(router.currentRoute.value.query.device_uuid || '').trim()
    if (requestedDeviceUuid) {
      const { device_uuid: _deviceUuid, ...query } = router.currentRoute.value.query
      await router.replace({ name: 'device-console', query, hash: router.currentRoute.value.hash })
      const requestedDevice = devices.value.find((device) => device.device_uuid === requestedDeviceUuid)
      if (requestedDevice) await openDevice(requestedDevice)
      else ElMessage.warning('设备已不存在或不属于当前局点')
    }
    if (!disposed) activityTimer = setInterval(() => void refreshActiveSessions(), 3000)
  })

  onBeforeUnmount(() => {
    disposed = true
    window.removeEventListener('click', hideContextMenu)
    if (activityTimer) clearInterval(activityTimer)
    stopDividerDrag?.()
  })
  watch(() => router.currentRoute.value.query.device_uuid, async value => {
    if (router.currentRoute.value.name !== 'device-console' || !value) return
    const id = String(value)
    const { device_uuid: _id, ...query } = router.currentRoute.value.query
    await router.replace({ name: 'device-console', query, hash: router.currentRoute.value.hash })
    const device = devices.value.find(item => item.device_uuid === id)
    if (device) await openDevice(device)
  })

  return {
    addTerminalTab,
    selectedSessionIds,
    sessionStateFilter,
    cloneSession,
    renameSession,
    saveConnectionTemplate,
    deleteRecording,
    devices,
    sessions,
    profiles,
    profileFolders,
    history,
    tabs,
    selectedDeviceUuid,
    selectedDeviceUuids,
    activeTabId,
    closingTabIds,
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
    contextProfile,
    sessionContextMenu,
    profileContextMenu,
    collapsedProfileGroups,
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
    openDeviceExternalTerminal,
    copyConnectionAddress,
    externalTerminalBusy: externalTerminalLauncher.busy,
    quickConnect,
    openProfile,
    connectProfileAtAddress,
    importProfiles,
    exportProfiles,
    editProfile,
    saveProfileAction,
    toggleProfileGroup,
    showProfileMenu,
    startProfileDrag,
    dropProfileOnFolder,
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
    executeActiveTerminalMenuFunction,
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
  }
}
