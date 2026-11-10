# MESH 普通滚轮缩放恢复

状态：`MESH_WHEEL_ZOOM=IMPLEMENTED_NOT_RUNTIME_VERIFIED`。本次是局部修改，不代表 Phase 11.8 完成。

## 原因和修改

提交 `dec6b1c3` 将主链路工作台的 ECharts 内置滚轮缩放关闭，并增加仅响应 Shift 滚轮的原生处理；当前代码和提交记录未提供更具体的设计原因。原处理的滚轮方向也与本次要求相反。

`MeshMetricChart.vue` 移除 Shift 限制，按鼠标所在绘图区的时间计算缩放中心；向上缩小窗口、向下扩大窗口，并限制在会话范围和最小 100 毫秒窗口内。绘图区外和无法继续缩放时不阻止默认滚动。原有非 passive 监听、卸载清理及 Tooltip、双击、Shift 左键、Ctrl 浏览代码保留。`MeshMetricChart.test.ts` 调整并增加方向、鼠标位置、边界和毫秒精度测试。

主链路工作台的 RSSI、CPU、内存、TxBusy、RxBusy、Rate、Noise、TxDesFreeCnt、Tx/Rx、Retry/Err、GARP、MulJoin 使用同一图表组件和工作台时间窗口；Slider、时间输入和详情沿用现有联动。其他 MESH 时间序列组件没有在本次修改，不能声称全部普通滚轮行为已验证。

## 性能和验证

- 本地窗口立即更新，既有工作台按 180 毫秒防抖在停止滚动后重新查询可见指标和历史记录；请求取消与缓存沿用原实现。本次未测量请求数量，也未实现已加载范围内完全免查询。
- MESH 组件及时间轴定向回归：24 文件、228 测试通过，包含现有 Tooltip、选择、同步和生命周期测试。
- Renderer `pnpm build` 通过，包含 `vue-tsc -b`；Vite 有既有大 chunk 警告。`git diff --check` 通过。
- Electron：当前源码以 `--codex --isolated-test-data D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001` 成功启动并报告 isolated_test；未完成真实鼠标滚轮、页面滚动、AP/Radio 切换和请求计数验收。已停止本次启动的进程。本轮没有截图；历史截图 `screenshots/01-main-monitor.png` 不能作为本次交互证据。
- 数据影响：使用既有隔离快照启动，运行可能写入该隔离根；未以真实开发数据根启动，也未复制数据根。

## 未完成

需要在真实 Electron 窗口逐项完成滚轮方向、不同鼠标位置、全部关联图表和详情同步、页面滚动、切换及连续滚轮请求数量验收；还需覆盖其他 MESH 时间序列图，以及解决已有数据范围内停止滚动后仍重新查询的问题。未完成前不得标记 PASS。

产品提交：以包含本报告的 Git 提交为准。
