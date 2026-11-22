import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listDevices } from '../../api/deviceManagement'
import {
  closeTerminalSession,
  connectTerminalProfile,
  createTerminalProfileFolder,
  createTerminalSession,
  deleteTerminalProfile,
  deleteTerminalProfileFolder,
  getTerminalHighlightRules,
  getTerminalHistoryEvents,
  getTerminalSettings,
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
  type TerminalRecordingEvent,
  type TerminalSession,
  type TerminalSettings,
} from '../../api/terminal'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import { prepareLocalSaveDestination } from '../../composables/useUserSelectedExport'
import type { DeviceListItem } from '../../types/deviceManagement'
import TerminalPane from './TerminalPane.vue'

type SplitOrientation = 'none' | 'horizontal' | 'vertical'

interface TerminalTab {
  id: string
  session: TerminalSession
  ticket: string
}


export function useConsoleWorkspace() {
  const router = useRouter()
  const devices = ref<DeviceListItem[]>([])
  const sessions = ref<TerminalSession[]>([])
  const profiles = ref<TerminalProfile[]>([])
  const profileFolders = ref<TerminalProfileFolder[]>([])
  const history = ref<TerminalSession[]>([])
  const tabs = ref<TerminalTab[]>([])
  const selectedDeviceUuid = ref('')
  const selectedDeviceUuids = ref<string[]>([])
  const activeTabId = ref('')
  const secondaryTabId = ref('')
  const navigationMode = ref<'devices' | 'profiles' | 'sessions'>('devices')
  const deviceSearch = ref('')
  const sessionSearch = ref('')
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
  const draggedTabId = ref('')
  const manualLogTargets = new Map<string, { destinationPath: string; suggestedName: string }>()
  let activityTimer: ReturnType<typeof setInterval> | undefined
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
      profile.username,
      profile.vendor,
      profile.device_type,
    ].join(' ').toLowerCase().includes(needle))
    const groups = profileFolders.value.map((folder) => ({
      id: folder.folder_id,
      name: folder.name,
      items: visible.filter((profile) => profile.folder_id === folder.folder_id),
    }))
    const root = visible.filter((profile) => !profile.folder_id)
    return root.length ? [{ id: '', name: '未分组', items: root }, ...groups] : groups
  })

  function syncExpandedGroups(): void {
    const available = groupedDevices.value.map((group) => group.name)
    if (!expandedGroups.value.length) expandedGroups.value = available
    else expandedGroups.value = expandedGroups.value.filter((name) => available.includes(name))
  }

  const filteredSessions = computed(() => {
    const needle = sessionSearch.value.trim().toLowerCase()
    if (!needle) return sessions.value
    return sessions.value.filter((session) => [
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
    if (activeTabId.value) result.add(activeTabId.value)
    if (splitOrientation.value !== 'none' && secondaryTabId.value) result.add(secondaryTabId.value)
    return result
  })

  const workspaceStyle = computed(() => {
    const primary = `${Math.round(splitRatio.value * 1000) / 10}%`
    const secondary = `${Math.round((1 - splitRatio.value) * 1000) / 10}%`
    if (splitOrientation.value === 'horizontal') {
      return { gridTemplateColumns: `${primary} 5px ${secondary}`, gridTemplateRows: 'minmax(0, 1fr)' }
    }
    if (splitOrientation.value === 'vertical') {
      return { gridTemplateRows: `${primary} 5px ${secondary}`, gridTemplateColumns: 'minmax(0, 1fr)' }
    }
    return { gridTemplateColumns: 'minmax(0, 1fr)', gridTemplateRows: 'minmax(0, 1fr)' }
  })

  function paneClass(tabId: string): string[] {
    if (tabId === activeTabId.value) return ['terminal-grid__pane', 'is-primary']
    if (splitOrientation.value !== 'none' && tabId === secondaryTabId.value) return ['terminal-grid__pane', 'is-secondary']
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
    try {
      const active = await listTerminalSessions()
      const byId = new Map(active.items.map((item) => [item.session_id, item]))
      for (const tab of tabs.value) {
        const updated = byId.get(tab.id)
        if (updated) tab.session = updated
      }
      sessions.value = sessions.value.map((item) => byId.get(item.session_id) || item)
    } catch {
      // The WebSocket owns terminal connectivity; status polling is best effort.
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
    const tab: TerminalTab = {
      id: created.session.session_id,
      session: created.session,
      ticket: created.ticket,
    }
    tabs.value.push(tab)
    activeTabId.value = tab.id
    if (splitOrientation.value !== 'none' && !secondaryTabId.value) secondaryTabId.value = tab.id
  }

  async function openDevice(device: DeviceListItem): Promise<void> {
    selectedDeviceUuid.value = device.device_uuid
    const existing = tabs.value.find((tab) => tab.session.device_uuid === device.device_uuid && !['CLOSED', 'FAILED'].includes(tab.session.state))
    if (existing) {
      activeTabId.value = existing.id
      await nextTick()
      terminalRefs.value[existing.id]?.focus()
      return
    }
    openingDeviceUuid.value = device.device_uuid
    try {
      const created = await createTerminalSession(device.device_uuid, 'AUTO')
      addTerminalTab(created)
      await loadSessions()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '终端会话创建失败')
    } finally {
      openingDeviceUuid.value = ''
    }
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
    try {
      let password = ''
      if (!profile.password_configured) {
        const result = await ElMessageBox.prompt(
          `输入 ${profile.name} 的登录密码`,
          '连接保存会话',
          { inputType: 'password', confirmButtonText: '连接', cancelButtonText: '取消' },
        )
        password = result.value
      }
      const created = await connectTerminalProfile(profile.profile_id, password)
      addTerminalTab(created)
      await loadSessions()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') {
        ElMessage.error(error instanceof Error ? error.message : '保存会话连接失败')
      }
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

  async function openSelectedDevices(): Promise<void> {
    const selected = devices.value.filter((device) => selectedDeviceUuids.value.includes(device.device_uuid))
    for (const device of selected.slice(0, 8)) await openDevice(device)
  }

  async function openSession(session: TerminalSession): Promise<void> {
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
      tabs.value.push({ id: session.session_id, session, ticket: ticket.ticket })
      activeTabId.value = session.session_id
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '活动会话重新打开失败')
    }
  }

  function toggleDeviceSelection(deviceUuid: string, checked: boolean): void {
    selectedDeviceUuids.value = checked
      ? [...new Set([...selectedDeviceUuids.value, deviceUuid])]
      : selectedDeviceUuids.value.filter((value) => value !== deviceUuid)
  }

  function selectTab(tabId: string): void {
    if (splitOrientation.value !== 'none' && tabId !== activeTabId.value && activeTabId.value) {
      secondaryTabId.value = tabId
    } else {
      activeTabId.value = tabId
    }
    nextTick(() => terminalRefs.value[tabId]?.focus())
  }

  function closeTab(tabId: string): void {
    const index = tabs.value.findIndex((tab) => tab.id === tabId)
    if (index < 0) return
    tabs.value.splice(index, 1)
    if (activeTabId.value === tabId) activeTabId.value = tabs.value[Math.max(0, index - 1)]?.id || ''
    if (secondaryTabId.value === tabId) secondaryTabId.value = tabs.value.find((tab) => tab.id !== activeTabId.value)?.id || ''
    if (tabs.value.length < 2) splitOrientation.value = 'none'
  }

  function closeOtherTabs(tabId: string): void {
    tabs.value = tabs.value.filter((tab) => tab.id === tabId)
    activeTabId.value = tabId
    secondaryTabId.value = ''
    splitOrientation.value = 'none'
  }

  function closeAllTabs(): void {
    tabs.value = []
    activeTabId.value = ''
    secondaryTabId.value = ''
    splitOrientation.value = 'none'
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
      const session = await closeTerminalSession(tab.id)
      updateSession(tab.id, session)
      await loadSessions()
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
    try {
      const created = await reconnectTerminalSession(session.session_id)
      if (closeExistingTab) closeTab(session.session_id)
      tabs.value.push({ id: created.session.session_id, session: created.session, ticket: created.ticket })
      activeTabId.value = created.session.session_id
      await loadSessions()
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话重连失败')
    }
  }

  async function terminateSession(session: TerminalSession): Promise<void> {
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
    splitOrientation.value = orientation
    secondaryTabId.value = tabs.value.find((tab) => tab.id !== activeTabId.value)?.id || ''
    splitRatio.value = 0.5
    nextTick(() => {
      terminalRefs.value[activeTabId.value]?.fit()
      terminalRefs.value[secondaryTabId.value]?.fit()
    })
  }

  function closeSplit(): void {
    splitOrientation.value = 'none'
    secondaryTabId.value = ''
    nextTick(() => terminalRefs.value[activeTabId.value]?.fit())
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
      terminalRefs.value[activeTabId.value]?.fit()
      terminalRefs.value[secondaryTabId.value]?.fit()
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
  }

  function clearActiveTerminal(): void {
    if (activeTabId.value) terminalRefs.value[activeTabId.value]?.clear()
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
      replayEvents.value = (await getTerminalHistoryEvents(session.session_id, 0, 2000)).items
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '会话录制读取失败')
    } finally {
      replayLoading.value = false
    }
  }

  async function exportReplay(format: 'txt' | 'jsonl'): Promise<void> {
    if (!replaySession.value) return
    try {
      const result = await downloadBackendResource(terminalExportDownloadRequest(replaySession.value.session_id, format))
      ElMessage.success(result.status === 'saved' ? '会话记录已保存' : '浏览器已开始下载')
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
    selectedDeviceUuid.value = device.device_uuid
    contextDevice.value = device
    contextMenu.value = { visible: true, x: event.clientX, y: event.clientY }
    sessionContextMenu.value.visible = false
  }

  function showSessionMenu(event: MouseEvent, session: TerminalSession): void {
    event.preventDefault()
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
  }

  function formatTime(value: number | null): string {
    return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
  }

  function recordingText(session: TerminalSession): string {
    if (session.recording_status === 'COMPLETE') return '录制完整'
    if (session.recording_status === 'INCOMPLETE') return '录制不完整'
    return '录制中'
  }

  const replayText = computed(() => replayEvents.value
    .filter((event) => event.event_type === 'OUTPUT' || event.event_type === 'INPUT')
    .map((event) => event.event_type === 'INPUT' ? `\n> ${event.data || ''}\n` : String(event.data || ''))
    .join(''))

  onMounted(async () => {
    window.addEventListener('click', hideContextMenu)
    await Promise.all([loadDevices(), loadSessions(), loadProfiles(), loadTerminalPreferences()])
    const requestedDeviceUuid = String(router.currentRoute.value.query.device_uuid || '').trim()
    if (requestedDeviceUuid) {
      const { device_uuid: _deviceUuid, ...query } = router.currentRoute.value.query
      await router.replace({ name: 'device-console', query, hash: router.currentRoute.value.hash })
      const requestedDevice = devices.value.find((device) => device.device_uuid === requestedDeviceUuid)
      if (requestedDevice) await openDevice(requestedDevice)
      else ElMessage.warning('设备已不存在或不属于当前局点')
    }
    activityTimer = setInterval(() => void refreshActiveSessions(), 3000)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('click', hideContextMenu)
    if (activityTimer) clearInterval(activityTimer)
  })

  return {
    devices,
    sessions,
    profiles,
    profileFolders,
    history,
    tabs,
    selectedDeviceUuid,
    selectedDeviceUuids,
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
  }
}
