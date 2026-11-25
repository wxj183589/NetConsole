# NetConsole Phase 8.1 总验收

状态：**PARTIAL**

[Phase 8 / 8.1 总任务台账](./PHASE8_MASTER_TRACKER.md)涵盖 P8-01 至 P8-23 的原始需求、实施、证据、测试入口及尚未完成的验收。下面保留真实数据专项审计结果，并记录实际产品回放进度。

## 真实产品回放

| 数据 | 隔离 Backend 健康 | Electron 交互就绪 | 局点 |
| --- | --- | --- | --- |
| HZL9 | 5.54 秒 | 6.29 秒 | `hzdt-09` |
| HZL10 | 17.49 秒 | 23.30 秒 | `hzl10` |

两次使用 `NETCONSOLE_COLLECTION_MODE=disabled`，各为单次启动读数。复制范围为启动配置、设备及任务数据库、Ground 历史和 Online MR 解析数据库。首次启动拒绝使用记录原位置的存储清单，隔离副本保留原清单并由应用生成新清单后成功启动。现场及压力测试仍见总台账。

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
- 本节历史审计未覆盖实际应用。当前源码启动证据见上表，Windows 安装态、完整 GUI 回放、页面性能、内存/CPU、写入式迁移与回滚保持待验收。

## 数据安全

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=0`、`MAINTENANCE_AUTHORIZED=NO`。

验证数据仅位于 Workspace 的 `test-data/NetConsole/real-data-20261125-hz9` 和 `real-data-20261125-hzl10`，未纳入 Git。
