# 旧版 UI/UX 审计

以 `67865662` 为改造比较基线。依据 [实际路由](../../apps/desktop_renderer/src/router/routes.ts)、[菜单注册表](../../apps/desktop_renderer/src/navigation/registry.ts) 和 [四个任务入口](../../apps/desktop_renderer/src/navigation/deviceTaskEntries.ts) 核对。AppLayout 是布局容器。展开任务枚举后有 48 条子路由，其中 33 条普通页面路由、2 条隐藏实际页、13 条兼容跳转。菜单有 10 个一级入口，另有 2 个 `implemented: false` 的无线占位。页面可见性还受 Full/Customer、桌面宿主及父子权限共同影响。

| 路径 | 用途 | 组件或目标路由 |
| --- | --- | --- |
| `/` | 菜单候选 | `DashboardView.vue` |
| `/network/devices` | 菜单候选 | `DeviceManagementView.vue` |
| `/devices/archive` | 菜单候选 | `DeviceArchiveListView.vue` |
| `/console` | 菜单候选 | `ConsoleWorkspaceView.vue` |
| `/devices/:deviceId` | 隐藏实际页 | `DeviceDetailView.vue` |
| `/ac-management` | 菜单候选 | `AcControllersView.vue` |
| `/ac-management/fit-aps` | 菜单候选 | `AcManagementView.vue` |
| `/ac-management/optical` | 兼容别名 | `ac-fit-aps` |
| `/ac-management/extensions` | 菜单候选 | `AcWebParityView.vue` |
| `/ac-management/mesh-links` | 兼容别名 | `ground-unattended` |
| `/ac/mesh-link-monitor` | 兼容别名 | `ground-unattended` |
| `/rail-transit/wireless-dashboard` | 菜单候选 | `RailTransitWirelessDashboardView.vue` |
| `/rail-transit/infrastructure` | 菜单候选 | `RailTransitInfrastructureView.vue` |
| `/rail-transit/base-data` | 菜单候选 | `RailTransitBaseDataView.vue` |
| `/rail-transit/train-online` | 兼容别名 | `ground-unattended` |
| `/rail-transit/ground-unattended` | 菜单候选 | `GroundUnattendedView.vue` |
| `/rail-transit/ground-unattended-replay` | 菜单候选 | `GroundUnattendedReplayView.vue` |
| `/rail-transit/car-network-diagnostic` | 兼容别名 | `ground-unattended` |
| `/rail-transit/trackside-ap-business` | 菜单候选 | `TracksideApBusinessView.vue` |
| `/rail-transit/trackside-ap-plan` | 兼容别名 | `rail-transit-base-data` |
| `/rail-transit/mesh-analysis` | 菜单候选 | `MeshAnalysisView.vue` |
| `/rail-transit/online-mr` | 菜单候选 | `OnlineMrRealtimeView.vue` |
| `/rail-transit/online-mr-analysis` | 菜单候选 | `OnlineMrAnalysisView.vue` |
| `/config-center` | 无菜单路由 | `ConfigCollectionView.vue` |
| `/device-files` | 菜单候选 | `DeviceFileTransferView.vue` |
| `/device-files/diagnostics` | 无菜单路由 | `DeviceDiagnosticDownloadView.vue` |
| `/file-manager` | 菜单候选 | `FileManagerWorkspaceView.vue` |
| `/file-management` | 兼容别名 | `device-file-downloads` |
| `/tools/traffic` | 菜单候选 | `TrafficTestView.vue` |
| `/tools/connectivity` | 菜单候选 | `NetworkToolsView.vue` |
| `/tools/wireless-scan` | 菜单候选 | `WirelessScanView.vue` |
| `/tools/network-components` | 菜单候选 | `NetworkComponentsView.vue` |
| `/tools/network-services` | 菜单候选 | `LocalNetworkServicesView.vue` |
| `/network-tools/traffic` | 兼容别名 | `tools-traffic` |
| `/network-tools/toolbox` | 兼容别名 | `tools-connectivity` |
| `/network-tools/wireless-scan` | 兼容别名 | `tools-wireless-scan` |
| `/network-tools/overview` | 兼容别名 | `tools-connectivity` |
| `/tools` | 菜单候选 | `ToolCollectionView.vue` |
| `/tasks` | 菜单候选 | `JobCenterView.vue` |
| `/storage-management` | 兼容别名 | `system-settings` |
| `/settings` | 菜单候选 | `SystemSettingsView.vue` |
| `/feature-flags` | 隐藏实际页 | `RetiredFeatureDeliveryView.vue` |
| `/command-reference` | 兼容别名 | `logs` |
| `/logs` | 菜单候选 | `SystemMaintenanceView.vue` |
| `/tasks/diagnostic` | 菜单候选 | `JobCenterView.vue`，诊断收集 |
| `/tasks/backup` | 菜单候选 | `JobCenterView.vue`，配置备份 |
| `/tasks/upgrade_lab` | 菜单候选 | `JobCenterView.vue`，版本升级 |
| `/tasks/config_generate` | 菜单候选 | `JobCenterView.vue`，配置生成 |

导航隐藏的占位是 AP 在线概览和 AC 配置快照。原 `/file-manager?device_uuid=…` 根据参数前往传输的 SFTP 子视图，计数归在 canonical 文件路由。命令参考、局点存储和轨旁规划保留为带 query 的跳转。版本与功能交付页保持桌面隐藏。独立任务详情、会话和文件面板属页内工作区。

## 改造与异常提示

改造覆盖按 `git diff 67865662` 中实际发生的页面或直接消费组件分组。下表中的局部覆盖只证明代码有变更，交互截图和真实数据验收由集成报告独立记录。

| 模块 | 当前改造触点 | 异常提示与边界 |
| --- | --- | --- |
| 应用外壳与首页 | AppLayout、DesktopRuntimeStatus、Dashboard、运维聚合组件 | 后端和局点状态简明表达，子请求各自报告缺口 |
| 设备与档案 | DeviceManagementView 与连接表单。档案独立页面保留 | 表单逐项验证；档案长期展示采集事实 |
| 任务与配置 | DeviceTaskCreateDialog、ConfigCollectionView | 提交和结果分开，终态保留失败原因。升级能力限既有实验模板 |
| 无线与轨交 | AC、FIT-AP、InfrastructureWorkbench、地面概览、Trackside AP | 保留数据源失败、冲突、未知、过期状态；实时和回放保持独立 |
| 控制台 | ConsoleWorkspaceView 操作分组 | 多行确认、同步目标和授权判断沿用原实现 |
| 文件 | FileWorkspacePanel 地址、状态、文件预览 | 保留受管校验、另存和清理失败。远端文件传输页面本轮局部扫描 |
| 日志 | SystemMaintenanceView 维护与导出操作 | 默认重要事件，原始事件按需展开，任务与服务日志分别查询 |
| 网络 | NetworkToolboxPanel 地址计算与诊断 | 状态和详情分开展示；无线扫描、流量测试和监听服务未逐项改造 |
| 独立工具、系统设置 | 入口审计 | 按原权限展示；未安排页内改造 |

复核使用各组件的 `catch`、`ElMessage.error`、终态与空状态。常见失败包括连接/超时、权限、请求冲突、文件完整性、局点切换和用户取消。前四项仍由业务契约产生状态，取消沿用各模块原判断。未逐个枚举子弹窗的异常路径。

首页最近记录使用当前局点持久的设备任务列表，传入 `expected_site`、`device_only=true`，限 6 条。建议标题使用“最近设备任务”，点击沿用任务 ID 及局点深链。控制台、文件或单纯页面访问记录需要各自的持久审计来源。
