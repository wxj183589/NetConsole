# NetConsole Phase 8.1 总验收

状态：**PARTIAL**

本轮最终 Full Gate 已在提交 `11061806` 上通过。Python `5878 passed / 3 skipped`，Renderer `224 files / 1616 tests`，Electron `41 files / 326 tests`，架构 `12/12`，文档门禁 `22 passed`，package smoke PASS。该结果覆盖自动化质量门禁，不改变真实设备、Windows 安装态、现场故障注入、外部终端自动认证和长时间性能项目的未验收状态。

[Phase 8 / 8.1 总任务台账](./PHASE8_MASTER_TRACKER.md)涵盖 P8-01 至 P8-23 的原始需求、实施、证据、测试入口及尚未完成的验收。下面保留真实数据专项审计结果，并记录实际产品回放进度。

## 真实产品回放

| 数据 | 隔离 Backend 健康 | Electron 交互就绪 | 局点 |
| --- | --- | --- | --- |
| HZL9 | 5.54 秒 | 6.29 秒 | `hzdt-09` |
| HZL10 | 17.49 秒 | 23.30 秒 | `hzl10` |

两次使用 `NETCONSOLE_COLLECTION_MODE=disabled`，各为单次启动读数。复制范围为启动配置、设备及任务数据库、Ground 历史和 Online MR 解析数据库。首次启动拒绝使用记录原位置的存储清单，隔离副本保留原清单并由应用生成新清单后成功启动。现场及压力测试仍见总台账。

两条线均进入设备管理、FIT-AP、轨旁 AP、Online MR 分析、任务中心和 Ground，并操作 Ground 的 Heartbeat、Quick Ping、Syslog、时间轴、AC-Mesh-Link 和归档页。HZL9 设备管理显示 117 台设备，Ground 可选择归档运行。HZL10 的实际回放复现了旧归档失败出现在实时页的问题，修复后重新打开页面显示「暂无运行」。历史失败记录继续保存在原有数据中。

截图和 Ground 导航记录见 Workspace 的 `reports/diagnostic/phase8-real-replay/pages/`。最终 Full Gate 日志见 `reports/tests/phase8-integrated-11061806/full-gate.log`，首次 Gate 发现的 Renderer 类型错误、文档目录缺失和 Syslog 端口回归均已修复。

## 历史审计证据

本阶段完成杭州地铁 9 号线和 10 号线真实运行数据的本地隔离解压、压缩包 SHA-256 核对、DataRoot 结构审计、SQLite 只读 Schema/行数审计和对比报告。原始压缩包保持原位，未上传、未修改或删除。

## 证据报告

- [HZL9_REAL_DATA_ACCEPTANCE.md](./real-data-20261125/HZL9_REAL_DATA_ACCEPTANCE.md)
- [HZL10_REAL_DATA_ACCEPTANCE.md](./real-data-20261125/HZL10_REAL_DATA_ACCEPTANCE.md)
- [REAL_DATA_COMPARISON.md](./real-data-20261125/REAL_DATA_COMPARISON.md)

## 状态边界

- 结构审计和 SQLite 只读查询：PASS。
- HZL9 Ground、MESH、Quick Ping、AP/设备和任务历史具备真实记录，结果为 PASS_WITH_EVIDENCE_CAVEATS。
- HZL10 Ground、MESH、AP/设备和车辆 MR 具备真实记录。当前 Ground 数据无 Quick Ping 记录，标记 NOT AVAILABLE。
- 本节历史审计未覆盖实际应用。当前源码启动证据见上表，Windows 安装态、完整 GUI 回放、页面性能、内存/CPU、写入式迁移与回滚保持待验收。Full Gate 和冻结制品 smoke 已通过，不能替代这些现场验收。

## 数据安全

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=0`、`MAINTENANCE_AUTHORIZED=NO`。

验证数据仅位于 Workspace 的 `test-data/NetConsole/real-data-20261125-hz9` 和 `real-data-20261125-hzl10`，未纳入 Git。
