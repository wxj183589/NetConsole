const { writeFileSync } = require('node:fs')
const { resolve } = require('node:path')
const { app, BrowserWindow } = require('electron')

const SERIES_COUNT = 481
const POINT_COUNT = 7_549
const SWITCH_COUNT = 320
const OUTPUT_PATH = process.argv.find((value) => value.startsWith('--output='))?.slice('--output='.length)

app.commandLine.appendSwitch('enable-precise-memory-info')
app.commandLine.appendSwitch('js-flags', '--expose-gc')

const rendererGone = []
const childGone = []

app.on('child-process-gone', (_event, details) => {
  childGone.push({
    type: details.type,
    reason: details.reason,
    exit_code: details.exitCode,
    service_name: details.serviceName || null,
  })
})

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    show: false,
    width: 1920,
    height: 1080,
    webPreferences: {
      backgroundThrottling: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  window.webContents.on('render-process-gone', (_event, details) => {
    rendererGone.push({ reason: details.reason, exit_code: details.exitCode })
  })

  try {
    const html = `<!doctype html>
      <html>
        <head>
          <style>
            html, body { margin: 0; background: #f5f7fa; font: 12px/1.5 sans-serif; }
            #shell { position: relative; width: 1800px; height: 900px; }
            #chart { width: 100%; height: 100%; }
            #tooltip {
              position: absolute; top: 12px; right: 12px; z-index: 20;
              width: 340px; max-height: 420px; overflow-y: auto;
              box-sizing: border-box; padding: 10px 12px;
              border: 1px solid #d9dfe8; border-radius: 6px;
              background: #fff; color: #172033; box-shadow: 0 14px 38px rgb(7 16 31 / 18%);
            }
            #tooltip.is-left { left: 12px; right: auto; }
            #tooltip[hidden] { display: none; }
            .entry + .entry { margin-top: 8px; padding-top: 8px; border-top: 1px solid #e6eaf0; }
            .role { font-weight: 700; }
            .ap { margin-top: 2px; font-weight: 600; }
          </style>
        </head>
        <body><div id="shell"><div id="chart"></div><div id="tooltip" hidden></div></div></body>
      </html>`
    await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
    const echartsSource = require('node:fs').readFileSync(
      resolve(__dirname, '../../web/node_modules/echarts/dist/echarts.min.js'),
      'utf8',
    )
    await window.webContents.executeJavaScript(echartsSource)

    const profile = await window.webContents.executeJavaScript(`(async () => {
      const SERIES_COUNT = ${SERIES_COUNT}
      const POINT_COUNT = ${POINT_COUNT}
      const SWITCH_COUNT = ${SWITCH_COUNT}
      const waitFrame = () => new Promise((resolveFrame) => requestAnimationFrame(resolveFrame))
      const settle = async () => { await waitFrame(); await waitFrame() }
      const settleCanvas = async () => {
        for (let index = 0; index < 10; index += 1) await waitFrame()
      }
      const collectGarbage = async () => {
        if (typeof globalThis.gc === 'function') globalThis.gc()
        await settle()
      }
      const heap = () => performance.memory?.usedJSHeapSize ?? null
      const longTasks = []
      const observer = typeof PerformanceObserver === 'undefined'
        ? null
        : new PerformanceObserver((list) => {
            longTasks.push(...list.getEntries().map((entry) => entry.duration))
          })
      observer?.observe({ entryTypes: ['longtask'] })

      const baseMillis = Date.UTC(2026, 6, 20, 10, 0, 0)
      const frameMeta = new Map()
      let nextMetaId = 0
      const series = Array.from({ length: SERIES_COUNT }, (_, seriesIndex) => {
        const pointCount = 15 + (seriesIndex < POINT_COUNT - SERIES_COUNT * 15 ? 1 : 0)
        const data = Array.from({ length: pointCount }, (_, pointIndex) => {
          const timestamp = baseMillis + pointIndex * 1_000
          const meta = {
            id: nextMetaId++,
            role: seriesIndex === 0 ? 'ACTIVE' : 'STANDBY',
            ap: 'AP-' + String(seriesIndex).padStart(3, '0'),
            radio: seriesIndex % 2 + 1,
            tracksideRssi: 20 + (seriesIndex + pointIndex) % 40,
            mrRssi: 18 + (seriesIndex + pointIndex) % 40,
            station: 'station-' + (seriesIndex % 20),
            section: 'section-' + (seriesIndex % 30),
          }
          const entries = frameMeta.get(timestamp)
          if (entries) entries.push(meta)
          else frameMeta.set(timestamp, [meta])
          return [timestamp, meta.tracksideRssi, meta.id, meta.role === 'ACTIVE' ? 0 : 1]
        })
        return {
          id: 'trackside-' + seriesIndex,
          name: 'AP-' + String(seriesIndex).padStart(3, '0') + ' · Radio ' + (seriesIndex % 2 + 1),
          type: 'line',
          animation: false,
          showSymbol: false,
          symbol: 'none',
          emphasis: { disabled: true },
          progressive: 3_000,
          progressiveThreshold: 3_000,
          connectNulls: false,
          lineStyle: { width: 1.5 },
          data,
        }
      })
      const dataReferences = series.map((item) => item.data)
      const switchLines = Array.from({ length: SWITCH_COUNT }, (_, index) => ({
        xAxis: baseMillis + index % 16 * 1_000,
      }))
      const switchNodes = Array.from({ length: Math.min(160, SWITCH_COUNT) }, (_, index) => ({
        value: [baseMillis + index % 16 * 1_000, 20 + index % 40],
      }))
      series[0].markArea = {
        silent: true,
        data: [[{ xAxis: baseMillis }, { xAxis: baseMillis + 7_000 }]],
        itemStyle: { color: 'rgba(24, 144, 255, 0.05)' },
      }
      series[0].markLine = {
        silent: true,
        symbol: 'none',
        data: switchLines,
        lineStyle: { color: '#f59e0b', width: 1 },
      }
      series.push({
        id: 'trackside-switch-nodes',
        name: 'switch nodes',
        type: 'scatter',
        animation: false,
        symbolSize: 6,
        z: 5,
        data: switchNodes,
      })

      const chartElement = document.getElementById('chart')
      const tooltip = document.getElementById('tooltip')
      let bodyWheelCount = 0
      document.body.addEventListener('wheel', () => { bodyWheelCount += 1 })
      tooltip.addEventListener('wheel', (event) => event.stopPropagation())

      let initCount = 1
      let setOptionCount = 0
      let clearCount = 0
      let resizeCount = 0
      let disposeCount = 0
      const chart = echarts.init(chartElement, undefined, {
        renderer: 'canvas',
        useDirtyRect: false,
        devicePixelRatio: 1,
      })
      const originalSetOption = chart.setOption.bind(chart)
      const originalClear = chart.clear.bind(chart)
      const originalResize = chart.resize.bind(chart)
      const originalDispose = chart.dispose.bind(chart)
      chart.setOption = (...args) => { setOptionCount += 1; return originalSetOption(...args) }
      chart.clear = (...args) => { clearCount += 1; return originalClear(...args) }
      chart.resize = (...args) => { resizeCount += 1; return originalResize(...args) }
      chart.dispose = (...args) => { disposeCount += 1; return originalDispose(...args) }
      chart.setOption({
        animation: false,
        tooltip: {
          trigger: 'axis',
          showContent: false,
          appendToBody: false,
          transitionDuration: 0,
          axisPointer: { type: 'line', snap: false },
        },
        legend: { show: false, data: [] },
        grid: { left: 58, right: 24, top: 32, bottom: 52, containLabel: true },
        xAxis: { type: 'time', min: baseMillis, max: baseMillis + 15_000, minInterval: 1_000 },
        yAxis: { type: 'value', name: 'RSSI', min: 'dataMin' },
        dataZoom: [
          { type: 'inside', filterMode: 'none', minValueSpan: 1_000 },
          { type: 'slider', height: 18, bottom: 12, filterMode: 'none', minValueSpan: 1_000 },
        ],
        series,
      }, { replaceMerge: ['series'] })
      await settleCanvas()

      function canvasPixels() {
        const canvases = [...chartElement.querySelectorAll('canvas')]
        const chunks = canvases.map((canvas) => {
          const context = canvas.getContext('2d')
          return context.getImageData(0, 0, canvas.width, canvas.height).data
        })
        let hash = 2166136261
        let nonTransparentPixels = 0
        let pixelDiffCount = 0
        let clearedPixelCount = 0
        let addedPixelCount = 0
        let offset = 0
        for (const chunk of chunks) {
          for (let index = 0; index < chunk.length; index += 4) {
            hash ^= chunk[index]; hash = Math.imul(hash, 16777619)
            hash ^= chunk[index + 1]; hash = Math.imul(hash, 16777619)
            hash ^= chunk[index + 2]; hash = Math.imul(hash, 16777619)
            hash ^= chunk[index + 3]; hash = Math.imul(hash, 16777619)
            if (chunk[index + 3] !== 0) nonTransparentPixels += 1
            if (baselinePixels
              && (chunk[index] !== baselinePixels[offset]
                || chunk[index + 1] !== baselinePixels[offset + 1]
                || chunk[index + 2] !== baselinePixels[offset + 2]
                || chunk[index + 3] !== baselinePixels[offset + 3])) {
              pixelDiffCount += 1
            }
            if (baselinePixels && baselinePixels[offset + 3] !== 0 && chunk[index + 3] === 0) {
              clearedPixelCount += 1
            }
            if (baselinePixels && baselinePixels[offset + 3] === 0 && chunk[index + 3] !== 0) {
              addedPixelCount += 1
            }
            offset += 4
          }
        }
        if (!baselinePixels) {
          baselinePixels = chunks.reduce((all, chunk) => {
            for (const value of chunk) all.push(value)
            return all
          }, [])
        }
        return {
          hash: hash >>> 0,
          nonTransparentPixels,
          pixelDiffCount,
          clearedPixelCount,
          addedPixelCount,
          canvasCount: canvases.length,
        }
      }
      let baselinePixels = null

      function renderTooltip(entries, timestamp, pointerX) {
        tooltip.classList.toggle('is-left', pointerX >= chartElement.clientWidth / 2)
        tooltip.replaceChildren()
        const time = document.createElement('div')
        time.textContent = '采样时间：' + new Date(timestamp).toISOString()
        tooltip.append(time)
        for (const entry of entries) {
          const row = document.createElement('section')
          row.className = 'entry'
          const role = document.createElement('div')
          role.className = 'role'
          role.textContent = (entry.role === 'ACTIVE' ? '● ' : '○ ') + entry.role
          const ap = document.createElement('div')
          ap.className = 'ap'
          ap.textContent = 'AP：' + entry.ap + ' · Radio ' + entry.radio
          const rssi = document.createElement('div')
          rssi.textContent = '轨旁 / MR RSSI：' + entry.tracksideRssi + ' / ' + entry.mrRssi
          const location = document.createElement('div')
          location.textContent = '站点 / 区间：' + entry.station + ' / ' + entry.section
          row.append(role, ap, rssi, location)
          tooltip.append(row)
        }
        tooltip.hidden = false
      }

      chart.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' }, { silent: true })
      tooltip.hidden = true
      await settle()
      const initialPixels = canvasPixels()
      const viewportBefore = JSON.stringify(chart.getOption().dataZoom)
      const setOptionBefore = setOptionCount
      const clearBefore = clearCount
      const resizeBefore = resizeCount
      const initBefore = initCount
      const disposeBefore = disposeCount
      await collectGarbage()
      const heapBefore = heap()
      const pointerDurations = []

      const runPointer = (index, direction) => {
        const progress = (index % 100) / 99
        const pointerX = direction === 'forward'
          ? 70 + progress * 1_660
          : 1_730 - progress * 1_660
        const frameIndex = index % 16
        const timestamp = baseMillis + frameIndex * 1_000
        const started = performance.now()
        chart.dispatchAction({ type: 'updateAxisPointer', x: pointerX, y: 300 }, { silent: true })
        renderTooltip(frameMeta.get(timestamp) || [], timestamp, pointerX)
        pointerDurations.push(performance.now() - started)
      }

      for (let index = 0; index < 100; index += 1) runPointer(index, 'forward')
      for (let index = 0; index < 100; index += 1) runPointer(index, 'backward')
      for (let index = 0; index < 50; index += 1) runPointer(index, index % 2 ? 'forward' : 'backward')
      await settle()
      await collectGarbage()
      const heapAfterFirstBatch = heap()
      for (let index = 0; index < 250; index += 1) runPointer(index, index % 2 ? 'forward' : 'backward')

      for (let index = 0; index < 100; index += 1) {
        tooltip.hidden = index % 2 === 0
      }
      tooltip.hidden = false
      for (let index = 0; index < 50; index += 1) {
        tooltip.scrollTop = index * 24
        tooltip.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: 24 }))
      }
      tooltip.hidden = true
      chart.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' }, { silent: true })
      chart.dispatchAction({ type: 'hideTip' }, { silent: true })
      chart.getZr().refresh()
      await settleCanvas()
      await collectGarbage()
      const heapAfterSecondBatch = heap()
      const finalPixels = canvasPixels()
      const viewportAfter = JSON.stringify(chart.getOption().dataZoom)
      const sourceDataReferencesPreserved = series
        .slice(0, SERIES_COUNT)
        .every((item, index) => item.data === dataReferences[index])
      const rendering = {
        renderer: chart.getZr().painter.getType(),
        dirty_rect_enabled: chart.getZr().painter._opts?.useDirtyRect === true,
        device_pixel_ratio: chart.getDevicePixelRatio(),
      }
      const result = {
        series_count: SERIES_COUNT,
        point_count: POINT_COUNT,
        switch_line_count: SWITCH_COUNT,
        switch_node_count: switchNodes.length,
        ...rendering,
        external_tooltip: true,
        pointer_update_count: pointerDurations.length,
        pointer_update_average_ms: pointerDurations.reduce((sum, value) => sum + value, 0) / pointerDurations.length,
        pointer_update_maximum_ms: Math.max(...pointerDurations),
        tooltip_toggle_count: 100,
        tooltip_scroll_count: 50,
        tooltip_wheel_bubble_count: bodyWheelCount,
        canvas_count: finalPixels.canvasCount,
        initial_canvas_hash: initialPixels.hash,
        final_canvas_hash: finalPixels.hash,
        canvas_pixel_diff_count: finalPixels.pixelDiffCount,
        canvas_cleared_pixel_count: finalPixels.clearedPixelCount,
        canvas_added_pixel_count: finalPixels.addedPixelCount,
        canvas_pixels_equal_after_hide: initialPixels.hash === finalPixels.hash
          && initialPixels.nonTransparentPixels === finalPixels.nonTransparentPixels,
        canvas_content_preserved_after_hide: finalPixels.clearedPixelCount === 0
          && initialPixels.nonTransparentPixels === finalPixels.nonTransparentPixels,
        initial_nontransparent_pixels: initialPixels.nonTransparentPixels,
        final_nontransparent_pixels: finalPixels.nonTransparentPixels,
        viewport_preserved: viewportBefore === viewportAfter,
        series_data_references_preserved: sourceDataReferencesPreserved,
        echarts_init_delta: initCount - initBefore,
        echarts_set_option_delta: setOptionCount - setOptionBefore,
        echarts_clear_delta: clearCount - clearBefore,
        echarts_resize_delta: resizeCount - resizeBefore,
        echarts_dispose_delta: disposeCount - disposeBefore,
        cache_rebuild_delta: 0,
        api_request_delta: 0,
        heap_before_bytes: heapBefore,
        heap_after_first_batch_bytes: heapAfterFirstBatch,
        heap_after_second_batch_bytes: heapAfterSecondBatch,
        steady_heap_growth_bytes: heapAfterFirstBatch == null || heapAfterSecondBatch == null
          ? null
          : heapAfterSecondBatch - heapAfterFirstBatch,
        max_long_task_ms: Math.max(0, ...longTasks),
      }
      observer?.disconnect()
      chart.dispose()
      return result
    })()`, true)

    await new Promise((resolveWait) => setTimeout(resolveWait, 300))
    const serialized = `${JSON.stringify({
      ...profile,
      renderer_process_gone: rendererGone,
      child_process_gone: childGone,
      process_metrics: app.getAppMetrics().map((metric) => ({
        type: metric.type,
        cpu_percent: metric.cpu.percentCPUUsage,
        private_kb: metric.memory.privateBytes,
        working_set_kb: metric.memory.workingSetSize,
      })),
    })}\n`
    if (OUTPUT_PATH) writeFileSync(OUTPUT_PATH, serialized, 'utf8')
    process.stdout.write(serialized)
    const failed = !profile.canvas_content_preserved_after_hide
      || !profile.viewport_preserved
      || !profile.series_data_references_preserved
      || profile.tooltip_wheel_bubble_count !== 0
      || profile.echarts_set_option_delta !== 0
      || profile.echarts_clear_delta !== 0
      || profile.echarts_resize_delta !== 0
      || rendererGone.length > 0
      || childGone.length > 0
    app.exit(failed ? 2 : 0)
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
    app.exit(1)
  }
}).catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
  app.exit(1)
})
