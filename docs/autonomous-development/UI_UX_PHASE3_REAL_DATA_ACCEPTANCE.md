# Phase 3 真实数据验收

原始下载目录只读计算 SHA-256。HZL9 RAR 为 `E357A07B28E62463BFDF913C30AE8F3E58B194D5594FCA6326F6DD5D29F90133`，HZL10 ZIP 为 `D0EDA9908782FB96690802763E9B09C334D2889BDEC902B3790AC2C6A31A8A86`。复用 Workspace 的 `phase8-replay-hz9` 和 `phase8-replay-hz10`，SQL 使用 `mode=ro` 与 `query_only`。解压副本的历史存储清单绑定其他路径，保留其绑定并使用合法回放副本。Electron 明确禁用采集。历史副本可能写入日志、锁或运行元数据，原始归档未使用作运行根。

| 模块 | HZL9 | HZL10 |
| --- | --- | --- |
| Ground | 1 个 Run。选择历史范围后，MR 回放、时间轴和历史 Syslog 请求均返回 200 | 6 个 Run，6.32 GB Ground 索引。就绪修复后进入隔离回放 |
| Heartbeat | 30 条状态，真实页面选择历史 MR 时显示 resident 数据源 | 63 条状态。Electron 选择 2026-11-21 已完成 Run 和列车 17 CT，显示 9,778 条正常样本与 100% 连通率 |
| MESH | 6,818 条 Ground 事件 | 297,397 条 Ground 事件 |
| Quick Ping | 2 个 Run，点击按需加载返回 200 | NOT AVAILABLE，专用历史表 0 条。常规 Ping 汇总 562,861 条 |
| Online MR | 2,315 条链路 | 1,999,008 条链路 |
| FIT-AP | 有相关采集记录，当前 LLDP 189 行 | 当前 LLDP 948 行 |
| 设备档案 | 117 台设备。选定 UUID 的接口、光模块、LLDP 分别为 117、80、38 条 | 76 台设备。接口和光模块历史分别为 105,958、104,858 条 |
| 配置 | NOT AVAILABLE，配置快照 0 | NOT AVAILABLE，配置快照 0 |
| 轨旁 AP | 组织设备项目、连接与区间关联表均为 0，未证实完整关系流程 | GUI 返回 1,006 条，核对了站点、AP、交换机接口及收光快照。独立光衰历史及组织详情跳转待验 |
| 任务 | 4 条任务快照 | 66 条任务快照 |
| 日志 | 隔离运行日志页可进入，历史业务分类未逐条核验 | 同左 |

所有计数、可识别时间列的范围、数据库字节数和抽样耗时见 [SQL 原始记录](../../../reports/tests/legacy-ui-ux-phase3/sql-inventory.txt)。档案的现有对端 UUID 为空，未通过名称猜测关系。[HZL9 档案](../../../reports/tests/legacy-ui-ux-phase3/HZL9-DEVICE-ARCHIVE.md)
