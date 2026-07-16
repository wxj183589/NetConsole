# 配置采集中心 Qt / Electron 对等矩阵

## 事实源与状态

- Qt 页面：`src/netconsole/ui/pages/config_collection_center_page.py`
- Qt Worker：`src/netconsole/ui/config_lifecycle_worker.py`
- 共享业务：`src/netconsole/services/config_lifecycle_service.py`
- 持久化：`src/netconsole/repositories/config_snapshot_repository.py`
- Qt 双栏差异：`src/netconsole/ui/widgets/config_diff_viewer.py`
- Electron 页面：`apps/web/src/views/config-collection/ConfigCollectionView.vue`
- Application Service / Router / DTO：`src/netconsole/services/config_collection_web_service.py`、`src/netconsole/backend/api/config_collection_router.py`、`src/netconsole/models/api/config_collection.py`

当前导航状态为 `REAL_DEVICE_PENDING`，不是 `COMPLETE`。自动化已覆盖不连接真实设备的服务、API、Vue 类型构建、取消检查点、失败与重启恢复；H3C SSH/Telnet、现场权限、设备返回差异及 Electron 人工点击仍需主工作树验收。Qt 页面继续保留为事实源和回退入口。

## 完整入口矩阵

| Qt 有效入口/行为 | Qt 事实行为 | Electron 实际闭环 | 自动化证据 | 当前边界 |
| --- | --- | --- | --- | --- |
| 刷新设备、搜索、分组、分页、选择 | 从当前局点设备库读取 H3C 设备 | Vue → Config Router → `ConfigCollectionApplicationService.list_devices` → `DeviceRepository` | `tests/test_config_collection_web_api.py`、`ConfigCollectionView.test.ts` | 无设备连接 |
| 单设备配置采集 | 固定执行 `screen-length disable`、`display current-configuration`、`display saved-configuration` | Vue 提交持久 Task → config handler → `ConfigLifecycleService.fetch_configs` → running/saved/diff 三类快照和共享 raw/jsonl 审计 | `tests/test_config_lifecycle_service.py`、`tests/test_config_collection_web_api.py` | `REAL_DEVICE_PENDING` |
| 批量配置采集 | 逐设备执行并隔离失败 | 每台设备独立持久 Task；页面轮询终态并刷新快照，任务详情进入共享任务窗口 | `tests/test_config_collection_web_api.py` | 真实批量设备待验收 |
| 保存配置 | 明确执行 `save force`，需确认 | 服务端签发一次性确认 token/digest；Worker 只执行 `save force` 并写命令审计，不采集或伪造 saved-configuration 快照 | `tests/test_config_lifecycle_service.py`、`tests/test_config_collection_web_api.py` | 设备权限和回显待验收 |
| 批量保存配置 | 逐设备执行、保留失败项 | 单一持久 Task，逐设备检查点；可在项目边界取消，强停时当前项为 unknown、剩余项为 not_started，重启恢复结构化结果 | `tests/test_config_collection_web_api.py` | 共享任务窗口须放开 config 不可逆任务的停止能力 |
| running/saved/diff 历史和类型筛选 | 按设备、类型和时间列出快照 | Repository 查询；Application Service 验证快照仍位于受控目录后返回 DTO | `tests/test_config_collection_web_api.py` | 无 |
| 查看快照正文 | 后台读取，running/saved 清理 CLI 噪声 | 持久 Task 调用共享 Service，超长正文截断提示；完整内容仍可下载 | `tests/test_config_collection_web_api.py`、`tests/test_config_job_database_paths.py` | 无 |
| 下载单个快照 | Qt 复制到用户选择路径 | Electron Runtime Adapter 通过受控 Artifact ID 下载，main 负责系统保存对话框和原子替换 | `configCollection.test.ts`、Electron Bridge 集成分支测试 | 消费共享 Native Bridge，不在本分支修改 |
| 删除一个或多个快照 | 用户确认后删除记录和文件 | 服务端一次性确认 → 持久 Task → Service/Repository；共享 raw/jsonl 仅在最后一个引用删除后清理，越界/符号链接路径不删除 | `tests/test_config_lifecycle_service.py`、`tests/test_config_collection_web_api.py` | 共享任务窗口停止能力依赖见下节 |
| 最新 running/saved 比较 | 同设备最新两类快照 | config handler 直接调用共享 Service，返回左右正文、统一 diff、逐行双栏数据和摘要 | `tests/test_config_collection_web_api.py` | 无 |
| 任意两快照比较 | 支持同设备、跨设备和不同历史时间 | 选中顺序固定为 left → right；API 返回 left/right label、text、diff rows、summary | `tests/test_config_collection_web_api.py` | 无 |
| 两设备最新 running 比较 | 两台设备都必须已有 running 快照 | 读取两设备最新 running，返回双栏差异和结构差异，不连接设备 | `tests/test_config_lifecycle_service.py`、`tests/test_config_collection_web_api.py` | 无 |
| 双栏差异 | 左右行号、正文、`+/-/~/=` 和新增/删除/修改摘要 | Qt 的 `SequenceMatcher` 行对齐算法下沉到共享 Service；Vue 渲染相同状态和高对比色 | `tests/test_config_diff_viewer.py`、`tests/test_config_lifecycle_service.py`、Vue build | 无 |
| 差异筛选与导航 | Qt 可浏览完整双栏结果 | Vue 支持全部/新增/删除/修改筛选、上一处/下一处滚动定位；API 同时接受 added/removed/modified 过滤 | `tests/test_config_collection_web_api.py`、`ConfigCollectionView.test.ts` | 无 |
| 导出当前差异 | Qt 进入 Export Process 生成 diff/text | Vue 提交配置导出 Task → 独立 Export Process → 受控 Artifact manifest/hash/size → Electron 下载 | `tests/test_config_collection_web_api.py` | 无 |
| 批量导出快照 ZIP | Qt 进入 Export Process，包含快照和失败说明 | Vue 提交快照 ZIP Task → 独立 Export Process → 受控 Artifact；无浏览器路径入参 | `tests/test_config_collection_web_api.py` | 无 |
| 打开配置/导出目录 | Qt 打开当前配置目录或结果目录 | DesktopActionService 只接受当前局点已登记的 `config_snapshots` / `config_exports` 目录 ID | `tests/test_config_collection_web_api.py`、`ConfigCollectionView.test.ts` | Electron Desktop 才执行；Server 明确拒绝 |
| 任务进度、日志、取消、失败和重启恢复 | Qt Worker/Job 展示进度和失败 | 配置主页只显示运行/异常计数并打开独立共享任务窗口；TaskRepository 持久化，检查点恢复不可逆批次，Artifact 由共享任务窗口交付 | `tests/test_config_collection_web_api.py` | 共享窗口依赖见下节 |
| 配置导入 | Qt 配置采集中心没有配置导入入口 | 不新增 Electron 配置导入入口 | 不适用 | 保持 1:1，不以新设计扩范围 |

## 共享任务窗口集成依赖

本分支只消费 `window.netconsoleDesktop.openTaskWindow({ module: "config" })`，未修改 Job Center、TaskRepository、TaskApplicationService、公共 Artifact 或 Native Bridge。共享分支 `codex/electron-task-center-window` 集成时还需一处最小兼容补丁：

- 文件：`src/netconsole/services/job_center/query_service.py`
- 当前行为：`_cancel_capability` 对 `IRREVERSIBLE_CONFIG_TASK_TYPES` 的 `RUNNING/STOPPING` 返回不可取消。
- 需要行为：配置 Task 在 `PENDING/STARTING/RUNNING` 且 local 状态返回可取消，`STOPPING` 显示已请求停止；配置 Worker 已在每个设备/快照边界调用 `check_cancelled()`，并用检查点记录 completed/current/pending，强停或重启可交付 unknown/not_started 结果。

未合入该共享补丁前，配置 API 的取消与恢复契约已可用，但统一任务窗口按钮仍会被 capability 查询禁用，因此不得将集成结果标记为 `COMPLETE`。

## 数据与安全边界

- 未修改数据库 schema；继续使用既有 `devices.db.config_snapshots`，设备与 FIT-AP 主库兼容。
- `save force` 审计 raw log 不等于 saved-configuration 快照。
- running/saved/diff 同批快照共享 raw log；删除其中一条不能删除其他快照仍引用的审计。
- Router 只做 DTO、Feature Gate、异常映射和 Application Service 调用；Vue 不持有采集、保存、删除或差异业务规则。
- 所有正式导出继续进入独立 Export Process；页面只消费 Artifact ID。
