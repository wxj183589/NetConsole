const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const { app, BrowserWindow } = require('electron')

const SERIES_COUNT = 140
const POINT_COUNT = 14_581

app.commandLine.appendSwitch('enable-precise-memory-info')

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
  try {
    await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent('<!doctype html><html><body><div id="chart" style="width:1800px;height:900px"></div></body></html>')}`)
    const source = readFileSync(resolve(__dirname, '../../web/node_modules/echarts/dist/echarts.min.js'), 'utf8')
    await window.webContents.executeJavaScript(source)
    const profile = await window.webContents.executeJavaScript(`(async () => {
      const waitFrame = () => new Promise((resolveFrame) => requestAnimationFrame(() => resolveFrame()))
      const waitTwoFrames = async () => { await waitFrame(); await waitFrame() }
      const longTasks = []
      const observer = typeof PerformanceObserver === 'undefined'
        ? null
        : new PerformanceObserver((list) => longTasks.push(...list.getEntries().map((entry) => entry.duration)))
      observer?.observe({ entryTypes: ['longtask'] })
      const heapBefore = performance.memory?.usedJSHeapSize ?? null
      const chart = echarts.init(document.getElementById('chart'), undefined, {
        renderer: 'canvas',
        useDirtyRect: true,
        devicePixelRatio: 1.5,
      })
      let remaining = ${POINT_COUNT}
      let globalIndex = 0
      const optionBuildStarted = performance.now()
      const series = Array.from({ length: ${SERIES_COUNT} }, (_, seriesIndex) => {
        const count = Math.floor(remaining / (${SERIES_COUNT} - seriesIndex))
        remaining -= count
        const data = Array.from({ length: count }, (_, pointIndex) => {
          const timestamp = Date.UTC(2026, 6, 20, 9, 0, seriesIndex, pointIndex)
          const value = 20 + globalIndex % 30
          globalIndex += 1
          return [timestamp, value]
        })
        return {
          id: 'series-' + seriesIndex,
          name: 'AP-' + seriesIndex + ' · Radio ' + (seriesIndex % 2 + 1),
          type: 'line',
          animation: false,
          showSymbol: false,
          symbol: 'none',
          emphasis: { disabled: true },
          connectNulls: false,
          lineStyle: { width: 2 },
          data,
        }
      })
      const option = {
        animation: false,
        tooltip: { trigger: 'axis', transitionDuration: 0, axisPointer: { type: 'line', snap: false } },
        legend: { type: 'scroll', bottom: 2 },
        toolbox: { right: 8, feature: { dataZoom: { yAxisIndex: 'none' }, restore: {}, saveAsImage: { pixelRatio: 2 } } },
        grid: { left: 58, right: 24, top: 32, bottom: 72, containLabel: true },
        xAxis: { type: 'time', min: Date.UTC(2026, 6, 20, 9), max: Date.UTC(2026, 6, 20, 12) },
        yAxis: { type: 'value', name: 'dBm' },
        dataZoom: [
          { type: 'inside', filterMode: 'none' },
          { type: 'slider', height: 18, bottom: 28, filterMode: 'none' },
        ],
        series,
      }
      const optionBuildMs = performance.now() - optionBuildStarted
      const firstInteractiveStarted = performance.now()
      const setOptionStarted = performance.now()
      chart.setOption(option, { replaceMerge: ['series'] })
      const setOptionMs = performance.now() - setOptionStarted
      await waitTwoFrames()
      const firstInteractiveMs = performance.now() - firstInteractiveStarted
      const firstData = series[0].data

      let viewportDispatchCount = 0
      let appliedViewport = null
      const applyViewport = (startValue, endValue) => {
        if (appliedViewport?.startValue === startValue && appliedViewport?.endValue === endValue) return
        appliedViewport = { startValue, endValue }
        viewportDispatchCount += 1
        chart.dispatchAction({
          type: 'dataZoom',
          batch: [0, 1].map((dataZoomIndex) => ({
            dataZoomIndex,
            startValue,
            endValue,
          })),
        }, { silent: true })
      }
      const dataZoomStarted = performance.now()
      applyViewport(Date.UTC(2026, 6, 20, 10), Date.UTC(2026, 6, 20, 11))
      applyViewport(Date.UTC(2026, 6, 20, 10), Date.UTC(2026, 6, 20, 11))
      const dataZoomMs = performance.now() - dataZoomStarted

      const resizeStarted = performance.now()
      document.getElementById('chart').style.width = '1600px'
      chart.resize()
      const resizeMs = performance.now() - resizeStarted

      const themeStarted = performance.now()
      chart.setOption({
        textStyle: { color: '#f2f4f7' },
        xAxis: { axisLabel: { color: '#98a2b3' } },
        yAxis: { axisLabel: { color: '#98a2b3' } },
        series: series.map((item) => ({ id: item.id, lineStyle: { width: 2 } })),
      }, { lazyUpdate: true })
      const themeUpdateMs = performance.now() - themeStarted
      await waitTwoFrames()
      observer?.disconnect()
      const heapAfter = performance.memory?.usedJSHeapSize ?? null
      const result = {
        series_count: series.length,
        point_count: globalIndex,
        renderer: chart.getZr().painter.getType(),
        dirty_rect_enabled: chart.getZr().painter._opts?.useDirtyRect === true,
        device_pixel_ratio: chart.getDevicePixelRatio(),
        option_build_ms: Number(optionBuildMs.toFixed(3)),
        initial_set_option_ms: Number(setOptionMs.toFixed(3)),
        first_interactive_ms: Number(firstInteractiveMs.toFixed(3)),
        data_zoom_ms: Number(dataZoomMs.toFixed(3)),
        resize_ms: Number(resizeMs.toFixed(3)),
        theme_update_ms: Number(themeUpdateMs.toFixed(3)),
        max_long_task_ms: Number(Math.max(0, ...longTasks).toFixed(3)),
        heap_delta_bytes: heapBefore == null || heapAfter == null ? null : heapAfter - heapBefore,
        series_data_reference_preserved: series[0].data === firstData,
        viewport_dispatch_count: viewportDispatchCount,
        duplicate_viewport_sync_count: Math.max(0, viewportDispatchCount - 1),
      }
      chart.dispose()
      return result
    })()`, true)
    const gpuFeatureStatus = app.getGPUFeatureStatus()
    process.stdout.write(`${JSON.stringify({ ...profile, gpu_feature_status: gpuFeatureStatus })}\n`)
    app.exit(0)
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
    app.exit(1)
  }
}).catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
  app.exit(1)
})
