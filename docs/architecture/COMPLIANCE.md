# 架构一致性审计与遗留业务逻辑回收

## 文档定位

本文定义 Electron-only 架构的永久一致性规则。当前 Guard、精确分类配置和稳定产品架构声明已经形成；2026-07 的建立基线见[架构一致性报告](../archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md)。Guard 通过不等于 Electron 视觉、真实设备、最终制品或业务验收完成。

目标是持续验证实际代码符合 `Electron Main + Preload + Vue + FastAPI + Python Core` 分层。原 Qt 页面、Worker、Signal 和 Timer 回调的业务逻辑去向已经冻结在 archive 与 Git 历史中，不再作为活动迁移任务。

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

`device.inventory.collect` 是首个进入版本化 Profile 的生产操作，定义于 `resources/device_command_profiles.json`，发布时受控复制到 Backend 的 `netconsole/assets/device_command_profiles.json`。H3C 与 ZTE 设备详情采集通过 `src/netconsole/services/device_command_profile_service.py` 按 `vendor / role / platform / software_version` 选择 Profile；当前只对 H3C `switch` / `wireless_controller` / `mobile_router` 受控推断 Comware、对 ZTE `switch` 受控推断 ZXR10，不代表已从设备事实探测未知平台。H3C 无线控制器使用独立 selector 的通用只读 Profile，复用既有 Comware 命令和 parser/DTO contract，不改变设备角色，也不接管 AC/FIT-AP 专用业务。精确软件版本只接受受信探测结果的显式参数，不读取用户可编辑备注；无可信版本时只允许明确声明的 generic 只读 Profile。每个固定 step 保存顺序、输出 selector、parser/DTO contract、只读风险和验证证据，Operation schema 与 Guard 校验固定命令序列。ZTE generic Profile v3 的固定七命令已于 2026-07-28 在两台车站 C89E-4 V1.9.0 上完成只读验证；`show opticalinfo brief` 成功后，Application Service 只根据 Parser 返回的在线接口生成 `show opticalinfo <safe-interface>`，并再次经过接口安全构造器和 Guard。离线接口跳过，单接口失败保留摘要并形成部分成功；动态 detail 当前只有 fixture 自动化证据，不能沿用固定七命令的 `REAL_DEVICE_VERIFIED` 结论，其他 ZXR10 型号和 Release 也不据此视为已验证。

该切片不代表命令平台全量完成。AC 专项、Online MR 专项采集、配置、诊断、文件管理及 Agent sidecar 的生产命令仍需逐域迁移；Huawei 与未匹配的 ZTE 型号必须失败关闭。`src/netconsole/services/command_guard.py` 仍作为迁移期精确序列二次保护，不能替代 Profile resolver；ZTE 前三条核心命令失败会停止该设备，任一 LLDP 命令失败则保留有效接口/光模块和可用的另一份 LLDP 结果并标记 `partial_success`。未经确认的 ZTE LLDP 候选已退出 Guard。现场提供但未验证的 ZTE 硬件、SN、配置、文件、Ping 与 `write` 只进入命令参考，不自动进入生产 Profile。`scripts/maintenance/audit_commands.py` 对 Profile 只接受经正式 loader 验证后的完整规范化命令相等；发布审计使用 `--strict` 时任何 deferred 项都会返回非零。

## Qt 历史迁移归档

Qt 到 Electron 的仓库迁移已经关闭。最终迁移映射保存在 `docs/archive/migrations/qt-to-electron/MIGRATION_MATRIX.md`，仅用于历史追溯；当前产品能力以 `src/netconsole/core/feature_registry.py` 为准，当前运行形态以 `config/architecture/product_architecture.json` 为准。普通技术债按领域任务处理，不再创建新的 migration wave 或全仓 cleanup phase。

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
- 运行路径、孤儿模块和稳定产品架构声明；
- 项目目录 README、仓库根运行数据和无 Qt 依赖/安装包残留。

十个公开入口为：

```text
scripts/architecture/check_architecture_boundaries.py
scripts/architecture/check_forbidden_imports.py
scripts/architecture/check_direct_sql_access.py
scripts/architecture/check_device_command_hardcoding.py
scripts/architecture/check_ui_business_logic.py
scripts/architecture/check_removed_features.py
scripts/architecture/check_runtime_paths.py
scripts/architecture/check_orphan_modules.py
scripts/architecture/check_product_architecture.py
```

如多个检查可以由一个稳定的 AST 引擎承担，可共享实现，但上述发布门必须保留可单独定位的规则 ID 和失败输出。Python 边界检查应验证 Domain、Service、Repository、Application 与 Router 的依赖方向；TypeScript 边界检查应阻止 Vue 导入 Electron Main、Main 导入 Vue Store，以及 Preload 导入业务 Service。Repository、migration、明确的数据维护脚本和测试 fixture 之外的 `sqlite3.connect`/`aiosqlite.connect` 必须失败。生产设备命令只允许出现在版本化 Command Profile；命令 fixture、Parser 样本、文档和历史 Changelog 必须通过精确路径分类，不允许放行整个 `services/`。

UI 业务逻辑扫描是启发式检查，命中必须人工分类为 `DISPLAY_ONLY`、`BUSINESS_LOGIC` 或 `FALSE_POSITIVE`，不得自动删除。SQL 和命令文本扫描也只是初筛，需结合 AST、调用图和测试样本判断；不能放行整个 `services/` 或 `apps/desktop_renderer/`。

### 当前长期基线

统一入口 `scripts/architecture/run_all.py` 维持十门基线检查；第十门校验 Electron Desktop Only 四个运行组件、权威事实源和迁移归档已关闭。历史建立过程保留在 archive，不再作为活动阶段。

- Direct SQL、UI AST、限时例外和目录职责均由当前配置与 Guard 动态校验，不在本文冻结易漂移数量。
- Command Profile 当前只有 `device.inventory.collect` 进入版本化平台。AC、MR、配置、文件等命令按各领域事实与验证状态维护；这不再被描述为 Qt→Electron 迁移阶段。

历史状态色字面量已收敛到语义 Token，对应 `WEB_STATUS_COLOR_TOKEN` 例外已删除；`check_ui_business_logic.py` 当前为 0 finding / 0 waived。Guard 已收窄规则，避免把 `--nc-text-primary` 等普通文本 Token 误判为状态色，并由单元测试固定。全局浅色/深色/跟随系统、Element Plus、ECharts 和 Electron 背景严格 IPC 已接入；最终 Electron 多尺寸、多缩放和 Windows 跟随系统视觉验收仍为 `PENDING`，自动测试不能替代视觉通过。

## 有限期例外

架构例外统一写入 `config/architecture/exceptions.yaml`。每项必须精确到规则和文件，并包含理由、责任域、创建时间、到期时间和测试；禁止通配整个目录。到期例外使 Guard 失败。

示例：

```yaml
- rule_id: UI_BUSINESS_LOGIC
  path: apps/desktop_renderer/src/utils/chart-bucket.ts
  reason: 仅进行像素级降采样，不改变业务统计值
  owner: web
  created_at: 2026-07-18
  expires_at: 2026-10-01
  test: apps/desktop_renderer/tests/chart-bucket.spec.ts
```

当前不为尚未发现的命中创建占位例外。

## 孤儿代码和数据库所有权

审计无调用 Service、无路由 Router、无注册 Handler、无引用 DTO/Parser、无入口脚本、空目录和仅有 README 的废弃业务目录。未来契约需由目录 README 说明；待迁移功能必须有 Feature 状态和计划；确认无用途的代码直接删除并依赖 Git 历史，不创建 `legacy/old/backup` 目录。

`docs/storage/DATA_LAYOUT.md` 必须为每个活动数据库记录事实源或派生数据、拥有者 Repository、生命周期、备份、迁移和清理策略，重点包括 `devices.db`、`tasks.db`、`agents.db`、`traffic_runs.sqlite`、`iperf_results.sqlite`、Online MR 会话 SQLite 和 MESH catalog/SQLite。还要检查同一业务事实是否无理由重复存储、启动是否全库扫描、connection 是否跨线程共享、是否缺少 WAL/`busy_timeout`、大查询是否分页，以及 schema 修改是否都有 migration。

## 长期发布阻塞条件

历史 E10 合规报告保留在 `docs/archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md`，不再生成新的阶段报告。以下任一项存在时不得发布：

- 活动代码仍导入 Qt，或安装包仍携带 Qt 依赖/资源/许可证；
- Vue、Electron Main/Preload 或 FastAPI Router 承载核心业务算法；
- Router 直接执行 SQL、设备连接或设备命令；
- 生产命令绕过版本化 Command Profile；
- Service/Application 反向依赖 UI、Electron 或 FastAPI；
- Repository 之外存在未经批准的活动直接数据库访问；
- 当前产品架构声明与实际运行组件或权威事实源不一致；
- SNMP Center 或无线勘测仍有活动入口；
- API 契约、目录 README、数据所有权或运行路径门缺失；
- P0/P1 架构问题未清零。

P2 如延期，必须有明确问题记录、责任人、原因、临时边界、测试和完成时间。

## 长期验证

日常修改先运行 Change Impact，再由 `python -m scripts.quality.local_gate --mode auto` 选择 FAST、CONSUMER 或 FULL。L3/L4 合并、rebase 或解决冲突后，旧结果失效；最终组合必须重新运行登记消费者套件，L4 使用 `--mode full`。发布任务另行执行适用的 Package Smoke、Windows GUI、安装升级、签名和真实设备验收。

长期标准是 UI/Router/Electron 无业务算法、Application/Service 无 UI 或协议框架反向依赖、Repository 独占活动数据库访问、Command Profile 独占生产命令定义、Parser 职责中立且版本明确。普通技术债按领域任务、Change Impact 和 Local Gate 单独处理，不再开启全仓迁移或 cleanup wave。
