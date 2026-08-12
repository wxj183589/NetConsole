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
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'"><title>正在启动 NetConsole</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:${background};color:${text};font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid ${border};border-radius:8px;background:${panel};text-align:center}h1{font-size:22px;margin:0 0 10px}.brand{font-size:16px;font-weight:600;margin:0 0 26px}.spinner{width:28px;height:28px;margin:0 auto 20px;border:3px solid ${border};border-top-color:#0078d4;border-radius:50%;animation:spin 1s linear infinite}.stage{min-height:28px;font-size:16px}.hint,.elapsed{min-height:24px;color:${muted};line-height:1.6;margin-top:8px}.bar{height:4px;margin:22px 0 18px;overflow:hidden;background:${border};border-radius:2px}.bar::after{display:block;width:38%;height:100%;background:#0078d4;content:'';animation:slide 1.5s ease-in-out infinite}@keyframes spin{to{transform:rotate(360deg)}}@keyframes slide{0%{transform:translateX(-110%)}100%{transform:translateX(290%)}}@media (prefers-reduced-motion:reduce){.spinner{animation:none}.bar::after{animation:none;transform:translateX(80%)}}</style></head><body><main><p class="brand">NetConsole</p><h1>正在启动 NetConsole</h1><div class="spinner" aria-hidden="true"></div><div id="stage" class="stage">正在准备桌面环境</div><div class="bar" aria-hidden="true"></div><div id="elapsed" class="elapsed">已用时 0 秒</div><div id="hint" class="hint">正在启动本地核心服务</div></main><script nonce="${nonce}">const started=Date.now();function hint(s){if(s>=40)return'启动时间较长，程序仍在继续处理。';if(s>=20)return'正在处理本地数据，请勿关闭 NetConsole。';if(s>=10)return'大型局点启动可能需要更多时间。';return'正在启动本地核心服务';}function tick(){const s=Math.floor((Date.now()-started)/1000);document.getElementById('elapsed').textContent='已用时 '+s+' 秒';document.getElementById('hint').textContent=hint(s)}window.netconsoleStartup={setStage(value){document.getElementById('stage').textContent=value}};const timer=setInterval(tick,1000);window.addEventListener('beforeunload',()=>clearInterval(timer));tick();</script></body></html>`
    await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
    this.loaded = true
  }

  update(stage: string): void {
    if (!this.loaded || this.disposed || this.options.window.isDestroyed()) return
    const encoded = JSON.stringify(stage)
    void this.options.window.webContents.executeJavaScript(
      `window.netconsoleStartup && window.netconsoleStartup.setStage(${encoded})`,
      true,
    ).catch(() => undefined)
  }

  dispose(): void {
    this.disposed = true
  }
}

export function startupStageLabel(stage: string): string {
  return ({
    'electron.app_ready': '正在准备桌面环境',
    'backend.spawn_started': '正在启动本地核心服务',
    paths_resolved: '正在准备数据环境',
    instance_lock_acquired: '正在检查运行状态',
    storage_manifest_ready: '正在检查数据兼容性',
    upgrade_recovery_complete: '正在恢复未完成操作',
    active_site_database_ready: '正在读取当前局点',
    ap_identity_index_ready: '正在初始化本地索引',
    routers_registered: '正在配置本地服务',
    listener_ready: '本地核心服务已启动',
    application_built: '正在初始化核心服务',
    'backend.handshake_received': '正在建立本地服务连接',
    'backend.health_ready': '本地服务已就绪',
    'renderer.navigation_started': '正在加载工作界面',
    'renderer.dom_ready': '正在准备界面组件',
  } as Record<string, string>)[stage] ?? '正在初始化本地核心服务'
}
