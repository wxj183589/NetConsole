# UI 导入导出文件选择审计

本审计以 `apps/web/src/router/routes.ts` 的全部可见路由为入口，覆盖页面、弹窗、共享组件、Task Center、Electron Platform Adapter、Python API、Export Worker、Artifact Store、测试和构建脚本。审计基线为 2026-07-30。

## 统一结论

- 正式 Electron 的主动导出先由当前业务窗口打开 Windows“另存为”；用户取消时不调用导出 API、不创建任务、不生成 Artifact。
- 任务型导出通过 `exportActionRegistry.ts` 的固定动作定义和 `useUserSelectedExport.ts` 的共享协调器绑定 `taskId`、动作、Main 授权路径、文件类型和会话状态。Artifact 就绪后使用同一授权路径、大小与 SHA-256 调用 `downloadBackendResource`，不会再弹第二次窗口。
- 保存失败保留 Artifact；Task Center 对该绑定显示“重新选择保存位置”，复用原 Artifact，不重建导出任务。
- 只有当前 Renderer 会话中已有明确绑定的任务可以恢复后继续写入原授权位置。页面加载、Tab 恢复和历史任务恢复均不会自动打开“另存为”。
- 未绑定的历史 Artifact、单个既有配置 Artifact 等，只在用户点击“另存 Artifact/下载”时打开一次“另存为”。
- Browser 仅用于开发：下载结果只能报告 `started`，不声称已验证本地落盘。`netconsole_host=electron` 缺少 Bridge 时由平台层直接失败，不回退到浏览器下载。
- 导入仍由浏览器 `File/FileList` 或 Electron Main 的专用选择器承载；取消不预检、不提交，文件 input 在处理后清空，允许再次选择同名文件。扩展名过滤不能替代后端文件契约、schema、工作表/字段、非空、重复内容和 ZIP 路径安全校验。

## 页面审计矩阵

“整改前 → 当前”记录本轮发现的不一致及最终行为。“最终路径”指用户拿到的正式副本，不是 Export Worker 临时文件或 Artifact Store。

| 路由/页面 | 组件 | UI 动作 | 类型 | 整改前 → 当前 | 是否弹窗 | 当前最终路径 | 是否创建任务 | 整改/保留方式 | 自动化证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/network/devices` 设备管理 | `DeviceManagementView.vue` | CSV 导入、批量更新导入、自定义 SecureCRT 模板选择 | 导入 | 用户选择文件；补齐每次处理后清空 input | 文件选择 | 用户所选文件只用于上传/预检 | 仅确认业务写入时创建相应任务 | 保留用户触发的 file input；取消不调用预检 | `DeviceManagementView*.test.ts`、`exportEntryAudit.test.ts` |
| `/network/devices` 设备管理 | 同上 | 设备 CSV、导入模板、SecureCRT 会话、诊断包 | 导出 | 页面私有路径绑定/轮询 → 共享协调器 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `devices.*` 四个固定动作；同会话恢复，失败可换路径 | `useUserSelectedExport.test.ts`、页面测试、静态审计 |
| `/devices/:deviceId` 设备详情 | `DeviceDetailPanel.vue` | 保存已有配置 Artifact | 已有文件 | 保持按用户点击下载 | 点击时一次“另存为” | 用户路径 | 否 | 无任务预绑定；历史/既有 Artifact 手动保存 | `DeviceDetailPanel.test.ts` |
| `/ac-management/fit-aps` FIT-AP | `AcManagementView.vue` | FIT-AP 资源 XLSX | 导出 | 先创建任务且完成后突然弹窗 → 先选路径再建任务 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `ac.fit_ap_resources`；删除完成后自动 Save As | `AcManagementView.test.ts`、协调器测试 |
| `/ac-management/fit-aps` FIT-AP | `AcOmniPeekExportDialog.vue` | OmniPeek `.nam` 名称表 | 导出 | 已正确预选目录/文件 → 保持专用流程 | 创建任务前选择 | 用户所选目录和文件 | 确认路径后创建 | 专用目录、文件授权和完整性校验，不并入通用动作注册表 | `exportEntryAudit.test.ts` 的具名例外及既有 OmniPeek 测试 |
| `/ac-management/extensions` AP 扩展 | `AcWebParityView.vue` | CSV/XLSX 导入预览与应用 | 导入 | 用户选择文件；补齐清空 input | 文件选择 | 用户所选文件只用于预览 | 预览不创建；确认应用创建 | 取消不预览，后端继续校验契约 | 静态审计及 AC 页面测试 |
| `/ac-management/extensions` AP 扩展 | 同上 | 扩展资料 XLSX | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `ac.extensions` | `exportEntryAudit.test.ts`、协调器测试 |
| `/rail-transit/base-data` 基础资料 | `RailTransitBaseDataView.vue` | 线路站点/区间模板导入、基础资料导入、轨旁 AP 导入 | 导入 | 保持用户 file input；确认同名重选 | 文件选择 | 用户所选文件只用于预览 | 预览不创建；确认写入按原业务契约 | 每个 change handler 清空 input；后端 schema/字段校验不变 | 静态审计及既有基础资料测试 |
| `/rail-transit/base-data` 基础资料 | 同上 | 线路站点/区间模板、正式基础资料 | 直接下载 | 保持用户点击时调用受控下载 | 点击时一次“另存为” | 用户路径 | 否 | 现成响应不创建 Export Task；Browser 只报告开始 | 既有页面/API 测试、平台下载测试 |
| `/rail-transit/base-data` 轨旁 AP 基础资料 | 同上 | 模板、当前资料、重命名命令 | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `rail.trackside_base_*`、`rail.trackside_rename_commands` | 静态审计、协调器测试 |
| `/rail-transit/base-data?tab=trackside-ap-planning` | `TracksideApPlanningTab.vue` | 规划模板导入 | 导入 | 保持用户选择；补齐同名重选 | 文件选择 | 用户所选文件只用于预览 | 否 | input 清空，后端预览/应用契约不变 | `TracksideApPlanningTab.behavior.test.ts`、静态审计 |
| 同上 | 同上 | 规划模板、当前规划 | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `rail.trackside_plan_template/current`；移除任务完成自动下载 | 行为测试、静态审计 |
| `/rail-transit/train-online` 列车在线 | `VehicleMrOnlineView.vue` | MR 映射模板导入 | 导入 | 保持用户选择并清空 input | 文件选择 | 用户所选文件只用于预览 | 否 | 取消不调用导入 API | 静态审计及既有页面测试 |
| `/rail-transit/train-online` 列车在线 | 同上 | 列车经过历史、MR 映射模板 | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `rail.vehicle_history/mapping_template` | 静态审计、协调器测试 |
| `/rail-transit/ground-unattended` | `GroundUnattendedView.vue` | 已生成摘要/归档下载 | 已有文件 | 保持按用户点击下载 | 点击时一次“另存为” | 用户路径 | 下载动作不新建任务 | 归档是受管业务结果，导出副本仍由用户选择 | 既有地面无人值守测试 |
| `/rail-transit/train-communication` | `CarNetworkPointTableDialog.vue` | 车内通信点表导入 | 导入 | 保持用户选择并清空 input | 文件选择 | 用户所选文件只用于预览 | 否 | 取消不预检，同名可重选 | 静态审计及车内通信测试 |
| `/rail-transit/train-communication` | 同上 | 点表 CSV/XLSX | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `rail.car_network_points_csv/xlsx` | 静态审计、协调器测试 |
| `/rail-transit/trackside-ap-business` | `TracksideApBusinessView.vue` | 轨旁 AP 业务表 | 导出 | 任务完成/恢复后自动 Save As → 点击时先选路径 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | 删除页面私有 auto-save storage/watch；历史任务不自动弹窗 | `TracksideApBusinessView.test.ts`、协调器测试 |
| `/rail-transit/mesh-analysis` | `MeshAnalysisView.vue` | MESH 文件、多文件、文件夹导入 | 导入 | 保持用户触发的 file/multiple/webkitdirectory | 文件或文件夹选择 | 仅用户选中的 FileList | 预览/确认按原流程 | 取消不 prepare；清空 input；不扫描未选目录 | `MeshAnalysisView.behavior.test.ts`、静态审计 |
| `/rail-transit/mesh-analysis` | 同上 | 分析报告、链路明细 | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `rail.mesh_report/mesh_link_details` | 页面行为测试、协调器测试 |
| `/rail-transit/mesh-analysis` | 同上、Task Center | 历史报告/明细 Artifact | 历史文件 | 保持用户点击另存 | 点击时一次“另存为” | 用户路径 | 否 | 未绑定历史任务不自动保存 | 协调器恢复测试、Task Center 测试 |
| `/rail-transit/online-mr-analysis` | `OnlineMrAnalysisView.vue` | Online MR 分析报告 | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `rail.online_mr_report` | `OnlineMrAnalysisView.test.ts`、静态审计 |
| `/config-center` 配置采集 | `ConfigCollectionView.vue` | 配置差异 `.diff`、快照 ZIP | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `config.diff/snapshots` | `ConfigCollectionView.test.ts`、协调器测试 |
| `/config-center` 配置采集 | 同上 | 单个已有配置/结果 Artifact | 已有文件 | 保持用户点击下载 | 点击时一次“另存为” | 用户路径 | 否 | 未预绑定的现成 Artifact 手动保存 | 既有配置采集测试、Task Center 测试 |
| `/device-files` 文件管理 | `FileManagementView.vue` | 远程 SFTP 批量下载、重试、MESH 归档 | 受管下载 | 保持受管文件区，不逐文件 Save As | 不弹最终导出窗口 | 页面显示的受管 `local_path` | 创建持久下载任务 | 明确例外：需保持批量、断点/重试、队列、自动归档/导入 | `FileManagementView*.test.ts`、静态例外测试 |
| `/network-tools/toolbox` | `NetworkToolboxPanel.vue` | 工具结果 CSV/XLSX | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `network.toolbox_csv/xlsx` | 静态审计、协调器测试 |
| `/network-tools/wireless-scan` | `WirelessScanPanel.vue` | 扫描结果 CSV/XLSX | 导出 | 直接提交任务 → 先选路径再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `network.wireless_scan_csv/xlsx` | 静态审计、协调器测试 |
| `/tools` 工具集 | `ExternalToolEditorDialog.vue` | 选择 EXE、工作目录和自定义图标 | 本地资源选择 | 最新 `main` 已使用 Electron 专用选择器 → 保持 | Main 文件/目录选择 | Electron userData 中保存经选择和复验的工具注册信息；图标复制到专用缓存 | 否 | 取消不更新表单；Renderer 不手输任意程序路径后直接启动，启动只传工具 UUID | `ExternalToolEditorDialog.test.ts`、静态审计 |
| `/tasks` 任务中心 | `TaskDetailDrawer.vue` | 当前会话绑定 Artifact | 保存/重试 | 页面各自处理 → 全局识别绑定状态 | 首次已预选；失败重试才再弹 | 原授权路径或重新选择路径 | 否 | 就绪直接写入；失败复用原 Artifact | `useUserSelectedExport.test.ts`、Task Center 测试 |
| `/tasks` 任务中心 | 同上 | 历史 Artifact / 保存导出表格 | 历史文件 | 保持手动另存 | 点击时一次“另存为” | 用户路径 | 否 | 没有显式绑定时绝不自动提示/保存 | 协调器恢复测试、Task Center 测试 |
| `/settings` 局点与数据 | `SiteStoragePanel.vue` | 局点包导入 | 导入 | 已正确使用 `selectSitePackage` → 保持 | Main 文件选择 | Main 授权路径 | 选择并确认后按原流程 | 取消不调用 `importSite`，敏感/迁移包契约不变 | `exportEntryAudit.test.ts` 的专用流程检查及既有存储测试 |
| `/settings` 局点与数据 | 同上 | 完整迁移包、脱敏包、现场/回传包导出 | 导出 | 已正确使用专用目标选择 → 保持 | 创建导出前选择 | Main 授权路径 | 按既有包流程 | `selectSiteExportDestination` 保留专用敏感提示和包契约 | 静态审计及既有存储测试 |
| `/command-reference` | `CommandReferenceView.vue` | 命令说明 Markdown | 导出 | 直接创建任务 → 先选 `.md` 再提交 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `command-reference.markdown` | `CommandReferenceView.test.ts`、协调器测试 |
| `/logs` | `SystemMaintenanceView.vue` | 应用日志 CSV、开源清单 TXT/XLSX | 导出 | 先创建任务再处理 Artifact → 先选路径再建任务 | 点击后立即“另存为” | Main 授权的用户路径 | 确认路径后创建 | `system.logs/open_source_*` | `SystemMaintenanceView.test.ts`、协调器测试 |

以下可见路由经扫描没有用户文件导入、最终导出或 Artifact 保存入口：`/`、`/rail-transit/wireless-dashboard`、`/rail-transit/online-mr`、`/network-tools/traffic`、`/agents`。工具集虽不导入业务数据，但其 EXE、目录和图标选择已作为本地资源交互单列。Online MR 的 Agent 包同步/安全导入属于受控采集链内部收口，不是用户从任意本地路径发起的导入；本轮未改变其包校验或数据目录。重定向路由不承载独立页面动作。

## 硬编码路径与写文件审计

| 名称/路径类别 | 扫描结果 | 结论 |
| --- | --- | --- |
| `NetConsoleExportTest`、`NetConsoleBuildLogs` | 正式源码、测试和构建脚本均无运行路径命中；名称只出现在防回归审计规则时允许 | 不是正式 UI 输出目录，不新增兼容或删除逻辑 |
| `D:\NetConsoleTestData\<run-id>` | Runtime TEST、pytest、Electron dev/smoke/package smoke 的强制隔离根 | 仅测试/显式隔离运行；不是用户最终导出路径 |
| `D:\NetConsoleData` | 正式业务数据根、Artifact Store、任务日志、SQLite、采集包和受管文件区 | 允许内部受管数据；禁止作为 UI 最终导出副本的默认位置 |
| `exports`、`outputs`、`reports` | 领域 Worker/Artifact Store 内部结果、测试 fixture 或构建输出存在受控使用 | 只作为内部 Artifact/受管业务结果；用户副本必须经保存选择 |
| `Downloads`、`Documents`、Desktop | Web/Vue 正式生产源码没有最终导出默认路径 | 禁止新增；静态测试持续扫描 |
| `process.cwd()`、`Path.cwd()` | 个别测试用来定位测试自身；正式运行路径受项目架构门禁限制 | 不作为源码、配置、运行数据或最终导出位置 |
| Renderer `document.createElement('a')` | 只允许在 `platform/browser-adapter.ts` | Electron Host 不得回退；Browser 仅报告开始下载 |
| Python `open/write_text/write_bytes/os.replace` | Worker、Repository、Artifact Store、日志、缓存、测试/构建脚本存在受控写入 | 未发现绕过 UI 选择直接生成用户最终副本的新增路径；本轮不改 Backend/Worker/数据库 |

静态审计测试还把全部共享协调器动作、两个专用预选流程、所有 file input 处理器和唯一受管 SFTP 例外列成类型化清单；新增未登记动作或生产源码中的测试/用户默认导出路径会使测试失败。

## 人工验收状态

自动测试可以验证取消不提交、路径绑定、Artifact 类型/大小/SHA-256 参数、保存失败重试、Browser `started`、同会话恢复和历史任务不弹窗，但不能代替 Windows 原生对话框和真实设备：

- `DESKTOP_SMOKE_PENDING`：设备、FIT-AP、OmniPeek、轨旁 AP、基础资料、MESH、配置、命令说明、日志、开源清单和局点包的 Windows Save As/File/Folder 人工链路。
- `REAL_DEVICE_PENDING`：真实 AC/AP、MESH 日志现场样本、Online MR/Agent、SFTP 队列和 Office/WPS 打开结果。

人工验收时每个任务型导出需确认：点击立即弹窗、取消无任务、确认后仅一个任务、完成后不再弹窗、文件只出现在用户路径、大小/SHA-256 校验有效、失败换路径不重建任务、历史 Artifact 可手动另存。每个导入需确认：取消无预检/任务、所选名称和数量正确、同名重选有效、文件夹只包含用户选择内容。
