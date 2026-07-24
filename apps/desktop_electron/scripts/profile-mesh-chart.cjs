const { readFileSync, writeFileSync } = require('node:fs')
const { resolve } = require('node:path')
const { app, BrowserWindow } = require('electron')

function positiveProfileSize(name, fallback) {
  const value = Number.parseInt(process.env[name] || '', 10)
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const SERIES_COUNT = positiveProfileSize('NETCONSOLE_MESH_PROFILE_SERIES_COUNT', 770)
const POINT_COUNT = positiveProfileSize('NETCONSOLE_MESH_PROFILE_POINT_COUNT', 44_251)
const FRAME_COUNT = positiveProfileSize('NETCONSOLE_MESH_PROFILE_FRAME_COUNT', 18_188)
const SESSION_COUNT = positiveProfileSize('NETCONSOLE_MESH_PROFILE_SESSION_COUNT', 10)
const SOFTWARE_RENDERING = process.env.NETCONSOLE_MESH_PROFILE_SOFTWARE === '1'
const OUTPUT_PATH = process.argv.find((value) => value.startsWith('--output='))?.slice('--output='.length)
  || process.env.NETCONSOLE_MESH_PROFILE_OUTPUT

if (SOFTWARE_RENDERING) app.disableHardwareAcceleration()
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
    await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent('<!doctype html><html><body><div id="chart" style="width:1800px;height:900px"></div></body></html>')}`)
    const vueSource = readFileSync(resolve(__dirname, '../../web/node_modules/vue/dist/vue.global.prod.js'), 'utf8')
    const echartsSource = readFileSync(resolve(__dirname, '../../web/node_modules/echarts/dist/echarts.min.js'), 'utf8')
    await window.webContents.executeJavaScript(vueSource)
    await window.webContents.executeJavaScript(echartsSource)
    const profile = await window.webContents.executeJavaScript(`(async () => {
      const SERIES_COUNT = ${SERIES_COUNT}
      const POINT_COUNT = ${POINT_COUNT}
      const FRAME_COUNT = ${FRAME_COUNT}
      const SESSION_COUNT = ${SESSION_COUNT}
      const waitFrame = () => new Promise((resolveFrame) => requestAnimationFrame(() => resolveFrame()))
      const waitTwoFrames = async () => { await waitFrame(); await waitFrame() }
      const collectGarbage = async () => {
        if (typeof globalThis.gc === 'function') globalThis.gc()
        await waitTwoFrames()
      }
      const heap = () => performance.memory?.usedJSHeapSize ?? null
      const bytes = (value) => new TextEncoder().encode(JSON.stringify(value)).byteLength
      const longTasks = []
      const observer = typeof PerformanceObserver === 'undefined'
        ? null
        : new PerformanceObserver((list) => longTasks.push(...list.getEntries().map((entry) => entry.duration)))
      observer?.observe({ entryTypes: ['longtask'] })

      function createPayload(sessionIndex) {
        const series = Array.from({ length: SERIES_COUNT }, (_, seriesIndex) => ({
          series_id: 'session-' + sessionIndex + ':ap-' + seriesIndex + ':radio:' + (seriesIndex % 2 + 1),
          peer_name: 'AP-' + seriesIndex,
          peer_mac: 'peer-' + String(seriesIndex).padStart(4, '0'),
          ap_mac: 'ap-' + String(seriesIndex).padStart(4, '0'),
          peer_radio_mac: 'radio-' + String(seriesIndex).padStart(4, '0'),
          radio: seriesIndex % 2 + 1,
          station: 'station-' + (seriesIndex % 20),
          section: 'section-' + (seriesIndex % 30),
          roles_present: ['ACTIVE', 'STANDBY'],
          data_source: 'peer_rssi_db',
          total_points: 0,
          returned_points: 0,
          points: [],
        }))
        for (let pointIndex = 0; pointIndex < POINT_COUNT; pointIndex += 1) {
          const seriesIndex = pointIndex % SERIES_COUNT
          const frameIndex = Math.floor(pointIndex * FRAME_COUNT / POINT_COUNT)
          const timestampMillis = Date.UTC(2026, 6, 20, 9, 0, 0, frameIndex)
          series[seriesIndex].points.push({
            timestamp: new Date(timestampMillis).toISOString(),
            timestamp_tag: 'sample-' + pointIndex,
            source_file_id: 7,
            link_id: pointIndex + 1,
            sample_id: pointIndex + 1,
            local_radio: seriesIndex % 2 + 1,
            role: pointIndex % 3 === 0 ? 'STANDBY' : 'ACTIVE',
            peer_mac: series[seriesIndex].peer_mac,
            peer_ap_name: series[seriesIndex].peer_name,
            peer_ap_mac: series[seriesIndex].ap_mac,
            peer_radio: 'Radio ' + (seriesIndex % 2 + 1),
            peer_radio_mac: series[seriesIndex].peer_radio_mac,
            station: series[seriesIndex].station,
            section: series[seriesIndex].section,
            peer_rssi: 20 + pointIndex % 30,
            local_rssi: 18 + pointIndex % 30,
            peer_signal: null,
            local_signal: null,
            run_id: 'run-' + (pointIndex % 6398),
            run_sequence: pointIndex % 6398,
            segment_duration_seconds: 1,
            break_before: false,
            data_source: 'peer_rssi_db',
          })
        }
        for (const item of series) {
          item.total_points = item.points.length
          item.returned_points = item.points.length
        }
        return {
          source_id: 'session-' + sessionIndex,
          radio: null,
          time_range: {
            start: new Date(Date.UTC(2026, 6, 20, 9)).toISOString(),
            end: new Date(Date.UTC(2026, 6, 20, 9, 0, 0, FRAME_COUNT - 1)).toISOString(),
          },
          total_frames: 54800,
          returned_frames: FRAME_COUNT,
          total_link_points: 113958,
          returned_link_points: POINT_COUNT,
          returned_series: SERIES_COUNT,
          series,
          events: [],
          warnings: [],
        }
      }

      function buildCompactCache(sourceSeries) {
        const pointMetaById = new Map()
        const seriesMetaById = new Map()
        const dataIndexToMetaId = new Map()
        const frameMetaIds = new Map()
        const frameTimestamps = new Set()
        let metaId = 0
        const series = sourceSeries.map((source) => {
          const seriesMeta = {
            seriesId: source.series_id,
            name: source.peer_name + ' · Radio ' + source.radio,
            peerName: source.peer_name,
            peerMac: source.peer_mac,
            apMac: source.ap_mac,
            peerRadioMac: source.peer_radio_mac,
            radio: source.radio,
            station: source.station,
            section: source.section,
            pointCount: source.points.length,
          }
          seriesMetaById.set(source.series_id, seriesMeta)
          const metaIds = []
          const data = source.points.map((point) => {
            const id = metaId++
            const timestampMillis = Date.parse(point.timestamp)
            const roleCode = point.role === 'ACTIVE' ? 0 : 1
            const pointMeta = {
              metaId: id,
              seriesId: source.series_id,
              timestampMillis,
              timestampTag: point.timestamp_tag,
              sourceFileId: point.source_file_id,
              linkId: point.link_id,
              sampleId: point.sample_id,
              localRadio: point.local_radio,
              role: point.role,
              peerMac: point.peer_mac,
              peerApName: point.peer_ap_name,
              peerApMac: point.peer_ap_mac,
              peerRadio: point.peer_radio,
              peerRadioMac: point.peer_radio_mac,
              station: point.station,
              section: point.section,
              rssi: point.peer_rssi,
              localRssi: point.local_rssi,
              peerSignal: point.peer_signal,
              localSignal: point.local_signal,
              runId: point.run_id,
              segmentDurationSeconds: point.segment_duration_seconds,
              dataSource: point.data_source,
            }
            pointMetaById.set(id, pointMeta)
            metaIds.push(id)
            frameTimestamps.add(timestampMillis)
            const frame = frameMetaIds.get(timestampMillis)
            if (frame) frame.push(id)
            else frameMetaIds.set(timestampMillis, [id])
            return [timestampMillis, point.peer_rssi, id, roleCode]
          })
          dataIndexToMetaId.set(source.series_id, metaIds)
          return {
            id: source.series_id,
            name: seriesMeta.name,
            data,
            meta: seriesMeta,
            firstTimestampMillis: data[0]?.[0] ?? null,
            lastTimestampMillis: data.at(-1)?.[0] ?? null,
          }
        })
        return {
          series,
          pointMetaById,
          seriesMetaById,
          dataIndexToMetaId,
          frameMetaIds,
          frameTimestamps: [...frameTimestamps].sort((left, right) => left - right),
        }
      }

      function clearCompactCache(cache) {
        for (const item of cache.series) item.data.length = 0
        cache.series.length = 0
        cache.pointMetaById.clear()
        cache.seriesMetaById.clear()
        cache.dataIndexToMetaId.clear()
        cache.frameMetaIds.clear()
        cache.frameTimestamps.length = 0
      }

      function lowerBound(data, timestampMillis) {
        let low = 0
        let high = data.length
        while (low < high) {
          const middle = (low + high) >>> 1
          if (data[middle][0] < timestampMillis) low = middle + 1
          else high = middle
        }
        return low
      }

      function viewportSeries(cache, startMillis, endMillis) {
        return cache.series.filter((item) => {
          if (
            item.firstTimestampMillis == null
            || item.lastTimestampMillis == null
            || item.lastTimestampMillis < startMillis
            || item.firstTimestampMillis > endMillis
          ) return false
          const index = lowerBound(item.data, startMillis)
          return index < item.data.length && item.data[index][0] <= endMillis
        })
      }

      function escapeTooltipHtml(value) {
        const text = value == null || value === '' ? '—' : String(value)
        return text.replace(/[&<>"']/g, (char) => ({
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;',
        })[char] || char)
      }

      function buildTracksideTooltip(cache, timestampMillis) {
        const entries = (cache.frameMetaIds.get(timestampMillis) || [])
          .map((metaId) => cache.pointMetaById.get(metaId))
          .filter(Boolean)
          .sort((left, right) => (
            (left.role === 'ACTIVE' ? 0 : 1) - (right.role === 'ACTIVE' ? 0 : 1)
            || String(left.peerApName || left.peerMac || '').localeCompare(String(right.peerApName || right.peerMac || ''), 'zh-CN')
            || (left.localRadio ?? Number.MAX_SAFE_INTEGER) - (right.localRadio ?? Number.MAX_SAFE_INTEGER)
          ))
        const rows = entries.map((entry) => {
          const symbol = entry.role === 'ACTIVE' ? '●' : '○'
          const duration = entry.role === 'ACTIVE'
            && entry.segmentDurationSeconds != null
            && Number.isFinite(entry.segmentDurationSeconds)
            ? '<br>主链持续：' + entry.segmentDurationSeconds + ' s'
            : ''
          return '<strong>' + symbol + ' ' + entry.role + '　'
            + escapeTooltipHtml(entry.peerApName || entry.peerMac || '轨旁 AP 未知')
            + ' · Radio ' + escapeTooltipHtml(entry.localRadio) + '</strong>'
            + '<br>轨旁 / MR RSSI：' + escapeTooltipHtml(entry.rssi) + ' / ' + escapeTooltipHtml(entry.localRssi)
            + '<br>站点 / 区间：' + escapeTooltipHtml(entry.station) + ' / ' + escapeTooltipHtml(entry.section)
            + duration
        })
        return '<div>采样时间：' + new Date(timestampMillis).toISOString() + rows.join('') + '</div>'
      }

      function createOption(cache) {
        return {
          animation: false,
          tooltip: {
            trigger: 'axis',
            transitionDuration: 0,
            axisPointer: { type: 'line', snap: false },
          },
          legend: { show: false, data: [] },
          toolbox: {
            right: 8,
            feature: {
              dataZoom: { yAxisIndex: 'none' },
              restore: {},
              saveAsImage: { pixelRatio: 2 },
            },
          },
          grid: { left: 58, right: 24, top: 32, bottom: 52, containLabel: true },
          xAxis: { type: 'time', minInterval: 1000 },
          yAxis: { type: 'value', name: 'RSSI' },
          dataZoom: [
            { type: 'inside', filterMode: 'none', minValueSpan: 1000 },
            { type: 'slider', height: 18, bottom: 12, filterMode: 'none', minValueSpan: 1000 },
          ],
          series: cache.series.map((item) => ({
            id: item.id,
            name: item.name,
            type: 'line',
            animation: false,
            showSymbol: false,
            symbol: 'none',
            hoverAnimation: false,
            emphasis: { disabled: true },
            progressive: 3000,
            progressiveThreshold: 3000,
            connectNulls: false,
            lineStyle: { width: 2 },
            data: item.data,
          })),
        }
      }

      await collectGarbage()
      const heapBefore = heap()
      const sessionProfiles = []
      let apiPayloadBytes = 0
      let estimatedLegacyOptionBytes = 0
      let compactOptionBytes = 0
      let payloadInstallMs = 0
      let cacheBuildMs = 0
      let optionBuildMs = 0
      let setOptionMs = 0
      let firstInteractiveMs = 0
      let renderer = null
      let dirtyRectEnabled = false
      let devicePixelRatio = null
      let preservedDataReference = false
      let tooltipFrameLinkCount = 0
      let tooltipBuildAverageMs = 0
      let tooltipBuildMaximumMs = 0
      let chartInitCount = 0
      let chartSetOptionCount = 0
      let chartDisposeCount = 0
      let cacheBuildCount = 0
      let cacheDisposeCount = 0
      let layoutSwitchAverageMs = 0
      let layoutSwitchMaximumMs = 0
      let layoutSwitchViewportPreserved = false
      let layoutSwitchInitDelta = 0
      let layoutSwitchSetOptionDelta = 0
      let layoutSwitchDisposeDelta = 0
      let layoutSwitchHeapGrowthBytes = null
      let layoutSwitchSteadyHeapGrowthBytes = null
      let visibleSeriesInViewport = 0
      let viewportListComputeAverageMs = 0
      let viewportListComputeMaximumMs = 0
      let selectedSeriesId = null
      let selectionStyleUpdateAverageMs = 0
      let selectionStyleUpdateMaximumMs = 0
      let selectionHeapGrowthBytes = null
      let selectionSteadyHeapGrowthBytes = null
      let selectionDataReferencesPreserved = false
      let selectionInitDelta = 0
      let selectionSetOptionDelta = 0
      let selectionDisposeDelta = 0

      for (let sessionIndex = 0; sessionIndex < SESSION_COUNT; sessionIndex += 1) {
        await collectGarbage()
        const beforeSessionHeap = heap()
        let payload = createPayload(sessionIndex)
        if (sessionIndex === 0) {
          apiPayloadBytes = bytes(payload)
          estimatedLegacyOptionBytes = payload.series.reduce((total, item) => {
            const seriesMetaBytes = bytes(item)
            return total + item.points.reduce((subtotal, point) => (
              subtotal + bytes({
                value: [Date.parse(point.timestamp), point.peer_rssi],
                symbol: point.role === 'ACTIVE' ? 'circle' : 'emptyCircle',
                meta: point,
              }) + seriesMetaBytes
            ), 0)
          }, 0)
        }
        const installStarted = performance.now()
        const tracksideSignal = Vue.shallowRef(Vue.markRaw(payload))
        const installMs = performance.now() - installStarted
        const cacheStarted = performance.now()
        const cache = buildCompactCache(tracksideSignal.value.series)
        cacheBuildCount += 1
        const builtCacheMs = performance.now() - cacheStarted
        const optionStarted = performance.now()
        const option = createOption(cache)
        const builtOptionMs = performance.now() - optionStarted
        if (sessionIndex === 0) {
          compactOptionBytes = bytes(option)
          payloadInstallMs = installMs
          cacheBuildMs = builtCacheMs
          optionBuildMs = builtOptionMs
          preservedDataReference = option.series[0].data === cache.series[0].data
          const tooltipFrame = cache.frameTimestamps.reduce((selected, timestamp) => (
            (cache.frameMetaIds.get(timestamp)?.length || 0) > (cache.frameMetaIds.get(selected)?.length || 0)
              ? timestamp
              : selected
          ), cache.frameTimestamps[0])
          tooltipFrameLinkCount = cache.frameMetaIds.get(tooltipFrame)?.length || 0
          const tooltipDurations = Array.from({ length: 100 }, () => {
            const tooltipStarted = performance.now()
            buildTracksideTooltip(cache, tooltipFrame)
            return performance.now() - tooltipStarted
          })
          tooltipBuildAverageMs = tooltipDurations.reduce((total, value) => total + value, 0) / tooltipDurations.length
          tooltipBuildMaximumMs = Math.max(...tooltipDurations)
        }
        tracksideSignal.value = Vue.markRaw({
          ...payload,
          series: [],
        })
        payload = null
        await collectGarbage()
        const heapBeforeChart = heap()
        const chart = echarts.init(document.getElementById('chart'), undefined, {
          renderer: 'canvas',
          useDirtyRect: true,
          devicePixelRatio: 1.5,
        })
        chartInitCount += 1
        const interactiveStarted = performance.now()
        const setStarted = performance.now()
        chart.setOption(option, { replaceMerge: ['series'] })
        chartSetOptionCount += 1
        const currentSetOptionMs = performance.now() - setStarted
        await waitTwoFrames()
        const currentInteractiveMs = performance.now() - interactiveStarted
        if (sessionIndex === 0) {
          setOptionMs = currentSetOptionMs
          firstInteractiveMs = currentInteractiveMs
          renderer = chart.getZr().painter.getType()
          dirtyRectEnabled = chart.getZr().painter._opts?.useDirtyRect === true
          devicePixelRatio = chart.getDevicePixelRatio()
          const viewportListDurations = []
          for (let viewportIndex = 0; viewportIndex < 100; viewportIndex += 1) {
            const startIndex = viewportIndex * 137 % Math.max(1, cache.frameTimestamps.length - 50)
            const viewportStarted = performance.now()
            visibleSeriesInViewport = viewportSeries(
              cache,
              cache.frameTimestamps[startIndex],
              cache.frameTimestamps[Math.min(cache.frameTimestamps.length - 1, startIndex + 50)],
            ).length
            viewportListDurations.push(performance.now() - viewportStarted)
          }
          viewportListComputeAverageMs = viewportListDurations.reduce((total, value) => total + value, 0) / viewportListDurations.length
          viewportListComputeMaximumMs = Math.max(...viewportListDurations)

          const selectionDataReferences = cache.series.map((item) => item.data)
          const initBeforeSelections = chartInitCount
          const setOptionBeforeSelections = chartSetOptionCount
          const disposeBeforeSelections = chartDisposeCount
          const selectionDurations = []
          const selectionStatus = document.createElement('div')
          document.body.append(selectionStatus)
          await collectGarbage()
          const selectionHeapBefore = heap()
          const runSelectionBatch = async (offset) => {
            for (let selectionIndex = 0; selectionIndex < 100; selectionIndex += 1) {
              const selected = cache.series[(selectionIndex + offset) % cache.series.length]
              selectedSeriesId = selected.id
              const selectionStarted = performance.now()
              const point = cache.pointMetaById.get(selected.data[0]?.[2])
              selectionStatus.textContent = [
                selected.meta.peerName || selected.meta.apMac || '轨旁 AP 未知',
                selected.meta.apMac || '—',
                'Radio ' + (selected.meta.radio ?? '—'),
                'RSSI ' + (point?.rssi ?? '—'),
              ].join(' · ')
              selectionDurations.push(performance.now() - selectionStarted)
            }
          }
          await runSelectionBatch(0)
          await waitTwoFrames()
          await collectGarbage()
          const selectionHeapAfterFirstBatch = heap()
          selectionHeapGrowthBytes = selectionHeapBefore == null || selectionHeapAfterFirstBatch == null
            ? null
            : selectionHeapAfterFirstBatch - selectionHeapBefore
          await runSelectionBatch(100)
          await waitTwoFrames()
          await collectGarbage()
          const selectionHeapAfterSecondBatch = heap()
          selectionSteadyHeapGrowthBytes = selectionHeapAfterFirstBatch == null || selectionHeapAfterSecondBatch == null
            ? null
            : selectionHeapAfterSecondBatch - selectionHeapAfterFirstBatch
          selectionStyleUpdateAverageMs = selectionDurations.reduce((total, value) => total + value, 0) / selectionDurations.length
          selectionStyleUpdateMaximumMs = Math.max(...selectionDurations)
          selectionDataReferencesPreserved = cache.series.every((item, index) => item.data === selectionDataReferences[index])
          selectionInitDelta = chartInitCount - initBeforeSelections
          selectionSetOptionDelta = chartSetOptionCount - setOptionBeforeSelections
          selectionDisposeDelta = chartDisposeCount - disposeBeforeSelections
          selectionStatus.remove()

          chart.dispatchAction({ type: 'dataZoom', start: 20, end: 60 }, { silent: true })
          await waitFrame()
          const viewportBefore = JSON.stringify((chart.getOption().dataZoom || []).map((item) => ({
            start: item.start,
            end: item.end,
            startValue: item.startValue,
            endValue: item.endValue,
          })))
          const initBeforeSwitches = chartInitCount
          const setOptionBeforeSwitches = chartSetOptionCount
          const disposeBeforeSwitches = chartDisposeCount
          const layoutDurations = []
          const chartElement = document.getElementById('chart')
          await collectGarbage()
          const layoutHeapBefore = heap()
          const runLayoutSwitchBatch = () => {
            for (let layoutIndex = 0; layoutIndex < 20; layoutIndex += 1) {
              chartElement.style.height = layoutIndex % 2 === 0 ? '430px' : '900px'
              const layoutStarted = performance.now()
              chart.resize({ silent: true, animation: { duration: 0 } })
              layoutDurations.push(performance.now() - layoutStarted)
            }
          }
          runLayoutSwitchBatch()
          await waitTwoFrames()
          await collectGarbage()
          const layoutHeapAfterFirstBatch = heap()
          layoutSwitchHeapGrowthBytes = layoutHeapBefore == null || layoutHeapAfterFirstBatch == null
            ? null
            : layoutHeapAfterFirstBatch - layoutHeapBefore
          runLayoutSwitchBatch()
          await waitTwoFrames()
          await collectGarbage()
          const layoutHeapAfterSecondBatch = heap()
          layoutSwitchSteadyHeapGrowthBytes = layoutHeapAfterFirstBatch == null || layoutHeapAfterSecondBatch == null
            ? null
            : layoutHeapAfterSecondBatch - layoutHeapAfterFirstBatch
          layoutSwitchAverageMs = layoutDurations.reduce((total, value) => total + value, 0) / layoutDurations.length
          layoutSwitchMaximumMs = Math.max(...layoutDurations)
          const viewportAfter = JSON.stringify((chart.getOption().dataZoom || []).map((item) => ({
            start: item.start,
            end: item.end,
            startValue: item.startValue,
            endValue: item.endValue,
          })))
          layoutSwitchViewportPreserved = viewportAfter === viewportBefore
          layoutSwitchInitDelta = chartInitCount - initBeforeSwitches
          layoutSwitchSetOptionDelta = chartSetOptionCount - setOptionBeforeSwitches
          layoutSwitchDisposeDelta = chartDisposeCount - disposeBeforeSwitches
        }
        chart.dispose()
        chartDisposeCount += 1
        clearCompactCache(cache)
        cacheDisposeCount += 1
        tracksideSignal.value = null
        await collectGarbage()
        sessionProfiles.push({
          session: sessionIndex + 1,
          before_heap_bytes: beforeSessionHeap,
          before_chart_heap_bytes: heapBeforeChart,
          residual_heap_bytes: heap(),
          set_option_ms: Number(currentSetOptionMs.toFixed(3)),
          interactive_ms: Number(currentInteractiveMs.toFixed(3)),
        })
      }

      observer?.disconnect()
      const residualHeaps = sessionProfiles.map((item) => item.residual_heap_bytes).filter((value) => value != null)
      return {
        series_count: SERIES_COUNT,
        point_count: POINT_COUNT,
        frame_count: FRAME_COUNT,
        session_count: SESSION_COUNT,
        active_api_count: 0,
        cache_build_count: cacheBuildCount,
        cache_dispose_count: cacheDisposeCount,
        chart_init_count: chartInitCount,
        chart_set_option_count: chartSetOptionCount,
        chart_dispose_count: chartDisposeCount,
        rendering_mode: ${JSON.stringify(SOFTWARE_RENDERING ? 'software' : 'hardware')},
        renderer,
        dirty_rect_enabled: dirtyRectEnabled,
        device_pixel_ratio: devicePixelRatio,
        legend_enabled: false,
        selected_series_id: selectedSeriesId,
        visible_series_in_viewport: visibleSeriesInViewport,
        viewport_list_iterations: 100,
        viewport_list_compute_average_ms: Number(viewportListComputeAverageMs.toFixed(3)),
        viewport_list_compute_maximum_ms: Number(viewportListComputeMaximumMs.toFixed(3)),
        selection_iterations_per_batch: 100,
        selection_total_iterations: 200,
        selection_style_update_average_ms: Number(selectionStyleUpdateAverageMs.toFixed(3)),
        selection_style_update_maximum_ms: Number(selectionStyleUpdateMaximumMs.toFixed(3)),
        selection_heap_growth_bytes: selectionHeapGrowthBytes,
        selection_steady_heap_growth_bytes: selectionSteadyHeapGrowthBytes,
        selection_series_data_references_preserved: selectionDataReferencesPreserved,
        selection_echarts_init_delta: selectionInitDelta,
        selection_echarts_set_option_delta: selectionSetOptionDelta,
        selection_echarts_dispose_delta: selectionDisposeDelta,
        api_payload_bytes: apiPayloadBytes,
        vue_shallow_payload_install_ms: Number(payloadInstallMs.toFixed(3)),
        compact_cache_build_ms: Number(cacheBuildMs.toFixed(3)),
        compact_option_build_ms: Number(optionBuildMs.toFixed(3)),
        compact_option_json_bytes: compactOptionBytes,
        estimated_legacy_option_json_bytes: estimatedLegacyOptionBytes,
        removed_point_meta_references: POINT_COUNT,
        removed_series_meta_references: POINT_COUNT,
        removed_indirect_points_traversals: Math.ceil(POINT_COUNT * POINT_COUNT / SERIES_COUNT),
        initial_set_option_ms: Number(setOptionMs.toFixed(3)),
        first_interactive_ms: Number(firstInteractiveMs.toFixed(3)),
        max_long_task_ms: Number(Math.max(0, ...longTasks).toFixed(3)),
        heap_before_bytes: heapBefore,
        final_residual_heap_bytes: heap(),
        residual_heap_growth_bytes: residualHeaps.length < 2 ? null : residualHeaps.at(-1) - residualHeaps[0],
        steady_state_residual_growth_bytes: residualHeaps.length < 3 ? null : residualHeaps.at(-1) - residualHeaps[1],
        series_data_reference_preserved: preservedDataReference,
        tooltip_profile_iterations: 100,
        tooltip_frame_link_count: tooltipFrameLinkCount,
        tooltip_build_average_ms: Number(tooltipBuildAverageMs.toFixed(3)),
        tooltip_build_maximum_ms: Number(tooltipBuildMaximumMs.toFixed(3)),
        layout_switch_count: 40,
        layout_switch_average_ms: Number(layoutSwitchAverageMs.toFixed(3)),
        layout_switch_maximum_ms: Number(layoutSwitchMaximumMs.toFixed(3)),
        layout_switch_viewport_preserved: layoutSwitchViewportPreserved,
        layout_switch_echarts_init_delta: layoutSwitchInitDelta,
        layout_switch_set_option_delta: layoutSwitchSetOptionDelta,
        layout_switch_echarts_dispose_delta: layoutSwitchDisposeDelta,
        layout_switch_heap_growth_bytes: layoutSwitchHeapGrowthBytes,
        layout_switch_steady_heap_growth_bytes: layoutSwitchSteadyHeapGrowthBytes,
        sessions: sessionProfiles,
      }
    })()`, true)
    await new Promise((resolveWait) => setTimeout(resolveWait, 500))
    const gpuFeatureStatus = app.getGPUFeatureStatus()
    const gpuInfo = await app.getGPUInfo('basic').catch(() => null)
    const processMetrics = app.getAppMetrics().map((metric) => ({
      type: metric.type,
      cpu_percent: metric.cpu.percentCPUUsage,
      private_kb: metric.memory.privateBytes,
      working_set_kb: metric.memory.workingSetSize,
    }))
    const serializedProfile = `${JSON.stringify({
      ...profile,
      renderer_process_gone: rendererGone,
      child_process_gone: childGone,
      gpu_feature_status: gpuFeatureStatus,
      gpu_aux_attributes: gpuInfo?.auxAttributes ?? null,
      process_metrics: processMetrics,
    })}\n`
    if (OUTPUT_PATH) {
      writeFileSync(OUTPUT_PATH, serializedProfile, 'utf8')
    }
    process.stdout.write(serializedProfile)
    app.exit(rendererGone.length || childGone.length ? 2 : 0)
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
    app.exit(1)
  }
}).catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
  app.exit(1)
})
