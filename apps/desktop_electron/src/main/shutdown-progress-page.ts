import type { BrowserWindow } from 'electron'
import { randomBytes } from 'node:crypto'

import { resolveDesktopBackgroundColor } from './config'

export interface ShutdownProgressPageOptions {
  window: BrowserWindow
  isDark: () => boolean
}

export class ShutdownProgressPage {
  private loaded = false
  private disposed = false
  private stage = '正在停止新的后台任务'

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
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'"><title>正在安全退出 NetConsole</title><style>body{display:grid;place-items:center;min-height:100vh;margin:0;background:${background};color:${text};font-family:Segoe UI,Microsoft YaHei,sans-serif}main{width:min(520px,calc(100vw - 48px));padding:36px;border:1px solid ${border};border-radius:8px;background:${panel};text-align:center}h1{font-size:22px;margin:0 0 10px}.brand{font-size:16px;font-weight:600;margin:0 0 26px}.spinner{width:28px;height:28px;margin:0 auto 20px;border:3px solid ${border};border-top-color:#0078d4;border-radius:50%;animation:spin 1s linear infinite}.stage{min-height:28px;font-size:16px}.elapsed{min-height:24px;color:${muted};line-height:1.6;margin-top:8px}.bar{height:4px;margin:22px 0 18px;overflow:hidden;background:${border};border-radius:2px}.bar::after{display:block;width:38%;height:100%;background:#0078d4;content:'';animation:slide 1.5s ease-in-out infinite}@keyframes spin{to{transform:rotate(360deg)}}@keyframes slide{0%{transform:translateX(-110%)}100%{transform:translateX(290%)}}@media (prefers-reduced-motion:reduce){.spinner,.bar::after{animation:none}.bar::after{transform:translateX(80%)}}</style></head><body><main><p class="brand">NetConsole</p><h1>正在安全退出 NetConsole</h1><div class="spinner" aria-hidden="true"></div><div id="stage" class="stage">${this.stage}</div><div class="bar" aria-hidden="true"></div><div id="elapsed" class="elapsed">已等待 0 秒</div></main><script nonce="${nonce}">const started=Date.now();function tick(){document.getElementById('elapsed').textContent='已等待 '+Math.floor((Date.now()-started)/1000)+' 秒'}window.netconsoleShutdown={setStage(value){document.getElementById('stage').textContent=value}};const timer=setInterval(tick,1000);window.addEventListener('beforeunload',()=>clearInterval(timer));tick();</script></body></html>`
    try {
      await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
      this.loaded = true
      this.update(this.stage)
    } catch {
      // The native window remains available for the final cleanup path.
    }
  }

  update(stage: string): void {
    this.stage = stage
    if (!this.loaded || this.disposed || this.options.window.isDestroyed()) return
    const encoded = JSON.stringify(stage)
    void this.options.window.webContents.executeJavaScript(
      `window.netconsoleShutdown && window.netconsoleShutdown.setStage(${encoded})`,
      true,
    ).catch(() => undefined)
  }

  dispose(): void {
    this.disposed = true
  }
}
