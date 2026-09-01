import type { BrowserWindow } from 'electron'
import { randomBytes } from 'node:crypto'

import { resolveDesktopBackgroundColor } from './config'

export interface ShutdownProgressPageOptions {
  window: BrowserWindow
  isDark: () => boolean
}

const SHUTDOWN_STAGE_PERCENT: Record<string, number> = {
  shutdown_started: 10,
  blocking_new_work: 30,
  draining_downloads: 40,
  stopping_backend: 45,
  draining_tasks: 55,
  persistence_draining: 70,
  backend_stopped: 95,
  finalizing_windows: 98,
  shutdown_incomplete: 0,
  complete: 100,
}

const SHUTDOWN_STAGE_LABEL: Record<string, string> = {
  shutdown_started: '正在准备安全退出',
  blocking_new_work: '正在停止新的后台任务',
  draining_downloads: '正在结束文件保存',
  stopping_backend: '正在停止本地核心服务',
  draining_tasks: '正在安全停止后台任务',
  persistence_draining: '正在完成本地数据保存',
  backend_stopped: '本地核心服务已停止',
  finalizing_windows: '正在完成退出',
  shutdown_incomplete: '退出过程中部分后台服务未及时结束',
  complete: '退出完成',
}

export function shutdownStagePercent(stage: string): number {
  return SHUTDOWN_STAGE_PERCENT[String(stage || '').trim()] ?? 0
}

export class ShutdownProgressPage {
  private loaded = false
  private disposed = false
  private stage = 'shutdown_started'
  private stageLabel = SHUTDOWN_STAGE_LABEL.shutdown_started
  private percent = shutdownStagePercent(this.stage)

  constructor(private readonly options: ShutdownProgressPageOptions) {}

  async load(): Promise<void> {
    if (this.disposed || this.options.window.isDestroyed()) return
    const theme = this.options.isDark() ? 'dark' : 'light'
    const background = resolveDesktopBackgroundColor(theme)
    const panel = theme === 'dark' ? '#18212d' : '#ffffff'
    const text = theme === 'dark' ? '#f2f4f7' : '#182230'
    const muted = theme === 'dark' ? '#98a2b3' : '#667085'
    const border = theme === 'dark' ? '#344054' : '#e4e7ec'
    const nonce = randomBytes(18).toString('base64')
    const window = this.options.window
    window.setBackgroundColor(background)
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'"><title>正在安全退出 NetConsole</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:${background};color:${text};font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid ${border};border-radius:8px;background:${panel};text-align:center}h1{font-size:22px;margin:0 0 10px}.brand{font-size:16px;font-weight:600;margin:0 0 26px}.spinner{width:28px;height:28px;margin:0 auto 20px;border:3px solid ${border};border-top-color:#0078d4;border-radius:50%;animation:spin 1s linear infinite}.stage{min-height:28px;font-size:16px}.percent{min-height:24px;color:${muted};line-height:1.6;margin-top:8px}.bar{height:4px;margin:22px 0 18px;overflow:hidden;background:${border};border-radius:2px}.bar-fill{width:${this.percent}%;height:100%;background:#0078d4;transition:none}@keyframes spin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.spinner{animation:none}}</style></head><body><main><p class="brand">NetConsole</p><h1>正在安全退出 NetConsole</h1><div class="spinner" aria-hidden="true"></div><div id="stage" class="stage">${this.stageLabel}</div><div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${this.percent}"><div id="bar-fill" class="bar-fill"></div></div><div id="percent" class="percent" aria-live="polite">${this.percent}%</div></main><script nonce="${nonce}">window.netconsoleShutdown={setStage(value,percent){document.getElementById('stage').textContent=value;document.getElementById('bar-fill').style.width=String(percent)+'%';document.getElementById('percent').textContent=String(percent)+'%';document.querySelector('.bar').setAttribute('aria-valuenow',String(percent))},dispose(){}};window.addEventListener('beforeunload',()=>window.netconsoleShutdown.dispose(),{once:true});</script></body></html>`
    try {
      await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
      this.loaded = true
      this.update(this.stage, this.stageLabel)
    } catch {
      // The native window remains available for the final cleanup path.
    }
  }

  update(stage: string, label?: string): void {
    this.stage = String(stage || '').trim() || this.stage
    this.stageLabel = String(label || SHUTDOWN_STAGE_LABEL[this.stage] || this.stageLabel).trim() || this.stageLabel
    this.percent = Math.max(this.percent, shutdownStagePercent(this.stage))
    if (!this.loaded || this.disposed || this.options.window.isDestroyed()) return
    const encoded = JSON.stringify(this.stageLabel)
    const encodedPercent = JSON.stringify(this.percent)
    void this.options.window.webContents.executeJavaScript(
      `window.netconsoleShutdown && window.netconsoleShutdown.setStage(${encoded},${encodedPercent})`,
      true,
    ).catch(() => undefined)
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
  }
}
