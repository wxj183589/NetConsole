# R2.2 Heartbeat 实施前审计

日期：2026-11-10。Agent：codex-A。审计时 HEAD：3eed9e87，上一阶段基线 b3ccb1bd；分支 codex-A/global-dataroot-disk-policy。本文件先于业务代码修改生成。

## 真实调用链

1. FastAPI `build_ground_runtime` 创建每个 Site 的 Repository、Ground Supervisor 和 Application Service；lifespan start/close，Site rebind 释放旧组合根。
2. Ground 构造 FleetPingSupervisor、HeartbeatStateEngine、TrainConnectivityAggregator 和 PingLossTracker 队列；DeepScheduler 引用同一个 Fleet。
3. `_start_run`、`_recover_on_start` 调用 `_start_fleet_ping`。其按 Run ID 恢复快照，原始数据放入 Ground active/run_date。`_tick` 无 Run/关闭计划时返回；库存和心跳落库主要在 AC 分类路径刷新。
4. `_finalize_run` 明确 stop Fleet 并 quiesce 心跳；`close` 再停止。`_shutdown_active_run` 只记录 Backend 暂停收口事件。因此现有实现不能满足无 Run 常驻。
5. 库存同步已能从轨交 MR 基础资料和设备 UUID/主备地址构建，不要求 AC 在线或 SSH 凭据。当前 heartbeat 查询还会触发同步；页面不是实际 Ping 执行者，但轮询受 Ground RUNNING 限制。
6. SQLite 心跳快照、丢包、汇总和 raw 均带 run_id（无强制 Run 外键）；可复用持久命名空间但不能伪造业务 Run。Raw 查询部分校验 get_run，需适配；旧 Run 历史必须保留。
7. 状态引擎已有主备 IP 独立统计、恢复、目标冲突处理；持久化已有 256 轮转批次、4096 有界事件队列和重试保留。不再实现第二套判断逻辑。

## Consumer Audit / L4

| 契约 | 写入 / 缓存 | 读取 / 展示 / 清理 | 本轮处理 |
| --- | --- | --- | --- |
| Fleet 生命周期 | Ground 创建，分片线程回调；内存桶 | DeepScheduler、health、Ground stop | 独立 Heartbeat owner，Ground 仅 enrichment；stop 不再结束心跳 |
| 心跳状态/丢包 | state engine、bounded dirty/event queue -> SQLite | heartbeat、MR drawer、loss/series | 稳定 resident stream；跨 Run 和 Backend 恢复 |
| raw/summary | Fleet、RawStreamWriter、压缩线程 | raw query、归档、删除、导出 | resident 独立目录，保留旧 Run 读契约；不归 Ground 日归档清理 |
| Profile / 独立配置 | Repository -> DTO | Settings / API / frozen Run | 最终采用独立配置 JSON 表；首次原子采用旧 Fleet 参数，此后独立热更新 |
| inventory | TrainInventorySyncService | API、engine、Syslog 身份投影 | 后台周期检查源变更；页面只读；显式 clear 仍有效 |
| Renderer | Abort/generation、可见性轮询 | HeartbeatPage、Settings、useGroundUnattended | 查询/启停与 Run 脱钩，不让卸载控制 Backend |
| Syslog | 批次 FIFO/ownership/恢复 | Job Center、MR 状态 | 不修改该系统；跑 R2.1 回归 |

兼容风险：旧 Run 查询、每日 raw 归档与常驻目录边界；Backend 恢复时采样间隙不当作确认离线；临时 SQLite 锁/事件满队列必须可见；失败分片不能显示正常。实施时将原计划的 Profile additive columns 调整为独立 additive 配置表，保留旧 Profile 与冻结 Run 配置。

并行修改：仅一个 worktree；既有 16 个 DataRoot/SiteStorage/AGENTS 等 dirty 文件均排除。HEAD 的 MESH 修改保留。Workspace 检查最初被未跟踪 NVIDIA Corporation/umdlogs 阻断，用户明确授权后核验为空目录并移动到 Workspace/temp/analysis/r2-2-heartbeat；复查 PASS。

## 回归矩阵与边界

实施后运行：Ground schedule/API/heartbeat state/inventory/AC resident/Fleet/raw/archive/deep/Syslog；Renderer Heartbeat/Settings/useGround 定向测试与 build；Ruff、Workspace、文档和 diff 检查。L4 registry 还要求 architecture-guards、electron-contract、main-contract-smoke、python-full；最终报告逐项记录实际执行和缺口。当前无合并授权，不 Push/Merge；合并 main 后仍须重跑完整 Local Gate。

400 MR/双 IP 使用合成数据和可控 runner，不接触现场；短时自动化不能替代真实 8h 或 Electron GUI。GUI、长稳、真实设备未运行时不得标记 PASS。
