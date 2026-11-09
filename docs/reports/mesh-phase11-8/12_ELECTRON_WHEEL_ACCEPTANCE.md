# MESH 普通滚轮 Electron 局部验收

日期：2026-11-09。结论：`MESH_WHEEL_ZOOM=IMPLEMENTED_NOT_RUNTIME_VERIFIED`。已执行部分真实 Electron 操作，但完整运行态验收尚未完成，不代表 MESH_STATUS=COMPLETE。

## 环境

- 产品分支 `codex-A/global-dataroot-disk-policy`。开始时 HEAD `f9b2fb43`，并行任务随后将 HEAD 推进至 `b3ccb1bd`；本轮运行包含工作区中的滚轮修复和其他已有未提交修改。
- Electron 43.1.1，使用项目 Electron 主进程和 Vite 5189，后端 18183；Playwright Electron 及 CDP 控制真实窗口。后端显示 Online。
- 数据根 `D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001`；宁波地铁12号线，列车01-MR-CW，会话 `80716c07-6bd9-47d8-b76d-ace1e55624d1:1`，108700 条链路记录。未连接真实设备，未修改生产或开发数据根。
- 主显示器 2560×1440，系统缩放 100%（DPR 1）。窗口外框 1920×1080，Windows 边框内网页截图为 1904×1041，故截图尺寸要求未通过。截图来自 Electron 的 webContents，不包含系统窗口边框。

## 发现和修复

实际滚轮事件到达画布后被 ECharts 阻止冒泡，原先组件在容器冒泡阶段监听，因此普通滚轮未改变窗口。`MeshMetricChart.vue` 将监听改为捕获阶段，保留非 passive、绘图区判断以及仅在窗口变化时阻止默认行为，卸载时以同一捕获参数移除。新增画布停止冒泡的组件回归测试。

## 实际结果

| 项目 | 结果 |
| --- | --- |
| 普通滚轮向上 | 修复后真实 Electron 中从 300 秒缩为 240 秒；鼠标约在绘图区左侧，开始时间增加 15.893 秒，符合位置锚定的方向。 |
| 普通滚轮向下 | 重启后从 32.212 秒扩大至 40.265 秒，时间顺序正常。 |
| 已加载图表同步 | 重启后 RSSI、CPU、内存三张实际 ECharts 实例的 `dataZoom` 起止值一致，缩放前后实例 ID 保持不变。其余图表、Slider 和时间输入未完成逐项验证。 |
| 查询性能 | 一次 300 秒到 240 秒的缩放在加载范围内产生 6 个 MESH 请求：RSSI、CPU、内存、建链记录、分页历史和最近样本；6 个均返回 200。未满足已加载范围内避免重复完整查询的要求。 |
| 请求取消 | 后续多次操作的监听记录包含取消，但未完成逐请求配对和延迟统计，不能作为完整竞态验收。 |
| 页面外滚动、边界、连续滚轮 | 未完成验收。 |
| Tooltip、双击、Esc、Shift 左键、Ctrl 浏览、右侧详情 | 未完成本轮完整交互验收。 |
| AP、Radio、角色切换及页面重新进入 | 重启后进入了会话和主链路页面，但切换与重新进入后的完整交互未完成。 |
| Console | 未完成全程控制台审计。 |

根因是工作台 `setWindow` 180 ms 后调用 `loadMain`，按新窗口重新加载指标和分页业务数据。指标可能已降采样，历史记录和建链列表又是分页数据；不能直接把它们当作完整范围缓存。仍需实现有完整性证明的范围缓存、分页和选中详情一致性，再进行实际请求量验收。

## 截图

真实 Electron 截图位于 `screenshots/01-initial-main-monitor.png`、`02-wheel-zoom-in.png`、`03-wheel-zoom-out.png`、`04-wheel-anchor-position.png`。均为 1904×1041 内容区；04 仅记录一次锚点操作，不代表 25%/50%/75% 对照已完成。05 至 10 未生成。01、02 为重启前的修复验证，03、04 为重启后验证。

## 自动化检查

- MESH Renderer 定向测试：24 文件、229 测试通过。
- Renderer `pnpm build` 通过，包含 `vue-tsc -b`；构建报告已有大 chunk 警告。
- Electron 主进程 `pnpm run build:main` 通过。
- `git diff --check` 通过，Git 提示测试文件后续可能转为 CRLF。

## 未完成

完成范围缓存和请求性能修复；重启后对全部图表、右侧数据、页面外滚动、连续滚轮、各种 Tooltip 和 AP/Radio 切换执行完整 Electron 交互；提供 1920×1080 真实截图及 05–10；记录每项耗时、请求配对、控制台错误和完整结果。不得将当前结果标为 PASS 或 PASS_WITH_PERFORMANCE_LIMITATIONS。
