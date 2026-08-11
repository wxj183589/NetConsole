// @vitest-environment happy-dom

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { nextTick } from 'vue'
import { ElNotification } from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'

const notificationCss = readFileSync(
  resolve(process.cwd(), 'node_modules/element-plus/theme-chalk/el-notification.css'),
  'utf8',
)

describe('task notification layout', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    document.head.innerHTML = ''
  })

  it('mounts to body as a fixed overlay instead of entering the page flow', async () => {
    const page = document.createElement('main')
    page.style.width = '640px'
    page.style.height = '480px'
    document.body.append(page)
    const style = document.createElement('style')
    style.textContent = notificationCss
    document.head.append(style)
    const beforeHeight = document.documentElement.scrollHeight

    const notification = ElNotification({
      title: '任务失败',
      message: '没有可用于重建的原始 MESH 日志',
      duration: 0,
      customClass: 'nc-task-notification',
      appendTo: document.body,
      position: 'top-right',
    })
    await nextTick()

    const element = document.querySelector<HTMLElement>('.el-notification.nc-task-notification')
    expect(element).not.toBeNull()
    expect(element?.parentElement).toBe(document.body)
    expect(notificationCss).toMatch(/\.el-notification\{[^}]*position:fixed/)
    expect(document.documentElement.scrollHeight).toBe(beforeHeight)
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth)
    notification.close()
  })
})
