<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'

import NcDataTable from '../../src/components/table/NcDataTable.vue'
import type { NcDataTableContextMenuItem } from '../../src/components/table/NcDataTableContextMenu'
import type { NcTableColumn } from '../../src/components/table/NcTableColumn'
import { setAppLocale } from '../../src/i18n/runtime'
import { applyNetConsoleTheme, NETCONSOLE_THEME_CHANGE_EVENT } from '../../src/theme/theme'
import type { SystemLanguage, SystemTheme } from '../../src/types/systemSettings'

type PageId = 'dashboard' | 'devices' | 'device-detail' | 'fit-ap' | 'trackside' | 'online-mr' | 'job-center' | 'traffic' | 'agent' | 'settings'

interface MatrixRow {
  name: string
  address: string
  status: 'online' | 'warning' | 'failed'
  detail: string
  action: string
}

const query = new URLSearchParams(window.location.search)
const initialLocale: SystemLanguage = query.get('locale') === 'en' ? 'en_US' : 'zh_CN'
const initialTheme: SystemTheme = query.get('theme') === 'dark' ? 'dark' : 'light'

const locale = ref<SystemLanguage>(initialLocale)
const theme = ref<SystemTheme>(initialTheme)
const sidebarCollapsed = ref(false)
const drawerOpen = ref(false)
const dialogOpen = ref(false)
const contextMenuOpen = ref(false)
const resizeCount = ref(0)
const contentRef = ref<HTMLElement>()
const chartRefs = ref<HTMLElement[]>([])
const charts = new Map<HTMLElement, echarts.ECharts>()
let resizeObserver: ResizeObserver | undefined

const translations = {
  zh_CN: {
    title: '桌面视觉矩阵夹具',
    description: '固定数据验证主要业务页面的布局、主题、语言、表格、弹窗和图表契约。',
    primaryAction: '刷新视图',
    secondaryAction: '导出当前视图',
    switchLanguage: '切换 English',
    switchTheme: '切换深色主题',
    sidebar: '主导航',
    resize: '重算次数',
    openDrawer: '打开任务详情',
    openDialog: '打开确认对话框',
    drawerTitle: '任务详情',
    dialogTitle: '确认操作',
    cancel: '取消',
    confirm: '确认',
    status: '部分成功',
    taskSource: '触发来源：用户界面',
    concurrency: '并发：请求 128 / 有效 64 / 平台上限 64',
    chartTitle: '趋势与吞吐',
    empty: '暂无数据',
    pageDescriptions: {
      dashboard: '总览指标、告警和当前局点摘要',
      devices: '设备列表、筛选、排序和行操作',
      'device-detail': '设备详情、接口和状态信息',
      'fit-ap': 'FIT-AP 资源和射频状态',
      trackside: '轨旁 AP 业务与并发摘要',
      'online-mr': 'Online MR 采集趋势和 Tooltip',
      'job-center': '任务状态、来源和结果摘要',
      traffic: '流量测试和带宽图表',
      agent: 'Agent 状态与连接能力',
      settings: '系统设置、主题和语言入口',
    } as Record<PageId, string>,
    pages: {
      dashboard: 'Dashboard',
      devices: '设备管理',
      'device-detail': '设备详情',
      'fit-ap': 'FIT-AP 资源',
      trackside: '轨旁 AP 业务',
      'online-mr': 'Online MR',
      'job-center': '任务中心',
      traffic: '流量测试',
      agent: 'Agent',
      settings: '系统设置',
    } as Record<PageId, string>,
    columns: ['设备名称', '主地址', '状态', '错误与说明摘要', '操作'],
    actions: ['查看', '重试', '更多'],
    menu: ['查看详情', '复制地址', '外部终端'],
  },
  en_US: {
    title: 'Desktop visual matrix fixture',
    description: 'Fixed data validates layout, theme, language, table, dialog and chart contracts across core pages.',
    primaryAction: 'Refresh view',
    secondaryAction: 'Export current view',
    switchLanguage: '切换中文',
    switchTheme: 'Switch to dark theme',
    sidebar: 'Primary navigation',
    resize: 'Reflow count',
    openDrawer: 'Open task detail',
    openDialog: 'Open confirmation dialog',
    drawerTitle: 'Task detail',
    dialogTitle: 'Confirm action',
    cancel: 'Cancel',
    confirm: 'Confirm',
    status: 'Partial success',
    taskSource: 'Trigger source: User interface',
    concurrency: 'Concurrency: requested 128 / effective 64 / platform limit 64',
    chartTitle: 'Trend and throughput',
    empty: 'No data',
    pageDescriptions: {
      dashboard: 'Overview metrics, alerts and active site summary',
      devices: 'Device list, filters, sorting and row actions',
      'device-detail': 'Device detail, interfaces and status information',
      'fit-ap': 'FIT-AP resources and radio status',
      trackside: 'Trackside AP business and concurrency summary',
      'online-mr': 'Online MR collection trend and tooltip',
      'job-center': 'Task status, provenance and result summary',
      traffic: 'Traffic testing and bandwidth chart',
      agent: 'Agent status and connection capability',
      settings: 'System settings, theme and language entry',
    } as Record<PageId, string>,
    pages: {
      dashboard: 'Dashboard',
      devices: 'Device Management',
      'device-detail': 'Device Detail',
      'fit-ap': 'FIT-AP Resources',
      trackside: 'Trackside AP Business',
      'online-mr': 'Online MR',
      'job-center': 'Job Center',
      traffic: 'Traffic Test',
      agent: 'Agent',
      settings: 'Settings',
    } as Record<PageId, string>,
    columns: ['Device name', 'Primary address', 'Status', 'Error and description summary', 'Actions'],
    actions: ['View', 'Retry', 'More'],
    menu: ['View details', 'Copy address', 'External terminal'],
  },
} as const

const labels = computed(() => translations[locale.value])
const pageIds: PageId[] = ['dashboard', 'devices', 'device-detail', 'fit-ap', 'trackside', 'online-mr', 'job-center', 'traffic', 'agent', 'settings']
const pages = computed(() => pageIds.map((id) => ({ id, title: labels.value.pages[id], description: labels.value.pageDescriptions[id] })))

const rows: MatrixRow[] = [
  { name: 'AP-01 / Northbound platform access point with a long stable name', address: '192.168.10.11', status: 'online', detail: 'Stable sample row for tooltip and table width measurement.', action: 'view' },
  { name: 'Switch-GE-2/0/1', address: '10.0.0.1', status: 'warning', detail: 'Partial result with a deliberately long diagnostic description.', action: 'retry' },
  { name: 'MR-TRAIN-0007', address: '2001:db8::20', status: 'failed', detail: 'Connection information incomplete; retained as a structured skip.', action: 'more' },
]

const columns = computed<NcTableColumn<MatrixRow>[]>(() => [
  { key: 'name', label: labels.value.columns[0], valueType: 'name', minWidth: 220 },
  { key: 'address', label: labels.value.columns[1], valueType: 'ip', minWidth: 150 },
  { key: 'status', label: labels.value.columns[2], valueType: 'status', cellKind: 'tag', width: 120 },
  { key: 'detail', label: labels.value.columns[3], valueType: 'description', align: 'left', alignmentReason: 'long-text', minWidth: 260 },
  { key: 'action', label: labels.value.columns[4], valueType: 'actions', cellKind: 'actions', width: 150, actionLabels: [...labels.value.actions] },
])

const contextMenuItems = computed<NcDataTableContextMenuItem<MatrixRow>[]>(() => [
  { key: 'detail', label: labels.value.menu[0], action: () => { contextMenuOpen.value = false } },
  { key: 'copy', label: labels.value.menu[1], action: () => { contextMenuOpen.value = false } },
  { key: 'terminal', label: labels.value.menu[2], action: () => { contextMenuOpen.value = false } },
])

function updateRoot(): void {
  document.documentElement.lang = locale.value === 'en_US' ? 'en' : 'zh-CN'
  document.documentElement.dataset.visualLocale = locale.value === 'en_US' ? 'en' : 'zh-CN'
  document.documentElement.dataset.visualTheme = theme.value
}

function applyLocale(next: SystemLanguage): void {
  locale.value = next
  setAppLocale(next)
  updateRoot()
}

function toggleLocale(): void {
  applyLocale(locale.value === 'en_US' ? 'zh_CN' : 'en_US')
}

function toggleTheme(): void {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyNetConsoleTheme(theme.value, '#0078D4', { reportDesktop: false })
  updateRoot()
  renderChart()
}

function openContextMenu(event: MouseEvent): void {
  event.preventDefault()
  const width = 240
  const height = 150
  contextMenuOpen.value = true
  requestAnimationFrame(() => {
    const left = Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8))
    const top = Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8))
    const menu = document.querySelector<HTMLElement>('[data-visual-context-menu]')
    if (menu) {
      menu.style.left = `${left}px`
      menu.style.top = `${top}px`
    }
  })
}

function renderChart(): void {
  if (!chartRefs.value.length) return
  const styles = getComputedStyle(document.documentElement)
  const text = styles.getPropertyValue('--nc-text-secondary').trim() || '#526174'
  const primary = styles.getPropertyValue('--nc-primary').trim() || '#0078D4'
  for (const element of chartRefs.value) {
    const chart = charts.get(element) ?? echarts.init(element, undefined, { renderer: 'svg' })
    charts.set(element, chart)
    chart.setOption({
      animation: false,
      grid: { top: 24, right: 16, bottom: 24, left: 42 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['08:00', '08:10', '08:20', '08:30'], axisLabel: { color: text } },
      yAxis: { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: styles.getPropertyValue('--nc-border-light').trim() || '#d9e2ef' } } },
      series: [{ type: 'line', data: [42, 58, 51, 76], smooth: true, symbol: 'circle', itemStyle: { color: primary }, lineStyle: { color: primary } }],
    })
  }
}

function handleResize(): void {
  resizeCount.value += 1
  charts.forEach((chart) => chart.resize())
}

applyLocale(initialLocale)
applyNetConsoleTheme(initialTheme, '#0078D4', { reportDesktop: false })
updateRoot()

onMounted(() => {
  resizeObserver = new ResizeObserver(handleResize)
  if (contentRef.value) resizeObserver.observe(contentRef.value)
  chartRefs.value.forEach((element) => resizeObserver?.observe(element))
  window.addEventListener('resize', handleResize)
  window.addEventListener(NETCONSOLE_THEME_CHANGE_EVENT, renderChart)
  renderChart()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener(NETCONSOLE_THEME_CHANGE_EVENT, renderChart)
  resizeObserver?.disconnect()
  charts.forEach((chart) => chart.dispose())
  charts.clear()
})
</script>

<template>
  <div class="visual-matrix-shell" :class="{ 'visual-matrix-shell--collapsed': sidebarCollapsed }" data-visual-matrix-root>
    <aside class="visual-matrix-sidebar" data-visual-sidebar>
      <div class="visual-matrix-brand">NetConsole</div>
      <div class="visual-matrix-sidebar-title">{{ labels.sidebar }}</div>
      <nav aria-label="primary navigation">
        <a v-for="page in pages" :key="page.id" :href="`#visual-${page.id}`">{{ page.title }}</a>
      </nav>
    </aside>
    <section class="visual-matrix-workspace">
      <header class="visual-matrix-header" data-visual-header>
        <div class="visual-matrix-heading">
          <span class="visual-matrix-eyebrow">P5 UI VISUAL MATRIX</span>
          <h1>{{ labels.title }}</h1>
          <p>{{ labels.description }}</p>
        </div>
        <div class="visual-matrix-actions">
          <el-button data-visual-primary-action type="primary">{{ labels.primaryAction }}</el-button>
          <el-button data-visual-secondary-action>{{ labels.secondaryAction }}</el-button>
          <el-button data-visual-locale-toggle @click="toggleLocale">{{ labels.switchLanguage }}</el-button>
          <el-button data-visual-theme-toggle @click="toggleTheme">{{ labels.switchTheme }}</el-button>
          <el-button data-sidebar-toggle text @click="sidebarCollapsed = !sidebarCollapsed">{{ sidebarCollapsed ? '→' : '←' }}</el-button>
        </div>
      </header>
      <div ref="contentRef" class="visual-matrix-content" data-visual-content @click="contextMenuOpen = false">
        <div class="visual-matrix-facts" data-visual-facts>
          <span>{{ labels.status }}</span>
          <span>{{ labels.taskSource }}</span>
          <span>{{ labels.concurrency }}</span>
          <span data-resize-count>{{ labels.resize }}: {{ resizeCount }}</span>
        </div>
        <article v-for="page in pages" :id="`visual-${page.id}`" :key="page.id" class="visual-page-card" :data-visual-page="page.id">
          <header class="visual-page-card__header">
            <div>
              <h2>{{ page.title }}</h2>
              <p>{{ page.description }}</p>
            </div>
            <el-tag type="success" effect="plain">{{ labels.status }}</el-tag>
          </header>
          <div v-if="page.id === 'devices' || page.id === 'fit-ap'" class="visual-table-frame" data-context-anchor @contextmenu="openContextMenu">
            <NcDataTable
              :data="rows"
              :columns="columns"
              :context-menu-items="contextMenuItems"
              :table-id="`visual-matrix-${page.id}`"
              :route-key="`/__visual/${page.id}`"
              height="240"
              :show-column-settings="false"
            >
              <template #cell-status="{ row }">
                <el-tag :type="row.status === 'online' ? 'success' : row.status === 'warning' ? 'warning' : 'danger'">{{ labels.status }}</el-tag>
              </template>
              <template #cell-action>
                <el-button link type="primary">{{ labels.actions[0] }}</el-button>
              </template>
            </NcDataTable>
          </div>
          <div v-else-if="page.id === 'online-mr' || page.id === 'traffic'" class="visual-chart-card">
            <h3>{{ labels.chartTitle }}</h3>
            <div ref="chartRefs" class="visual-chart" data-visual-chart :aria-label="labels.chartTitle"></div>
          </div>
          <div v-else class="visual-page-summary">
            <span>{{ labels.empty }}</span>
            <strong>{{ page.description }}</strong>
          </div>
          <footer class="visual-page-card__footer">
            <el-button data-visual-open-drawer size="small" @click.stop="drawerOpen = true">{{ labels.openDrawer }}</el-button>
            <el-button data-visual-open-dialog size="small" @click.stop="dialogOpen = true">{{ labels.openDialog }}</el-button>
          </footer>
        </article>
      </div>
    </section>
    <div v-if="contextMenuOpen" class="visual-context-menu" data-visual-context-menu role="menu" @click.stop>
      <button v-for="item in contextMenuItems" :key="item.key" type="button" role="menuitem" @click="item.action(rows[0])">{{ item.label }}</button>
    </div>
    <el-drawer v-model="drawerOpen" :title="labels.drawerTitle" direction="rtl" size="min(520px, 92vw)" data-visual-drawer>
      <div class="visual-drawer-body">
        <p>{{ labels.taskSource }}</p>
        <p>{{ labels.concurrency }}</p>
        <p>{{ labels.status }}</p>
      </div>
      <template #footer>
        <div class="visual-dialog-footer" data-visual-drawer-footer><el-button @click="drawerOpen = false">{{ labels.cancel }}</el-button><el-button type="primary" @click="drawerOpen = false">{{ labels.confirm }}</el-button></div>
      </template>
    </el-drawer>
    <el-dialog v-model="dialogOpen" :title="labels.dialogTitle" width="min(620px, calc(100vw - 32px))" data-visual-dialog>
      <p>{{ labels.description }}</p>
      <template #footer>
        <div class="visual-dialog-footer" data-visual-dialog-footer><el-button @click="dialogOpen = false">{{ labels.cancel }}</el-button><el-button type="primary" @click="dialogOpen = false">{{ labels.confirm }}</el-button></div>
      </template>
    </el-dialog>
  </div>
</template>

<style>
:root { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; color: var(--nc-text-primary); background: var(--nc-bg-page); }
* { box-sizing: border-box; }
html, body, #app { min-width: 0; min-height: 100%; margin: 0; }
body { overflow: hidden; }
.visual-matrix-shell { display: grid; grid-template-columns: var(--nc-shell-sidebar-width) minmax(0, 1fr); min-width: 0; min-height: 100vh; background: var(--nc-bg-page); }
.visual-matrix-shell--collapsed { grid-template-columns: var(--nc-shell-sidebar-collapsed-width) minmax(0, 1fr); }
.visual-matrix-sidebar { display: flex; min-width: 0; flex-direction: column; gap: var(--nc-space-3); padding: 18px 12px; overflow: hidden; background: var(--nc-bg-sidebar); border-right: 1px solid var(--nc-border); }
.visual-matrix-shell--collapsed .visual-matrix-sidebar-title, .visual-matrix-shell--collapsed .visual-matrix-sidebar nav { visibility: hidden; }
.visual-matrix-brand { color: var(--nc-primary); font-size: 18px; font-weight: 800; white-space: nowrap; }
.visual-matrix-sidebar-title { color: var(--nc-text-secondary); font-size: 12px; font-weight: 700; white-space: nowrap; }
.visual-matrix-sidebar nav { display: grid; gap: 4px; }
.visual-matrix-sidebar a { min-width: 0; padding: 8px 10px; overflow: hidden; color: var(--nc-text-primary); border-radius: 6px; text-decoration: none; text-overflow: ellipsis; white-space: nowrap; }
.visual-matrix-sidebar a:hover { background: var(--nc-table-hover-bg); }
.visual-matrix-workspace { display: flex; min-width: 0; min-height: 100vh; flex-direction: column; }
.visual-matrix-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--nc-space-4); min-width: 0; padding: 20px 24px 14px; background: var(--nc-bg-card); border-bottom: 1px solid var(--nc-border); }
.visual-matrix-heading { min-width: 0; }
.visual-matrix-eyebrow { color: var(--nc-primary); font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.visual-matrix-heading h1 { margin: 4px 0; color: var(--nc-text-primary); font-size: clamp(20px, 2vw, 28px); line-height: 1.25; }
.visual-matrix-heading p { max-width: 760px; margin: 0; color: var(--nc-text-secondary); }
.visual-matrix-actions { display: flex; flex: none; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.visual-matrix-content { display: grid; min-width: 0; min-height: 0; flex: 1; gap: 14px; padding: 18px 24px 30px; overflow: auto; }
.visual-matrix-facts { display: flex; min-width: 0; flex-wrap: wrap; gap: 8px; }
.visual-matrix-facts span { min-width: 0; padding: 7px 10px; overflow: hidden; background: var(--nc-surface-muted); border: 1px solid var(--nc-border-light); border-radius: 6px; color: var(--nc-text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.visual-page-card { display: grid; min-width: 0; gap: 12px; padding: 16px; overflow: hidden; background: var(--nc-bg-card); border: 1px solid var(--nc-border); border-radius: 8px; }
.visual-page-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; min-width: 0; }
.visual-page-card__header > div { min-width: 0; }
.visual-page-card h2 { margin: 0; color: var(--nc-text-primary); font-size: 17px; }
.visual-page-card p { margin: 4px 0 0; color: var(--nc-text-secondary); font-size: 13px; }
.visual-table-frame { min-width: 0; overflow: hidden; }
.visual-table-frame .nc-data-table { min-height: 240px; background: var(--nc-bg-card); }
.visual-chart-card { min-width: 0; padding: 12px; background: var(--nc-surface-muted); border-radius: 6px; }
.visual-chart-card h3 { margin: 0 0 8px; color: var(--nc-text-primary); font-size: 14px; }
.visual-chart { width: 100%; min-width: 0; height: 190px; }
.visual-page-summary { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12px; min-height: 92px; padding: 16px; background: var(--nc-surface-muted); border-radius: 6px; }
.visual-page-summary span { flex: none; color: var(--nc-text-secondary); }
.visual-page-summary strong { min-width: 0; color: var(--nc-text-primary); font-size: 13px; text-align: right; }
.visual-page-card__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding-top: 4px; }
.visual-context-menu { position: fixed; z-index: 5000; display: grid; min-width: min(240px, calc(100vw - 16px)); max-width: calc(100vw - 16px); max-height: calc(100vh - 16px); gap: 4px; padding: 6px; overflow: auto; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 8px; box-shadow: var(--el-box-shadow-light); }
.visual-context-menu button { min-width: 0; padding: 8px 10px; overflow: hidden; background: transparent; border: 0; border-radius: 5px; color: var(--nc-text-primary); text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.visual-context-menu button:hover { background: var(--nc-table-hover-bg); }
.visual-drawer-body { display: grid; gap: 12px; }
.visual-dialog-footer { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 1100px) { .visual-matrix-header { align-items: stretch; flex-direction: column; } .visual-matrix-actions { justify-content: flex-start; } }
@media (max-width: 850px) { .visual-matrix-shell, .visual-matrix-shell--collapsed { grid-template-columns: 1fr; } .visual-matrix-sidebar { display: none; } .visual-matrix-header, .visual-matrix-content { padding-inline: 12px; } .visual-page-summary { align-items: flex-start; flex-direction: column; } .visual-page-summary strong { text-align: left; } }
</style>
