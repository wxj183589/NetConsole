import type { BrowserWindow } from 'electron'
import { randomBytes } from 'node:crypto'

import { resolveDesktopBackgroundColor } from './config'

export interface StartupProgressPageOptions {
  window: BrowserWindow
  isDark: () => boolean
}

export class StartupProgressPage {
  private loaded = false
  private disposed = false

  constructor(private readonly options: StartupProgressPageOptions) {}

  async load(): Promise<void> {
    const theme = this.options.isDark() ? 'dark' : 'light'
    const background = resolveDesktopBackgroundColor(theme)
    const panel = theme === 'dark' ? '#18212d' : '#ffffff'
    const text = theme === 'dark' ? '#f2f4f7' : '#182230'
    const muted = theme === 'dark' ? '#98a2b3' : '#667085'
    const border = theme === 'dark' ? '#344054' : '#e4e7ec'
    const nonce = randomBytes(18).toString('base64')
    const window = this.options.window
    window.setBackgroundColor(background)
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'"><title>正在启动 NetConsole</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:${background};color:${text};font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid ${border};border-radius:8px;background:${panel};text-align:center}h1{font-size:22px;margin:0 0 10px}.brand{font-size:16px;font-weight:600;margin:0 0 26px}.spinner{width:28px;height:28px;margin:0 auto 20px;border:3px solid ${border};border-top-color:#0078d4;border-radius:50%;animation:spin 1s linear infinite}.stage{min-height:28px;font-size:16px}.percent{min-height:24px;color:${muted};line-height:1.6;margin-top:8px}.bar{height:4px;margin:22px 0 18px;overflow:hidden;background:${border};border-radius:2px}.bar-fill{width:8%;height:100%;background:#0078d4;transition:none}@keyframes spin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.spinner{animation:none}}</style></head><body><main><p class="brand">NetConsole</p><h1>正在启动 NetConsole</h1><div class="spinner" aria-hidden="true"></div><div id="stage" class="stage">正在准备桌面环境</div><div class="bar" aria-hidden="true"><div id="bar-fill" class="bar-fill"></div></div><div id="percent" class="percent" aria-live="polite">8%</div></main><script nonce="${nonce}">window.netconsoleStartup={setStage(value,percent){document.getElementById('stage').textContent=value;document.getElementById('bar-fill').style.width=String(percent)+'%';document.getElementById('percent').textContent=String(percent)+'%';document.querySelector('.bar').setAttribute('aria-valuenow',String(percent))},dispose(){}};document.querySelector('.bar').setAttribute('role','progressbar');document.querySelector('.bar').setAttribute('aria-valuemin','0');document.querySelector('.bar').setAttribute('aria-valuemax','100');window.addEventListener('beforeunload',()=>window.netconsoleStartup.dispose(),{once:true});</script></body></html>`
    await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
    this.loaded = true
  }

  update(stage: string): void {
    if (!this.loaded || this.disposed || this.options.window.isDestroyed()) return
    const encoded = JSON.stringify(stage)
    const percent = startupStagePercent(stage)
    const encodedPercent = JSON.stringify(percent)
    void this.options.window.webContents.executeJavaScript(
      `window.netconsoleStartup && window.netconsoleStartup.setStage(${encoded},${encodedPercent})`,
      true,
    ).catch(() => undefined)
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
  }
}

export function startupStagePercent(stage: string): number {
  const normalized = String(stage || '').trim()
  if (['ready', 'renderer.ready', 'desktop.interactive'].includes(normalized)) return 100
  if (['loading_workspace', 'renderer.navigation_started', 'renderer.dom_ready'].includes(normalized)) return 78
  if (['backend_ready', 'backend.health_ready', 'backend.handshake_received', 'listener_ready'].includes(normalized)) return 55
  if (['backend_starting', 'backend.spawn_started', 'application_building', 'application_built'].includes(normalized)) return 30
  if (['waiting_backend', 'electron.app_ready', 'paths_resolved', 'paths_resolving', 'instance_lock_acquired', 'instance_lock_acquiring', 'storage_manifest_preparing', 'storage_manifest_ready', 'upgrade_recovery_complete', 'upgrade_recovery_started', 'active_site_resolving', 'active_site_resolved', 'application_services_initializing', 'active_site_database_ready', 'active_site_database_initializing', 'ap_identity_index_ready', 'ap_identity_index_initializing', 'routers_registered'].includes(normalized)) return 15
  return 8
}

export function startupStageLabel(stage: string): string {
  return ({
    'electron.app_ready': '正在准备桌面环境',
    'backend.spawn_started': '正在启动本地核心服务',
    paths_resolved: '正在准备数据环境',
    paths_resolving: '正在准备数据环境',
    instance_lock_acquired: '正在检查运行状态',
    instance_lock_acquiring: '正在检查运行状态',
    storage_manifest_preparing: '正在检查数据兼容性',
    storage_manifest_ready: '正在检查数据兼容性',
    listener_binding: '正在建立本地服务监听',
    application_building: '正在初始化核心服务',
    upgrade_recovery_complete: '正在恢复未完成操作',
    upgrade_recovery_started: '正在恢复未完成操作',
    active_site_resolving: '正在读取当前局点',
    active_site_resolved: '正在读取当前局点',
    application_services_initializing: '正在配置本地服务',
    active_site_database_ready: '正在读取当前局点',
    active_site_database_initializing: '正在读取当前局点',
    ap_identity_index_ready: '正在初始化本地索引',
    ap_identity_index_initializing: '正在初始化本地索引',
    routers_registered: '正在配置本地服务',
    listener_ready: '本地核心服务已启动',
    application_built: '正在初始化核心服务',
    'backend.handshake_received': '正在建立本地服务连接',
    'backend.health_ready': '本地服务已就绪',
    'renderer.navigation_started': '正在加载工作界面',
    'renderer.dom_ready': '正在准备界面组件',
  } as Record<string, string>)[stage] ?? '正在初始化本地核心服务'
}
