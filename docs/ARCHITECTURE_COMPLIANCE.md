# 架构一致性审计与遗留业务逻辑回收

## 文档定位

本文定义 Electron-only 重构最终阶段 `E10` 的永久规则。当前九个公开架构门、精确分类配置、最终迁移矩阵和阶段报告已经形成；实际结果、限时例外、未解决 P1/P2 与发布门见[架构一致性报告](archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md)及 [E10B 整改归档](archive/migrations/electron-only/2026-07-18-E10B-architecture-guards-and-remediation.md)。Guard 通过不等于 Electron 视觉、真实设备、最终制品或业务验收完成。

目标是验证实际代码符合 `Electron Main + Preload + Vue + FastAPI + Python Core` 分层，并追踪原 Qt 页面、Worker、Signal 和 Timer 回调中的有效业务逻辑去向。仅通过 Qt 关键字扫描或应用启动冒烟不能满足本阶段要求。

## 分层边界

| 层级 | 允许职责 | 禁止职责 |
| --- | --- | --- |
| Electron Main | 窗口、单实例、托盘、禁止休眠、Backend 生命周期、白名单文件对话框、打开目录/外链、通知、升级和安全 IPC | 设备命令、SSH/Telnet、数据库查询、Parser、报告、任务业务状态机和 MESH/MR/FIT-AP 规则 |
| Electron Preload | 最小强类型 IPC Bridge、参数校验和结果类型 | 文件业务、数据库、设备连接、任意命令、业务计算，或暴露 `ipcRenderer`、`fs`、`child_process` |
| Vue Renderer | 布局、表单、表格、图表、筛选、交互反馈、API/WebSocket 消费和不改变业务语义的显示格式化 | 链路判断、异常阈值、AP 匹配、资源合并、命令选择、Parser、文件解析、任务状态机和重试策略 |
| FastAPI Router | 认证授权、请求校验、DTO 转换、Application Service 调用、HTTP/WebSocket 适配和错误映射 | 直接 SQL、Repository 组合业务、SSH、设备命令、`subprocess`、目录扫描、报告和复杂状态分支 |
| Application Service | 用例编排、事务边界、任务创建/取消、跨 Service/Repository 协作、业务校验和状态转换 | PySide6、Electron、Vue、FastAPI Request/Response、QThread/QProcess 和浏览器状态 |
| Domain / Service | 核心业务规则、链路计算、设备能力、身份匹配、归一化、报告、Traffic 和 MR 规则 | UI、Electron、FastAPI 和 HTTP 响应依赖 |
| Parser | 原始文本到中立结构化数据；版本 Parser 与 Command Profile 绑定 | UI、任务控制、命令选择、数据库事务和用户提示 |
| Repository | SQLite 读写、事务、查询、分页、迁移和记录映射 | UI、设备命令、业务判定、HTTP 和 IPC |
| Command Profile | `Operation ID -> Resolver -> Versioned Profile -> Device Adapter` 的生产命令定义 | Vue、Electron、Router、页面回调和普通 Service 中散落生产命令文本 |

Vue 可以保留时间、字节、状态文字、表格列和图表坐标等显示转换。任何会改变业务结论、统计值或设备操作的逻辑必须进入 Python Core。`mesh_series_metadata.py` 等仅由页面消费的模块也必须按语义判断位置，不能以调用者数量作为留在 UI 层的依据。

## 命令平台当前接管状态

`device.inventory.collect` 是首个进入版本化 Profile 的生产操作，定义于 `resources/device_command_profiles.json`，发布时受控复制到 Backend 的 `netconsole/assets/device_command_profiles.json`。H3C 设备详情采集通过 `src/netconsole/services/device_command_profile_service.py` 按 `vendor / role / platform / software_version` 选择 Profile；当前只对 H3C `switch` 与 `mobile_router` 受控推断 Comware 平台，不代表已从设备事实探测未知平台。精确软件版本只接受受信探测结果的显式参数，不读取用户可编辑备注；exact Profile 的 fixture 主版本必须与 selector 一致，无可信版本时只允许明确声明的 generic 只读 Profile。每个 step 固定顺序、输出 selector、parser/DTO contract、只读风险和验证证据，Operation schema 与 Guard 同时校验完整 step/命令序列。应用日志记录已解析的 Operation、Profile 和兼容级别；现有 `CommandResult`、数据库 schema、API DTO 与 raw JSONL 契约不扩张，若后续需要持久化执行契约，应作为独立切片设计。当前只有 Comware 7.1 fixture 证据，generic 只读 Profile 的真实设备状态仍为 `REAL_DEVICE_PENDING`。

该切片不代表命令平台全量完成。AC、Online MR 专项采集、配置、诊断、文件管理及 Agent sidecar 的生产命令仍需逐域迁移；Huawei/ZTE 尚无真实命令或样本，必须失败关闭。`src/netconsole/services/command_guard.py` 仍作为迁移期精确序列二次保护，不能替代 Profile resolver；generic 执行会把 H3C 不识别、参数错误、歧义和权限错误回显标记为命令失败/partial。无生产调用、以用户备注猜测 V5/V7/V9 的旧 `H3CAdapter/H3CConnection/H3CCommandProfile` 已删除，未验证的 `display transceiver` 与 `display interface all` 不再作为活动命令保留。`scripts/maintenance/audit_commands.py` 对 Profile 只接受经正式 loader 验证后的完整规范化命令相等；发布审计使用 `--strict` 时任何 deferred 项都会返回非零。后续 E10 需消除 Profile 与 Guard 的命令文本重复，并对动态 SFTP username、MR Controller/Agent 双份命令和写操作 Profile 单独收口。

## Qt 历史迁移追踪

删除 Qt 文件前后都要检查 Git 历史中的 `src/netconsole/ui/`、`apps/desktop/`、Qt Page、Dialog、Worker、Table Model、Signal 和 Timer callback。重点复核 `_clicked`、`_on_*`、`_handle_*`、`_update_*`、`_refresh_*`、`_load_*`、`_parse_*`、`_calculate_*`、`_merge_*`、`_match_*`、`_resolve_*`、`_build_*` 和 `_finalize_*`。

`E10` 必须维护 `docs/architecture/MIGRATION_MATRIX.md`，逐个记录：

| 原 Qt 文件 | 原函数/类 | 分类 | 新位置 | 新测试 | 删除依据 |
| --- | --- | --- | --- | --- | --- |

分类只允许：

- `PURE_UI`：没有业务语义，可直接删除。
- `BUSINESS_MOVED`：给出永久层实现和测试。
- `ADAPTER_REPLACED`：给出 Electron、API 或 Event Hub 替代位置。
- `DEAD_CODE`：提供无入口、无引用或不可达证据。
- `FEATURE_REMOVED`：仅用于经批准正式删除的功能，例如 SNMP Center 和无线勘测。

无法确认的代码不得批量标记为 `DEAD_CODE`。功能级迁移状态只允许 `MIGRATED`、`REMOVED`、`HIDDEN_PENDING_MIGRATION` 和 `BLOCKED`；`MIGRATED` 必须同时具有新入口、新服务、新测试且旧 Qt 文件已删除。

## 专项审计域

- MESH：主备链路、链路序列、最小 RSSI、切换/乒乓、短时建链、备链统计、AP/Radio 匹配和图表业务聚合。
- Online MR：Ping1/Ping2、多 MR、共享 iPerf、Traffic 停止顺序、会话最终化、日志镜像、备注时间轴、站点区间映射、Channel Busy 和主链路判断。
- AC/FIT-AP：多命令资源合并、Radio/BBSSID 归一化、LLDP、光衰、扩展信息、点位关联和 V5/V7/V9 命令选择。
- 设备管理：去重、连接字段与凭据规则、批量策略、分组、版本识别和能力判断。
- 导出与报告：列顺序、字段裁剪、中文字段、统计规则、报告结构和文件命名。
- 数据库：事实源重复、直接 SQLite、启动全库扫描、跨线程 connection、WAL/`busy_timeout`、分页、migration、备份和清理归属。
- API：Router 直接 SQL/SSH/设备命令、裸 `dict`、缺失 DTO/错误模型、长任务绕过 Task Center、路径或令牌泄露以及 OpenAPI 覆盖。

## 自动化 Guard

`E10B` 已在 `scripts/architecture/` 建立稳定、单一实现的 Guard，覆盖：

- Python 与 TypeScript 依赖边界；
- 直接 SQL 调用位置；
- 生产设备命令硬编码；
- Vue/Electron 可疑业务逻辑；
- 已删除功能的活动入口；
- 运行路径、孤儿模块和 Qt 迁移映射；
- 项目目录 README、仓库根运行数据和无 Qt 依赖/安装包残留。

九个公开入口为：

```text
scripts/architecture/check_architecture_boundaries.py
scripts/architecture/check_forbidden_imports.py
scripts/architecture/check_direct_sql_access.py
scripts/architecture/check_device_command_hardcoding.py
scripts/architecture/check_ui_business_logic.py
scripts/architecture/check_removed_features.py
scripts/architecture/check_runtime_paths.py
scripts/architecture/check_orphan_modules.py
scripts/architecture/check_migration_map.py
```

如多个检查可以由一个稳定的 AST 引擎承担，可共享实现，但上述发布门必须保留可单独定位的规则 ID 和失败输出。Python 边界检查应验证 Domain、Service、Repository、Application 与 Router 的依赖方向；TypeScript 边界检查应阻止 Vue 导入 Electron Main、Main 导入 Vue Store，以及 Preload 导入业务 Service。Repository、migration、明确的数据维护脚本和测试 fixture 之外的 `sqlite3.connect`/`aiosqlite.connect` 必须失败。生产设备命令只允许出现在版本化 Command Profile；命令 fixture、Parser 样本、文档和历史 Changelog 必须通过精确路径分类，不允许放行整个 `services/`。

UI 业务逻辑扫描是启发式检查，命中必须人工分类为 `DISPLAY_ONLY`、`BUSINESS_LOGIC` 或 `FALSE_POSITIVE`，不得自动删除。SQL 和命令文本扫描也只是初筛，需结合 AST、调用图和测试样本判断；不能放行整个 `services/` 或 `apps/web/`。

### 当前 E10B 基线

截至 2026-07-18 当前工作树，统一入口 `scripts/architecture/run_all.py` 已建立并完成九门基线检查。可核实配置事实为：

- Direct SQL：61 个精确文件分类，包含 `REPOSITORY_REQUIRED` 12、`READ_ONLY_DATA_GATEWAY` 12、`ANALYSIS_DB_OWNER` 6、`MIGRATION_TOOL` 2、`TEST_ONLY` 29，`VIOLATION=0`；
- UI AST：32 个精确符号分类，其中 `DISPLAY_ONLY` 15、`FALSE_POSITIVE` 17，没有以函数名直接推断业务违规；
- 限时例外：38 条，全部精确到 `rule_id + path`，包括 Python 分层 14、孤儿候选 24；状态色例外已归零；
- 目录职责：建立检查时扫描 139 个维护目录，README 缺失为 0；新增目录仍必须重新运行门禁；
- Command Profile：目前只有 `device.inventory.collect` 进入版本化平台。AC、MR、配置、文件等生产命令迁移属于后续 `E11`，正式 API v1 契约治理属于后续 `E12`，均不能因九门建立而写成完成。

历史状态色字面量已收敛到语义 Token，对应 `WEB_STATUS_COLOR_TOKEN` 例外已删除；`check_ui_business_logic.py` 当前为 0 finding / 0 waived。Guard 已收窄规则，避免把 `--nc-text-primary` 等普通文本 Token 误判为状态色，并由单元测试固定。全局浅色/深色/跟随系统、Element Plus、ECharts 和 Electron 背景严格 IPC 已接入；最终 Electron 多尺寸、多缩放和 Windows 跟随系统视觉验收仍为 `PENDING`，自动测试不能替代视觉通过。

## 有限期例外

架构例外统一写入 `config/architecture/exceptions.yaml`。每项必须精确到规则和文件，并包含理由、责任域、创建时间、到期时间和测试；禁止通配整个目录。到期例外使 Guard 失败。

示例：

```yaml
- rule_id: UI_BUSINESS_LOGIC
  path: apps/web/src/utils/chart-bucket.ts
  reason: 仅进行像素级降采样，不改变业务统计值
  owner: web
  created_at: 2026-07-18
  expires_at: 2026-10-01
  test: apps/web/tests/chart-bucket.spec.ts
```

当前不为尚未发现的命中创建占位例外。

## 孤儿代码和数据库所有权

审计无调用 Service、无路由 Router、无注册 Handler、无引用 DTO/Parser、无入口脚本、空目录和仅有 README 的废弃业务目录。未来契约需由目录 README 说明；待迁移功能必须有 Feature 状态和计划；确认无用途的代码直接删除并依赖 Git 历史，不创建 `legacy/old/backup` 目录。

`docs/DATA_LAYOUT.md` 最终必须为每个活动数据库记录事实源或派生数据、拥有者 Repository、生命周期、备份、迁移和清理策略，重点包括 `devices.db`、`tasks.db`、`agents.db`、`traffic_runs.sqlite`、`iperf_results.sqlite`、Online MR 会话 SQLite 和 MESH catalog/SQLite。还要检查同一业务事实是否无理由重复存储、启动是否全库扫描、connection 是否跨线程共享、是否缺少 WAL/`busy_timeout`、大查询是否分页，以及 schema 修改是否都有 migration。

## 交付物和发布门

`E10` 必须生成 `docs/archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md`，至少逐项记录：

1. Qt 删除完整性；
2. 被删除 Qt 文件中的业务逻辑迁移结果；
3. UI 层业务逻辑命中；
4. Router 业务逻辑命中；
5. 直接 SQL 命中；
6. 设备命令硬编码命中；
7. Core 反向依赖命中；
8. 孤儿代码；
9. 无效依赖与资源；
10. 数据库重复事实和所有权；
11. API/OpenAPI 覆盖；
12. 目录 README 覆盖；
13. SNMP Center 与无线勘测删除结果；
14. 版本化 Command Profile 覆盖；
15. 架构例外；
16. 未解决项、风险等级和后续计划。

每个问题必须包含文件、行号、规则、影响、建议位置、发布阻塞状态和处理状态。报告只能基于实际 Guard、Git 历史和测试结果生成；在 E10 真正执行前不得创建内容为空或声称通过的占位报告。

以下任一项存在时不得标记 Electron-only 重构完成或发布：

- 活动代码仍导入 Qt，或安装包仍携带 Qt 依赖/资源/许可证；
- Vue、Electron Main/Preload 或 FastAPI Router 承载核心业务算法；
- Router 直接执行 SQL、设备连接或设备命令；
- 生产命令绕过版本化 Command Profile；
- Service/Application 反向依赖 UI、Electron 或 FastAPI；
- Repository 之外存在未经批准的活动直接数据库访问；
- 删除 Qt 文件中的业务逻辑没有迁移记录；
- SNMP Center 或无线勘测仍有活动入口；
- API 契约、目录 README、数据所有权或运行路径门缺失；
- P0/P1 架构问题未清零。

P2 如延期，必须有明确问题记录、责任人、原因、临时边界、测试和完成时间。

## 最终执行顺序

1. 完成 Qt 删除、无 Qt 构建和非 Qt 全量测试。
2. 扫描 Qt 关键字、依赖、安装包资源和许可证残留。
3. 建立已删除 Qt 文件业务迁移映射。
4. 检查 Python import 边界。
5. 检查 TypeScript 依赖边界。
6. 检查 Vue/Electron UI 业务逻辑并人工分类命中。
7. 检查全部 FastAPI Router 与 API DTO/OpenAPI 契约。
8. 检查直接 SQL、Repository 所有权和数据库一致性。
9. 检查生产设备命令与版本化 Command Profile。
10. 检查 SNMP Center、无线勘测和其他移除功能残留。
11. 检查目录 README、运行路径、仓库 `data/.local`、依赖和资源。
12. 检查孤儿 Service、Router、DTO、Parser、Handler 和入口。
13. 修复所有 P0/P1；P2 只有满足延期字段时可保留。
14. 运行全部架构 Guard、非 Qt 完整测试和 Electron/Vue/API 测试。
15. 生成架构合规报告和修复提交。
16. 再次运行全部 Guard 与发布检查。
17. 确认工作树干净，等待用户确认后才推送。

完成标准是 UI/Router/Electron 无业务算法、Application/Service 无 UI 或协议框架反向依赖、Repository 独占活动数据库访问、Command Profile 独占生产命令定义、Parser 职责中立且版本明确，以及全部 Qt 业务逻辑已迁移或有可核验证据地删除。
