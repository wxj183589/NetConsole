# NetConsole Phase 8.1 真实运行数据专项总验收

状态：**PARTIAL**

本阶段完成杭州地铁 9 号线和 10 号线真实运行数据的本地隔离解压、压缩包 SHA-256 核对、DataRoot 结构审计、SQLite 只读 Schema/行数审计和对比报告。原始压缩包保持原位，未上传、未修改或删除。

## 证据报告

- [HZL9_REAL_DATA_ACCEPTANCE.md](./real-data-20261125/HZL9_REAL_DATA_ACCEPTANCE.md)
- [HZL10_REAL_DATA_ACCEPTANCE.md](./real-data-20261125/HZL10_REAL_DATA_ACCEPTANCE.md)
- [REAL_DATA_COMPARISON.md](./real-data-20261125/REAL_DATA_COMPARISON.md)

## 状态边界

- 结构审计和 SQLite 只读查询：PASS。
- HZL9 Ground、MESH、Quick Ping、AP/设备和任务历史具备真实记录，结果为 PASS_WITH_EVIDENCE_CAVEATS。
- HZL10 Ground、MESH、AP/设备和车辆 MR 具备真实记录。当前 Ground 数据无 Quick Ping 记录，标记 NOT AVAILABLE。
- Electron/Backend 真实 GUI 回放、Windows 安装态、冷启动、页面性能、内存/CPU、写入式迁移与回滚：NOT VERIFIED。

## 数据安全

`PRODUCTION_DATA_MODIFIED=0`、`DEV_REAL_BUSINESS_DATA_MODIFIED=0`、`DATABASES_REMOVED=0`、`REAL_DEVICE_CONFIGURATION_WRITES=0`、`MAINTENANCE_AUTHORIZED=NO`。

验证数据仅位于 Workspace 的 `test-data/NetConsole/real-data-20261125-hz9` 和 `real-data-20261125-hzl10`，未纳入 Git。
