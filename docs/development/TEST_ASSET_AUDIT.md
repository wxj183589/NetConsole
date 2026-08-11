# Test Asset Audit

## 范围与结论

本报告是大规模测试压缩前的第一阶段资产审计，基线为 `main@e94f2d50`。本轮不按文件名删除活跃测试，不移动 Ground/MESH/Online MR 测试，也不改变业务断言。

核心结论：

- Python 有 277 个测试文件、约 3408 个测试函数和 120273 行；Renderer 有 173 个测试文件/39854 行；Electron 有 32 个测试文件/6092 行。
- 当前测试没有直接 import Qt/PySide。历史 `test_windowing.py`、`test_fluent_integration.py`、`test_web_shell_runtime.py`、`test_online_mr_agent_packages_qt.py` 已在主线历史中删除，本轮没有新的 `DELETE_LEGACY_QT` 文件。
- 文件名包含 `web` 不表示旧 Browser 产品。当前 31 个 Python `*web*` 测试主要保护 FastAPI/Application Service 契约，不能批量删除。
- `legacy`、`migration`、`compat`、`upgrade` 仍可能保护活动维护入口、旧库升级和 L4 数据安全，必须追到生产调用和退役条件后判断。
- 第一批只确认 5 个 `MERGE_CANDIDATE`；其余 272 个暂按 `KEEP_PENDING_REVIEW` 处理。当前没有证据充分的 `DELETE_LEGACY`、`DELETE_DUPLICATE` 或 `DELETE_DEAD`。

## Python 领域分布

以下是按文件名和路径做的发现性分组，只用于安排下一轮审计，不等同于删除结论。

| 领域 | 文件数 | 第一阶段判断 |
| --- | ---: | --- |
| Devices / AC | 26 | 保留核心采集、Repository、API、AC/FIT-AP 与设备兼容契约；1 个 parity 聚合候选 |
| Rail Base / Train | 20 | 保留基础资料、列车在线、车内通信与 revision 契约；1 个 parity 聚合候选 |
| Trackside AP | 16 | 保留固定 revision 快照、Identity、LLDP/光衰和导出契约 |
| MESH | 29 | 保留 raw/derived 数据、Identity、主备链、图表语义和报告契约 |
| Online MR | 27 | 保留 SSH/会话/解析/Identity/Ping/iPerf/打包契约 |
| Ground Unattended | 16 | 当前全部保留；下一轮按 foundation/scheduler/eligibility/correlation/syslog/archive/API 合并 |
| AP Identity（文件名直接命中） | 4 | 保留 canonical、consumer architecture、shadow/diagnostics 与 query contract |
| Task / Job | 9 | 保留状态机、Worker 协议、取消、恢复、列表/详情和 Artifact 契约 |
| Export | 4 | 保留 Export Process、文件落盘、Identity diagnostics 与用户文件契约 |
| Feature | 3 | 保留 Registry、snapshot 和 Renderer gate 契约 |
| Electron backend（Python） | 2 | 保留 Backend runtime 与 API 组合契约 |
| Packaging | 3 | 保留版本、制品身份和数据根发布门 |
| 其他 | 118 | 包含 parser、storage、files、network、architecture、quality 和跨域契约；逐项审计 |
| 合计 | 277 | 不做批量删除 |

## 第一批压缩候选

| 当前文件 | 规模 | 建议长期去向 | 删除前置条件 |
| --- | ---: | --- | --- |
| `tests/test_ac_web_parity.py` | 973 行 / 22 tests | AC/FIT-AP Application/API consumer contract | 独有断言全部迁入长期领域测试且目标测试在 main 通过 |
| `tests/test_network_tools_web_parity.py` | 883 行 / 17 tests | Network Tools API/traffic/wireless contract | 移除迁移期页面对照，只保留正式 Renderer/API 行为 |
| `tests/test_rail_transit_web_parity.py` | 1920 行 / 35 tests | Rail Base、Trackside、Train、Online MR 分域 contract | 每条断言具有唯一领域 owner，不形成新的超大聚合文件 |
| `tests/test_web_parity_foundation.py` | 380 行 / 14 tests | Renderer/FastAPI 基础 contract | Browser 迁移措辞清除，保留 Electron Renderer 实际调用链 |
| `tests/test_phase2_device_connection.py` | 446 行 / 13 tests | Device Repository、Import/Export、Connection Manager、Tunnel/Netmiko contract | 历史阶段命名移除，断言分别进入稳定 owner |

四个 parity 聚合文件合计 4156 行/88 tests。`tests/web_parity_test_support.py` 是它们当前共用的 142 行 helper，只能在全部消费者完成迁移后删除或下沉，不能先删。

## Ground/MESH/Online MR 压缩方向

本轮只记录职责，不执行移动：

- Ground：收敛为 foundation、scheduler、target eligibility、ping/correlation、syslog、archive/recovery、API contract；不得丢失 raw lifecycle、调度和历史只读事实。
- MESH：按 raw import/storage、derived rebuild、Identity/remap、topology/series semantics、report/API 归组；raw 日志和派生数据库边界必须保持。
- Online MR：按 collection/session、parser/derived data、Identity/remap、traffic、report/package、API/Application Service 归组；LOCAL/AGENT 生命周期和原始事实保持独立。

压缩目标是减少重复 fixture、重复 App 组合和事故命名，不是把多个领域塞进单个 5000 行文件。

## Consumer Contract 归类

第一阶段直接复用现有测试作为 Consumer Matrix 的检查来源，不要求每个契约新增测试文件：

| 共享契约 | 现有主要证据 |
| --- | --- |
| Renderer API Client | `apps/desktop_renderer/src/api/client.test.ts` 及关键 consumer API tests |
| NcDataTable | `apps/desktop_renderer/src/components/table/*.test.ts`、`tests/test_ui_table_guards.py` |
| Dynamic Chart | `dynamic-chart-stability` Skill 指定的 chart/timeline tests 和架构门 |
| AP Identity | `test_ap_identity*.py`、MESH/Ground/Online/Trackside consumer tests |
| Task/Job | Task Application、Job Center API、Worker protocol、Export integration tests |
| Export | `test_export_process_framework.py` 及各领域正式导出测试 |
| Feature Registry | Python Registry/Profile tests、Renderer features/featureGuard tests |
| DataRoot/SQLite | paths/sites/database/database upgrade/electron runtime tests |
| Electron Bridge | Main/Preload/IPC/security/artifact-save tests |

确切命令和检查文件由 `config/architecture/change_impact_matrix.json` 维护。

## 保留与删除准则

### KEEP_CORE

仍对应当前生产业务、数据安全、设备协议、Parser、Repository、Application Service 或正式 Renderer/Electron 行为。

### KEEP_CONSUMER_CONTRACT

证明 L3/L4 共享契约对至少一个稳定消费者仍兼容。一个测试可以服务一个契约，避免重复复制同一断言。

### MERGE_CANDIDATE

断言仍有价值，但文件按迁移阶段、单次事故或跨域 parity 聚合。迁移时先落目标断言并运行新旧组合，再删除旧文件。

### DELETE_LEGACY / DELETE_DUPLICATE / DELETE_DEAD

必须同时证明生产入口不存在、当前消费者不依赖、CI/docs/fixture 无引用、保留测试已覆盖唯一契约。证据不足一律回到 `MERGE_CANDIDATE` 或 `KEEP_PENDING_REVIEW`。

## 下一轮顺序

1. 先以 Consumer Matrix 固定共享契约 owner 和验证命令。
2. 迁移 4 个 parity 聚合文件的独有断言。
3. 迁移 `test_phase2_device_connection.py` 的 4 类职责。
4. 按领域逐批合并 Ground/MESH/Online MR，每批在最终 main 组合复验。
5. 最后才删除 dead/duplicate/retired tests，并形成新的完整 baseline。

下一轮不得同时重构生产业务代码；任何业务行为差异单独开 Bug 任务。
