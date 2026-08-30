# DataRoot 真实数据开发验证与生命周期审计

> 分类：HISTORICAL_RECORD。本文保留 2026-08-21 的验证事实；当前目录和 Authority 以项目 Canonical 文档为准。

本文件记录 2026-08-21 对 NetConsole 真实数据根、开发副本隔离和现有数据库生命周期策略的验证结果。它不是数据库重设计方案，也不授权删除、迁移、重建或压缩生产数据。

## 1. 历史数据根快照

以下内容是当时对两套明确标记数据根的历史现场记录，不是当前复制或重置流程授权：

| 环境 | 数据根 | `runtime_mode.json` | 允许的默认行为 |
| --- | --- | --- | --- |
| Production | `D:\NetConsoleData` | `mode=production`、`readonly_warning=true` | 采集、查看、分析、导出；维护写入默认阻止 |
| 旧 Development 目标（历史） | `D:\NetConsoleData - dev` | `mode=development`、`created_from=D:\NetConsoleData` | 历史上的真实数据副本验证目标 |
| Development Authority（现场已有） | `D:\NetConsoleData-dev` | `mode=development`、`created_from=D:\NetConsoleData` | 当前长期真实开发数据根；目录名不作为环境事实源 |

生产根和现场已有开发副本均保留完整数据根布局，包含 `config`、`sites`、`runtime`、`agents`、`migrations`、`staging`，以及各局点下的 `db`、`history`、`artifact`、`imports`、`exports`、`files` 等目录。现场已有开发副本的 `config/storage-manifest.json.data_root` 已指向自身；任务要求的带空格目标目录尚未在本轮创建。

启动不根据目录名猜测环境。持久化根必须包含有效的 `runtime_mode.json`；缺失、损坏、`test` 标记或生产根关闭只读警告时拒绝启动。测试进程仍使用显式 `RuntimeMode.TEST` 和 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`，不写持久化 marker。

Backend 启动日志和 `/api/health` 返回数据根、`PRODUCTION`/`DEVELOPMENT`/`TEST` 标签及生产写入授权状态；Renderer 顶部状态区展示当前数据根和运行模式。生产模式会显示“当前连接真实生产数据”的警告。

## 2. Production / Development 区别（历史记录）

生产根的普通业务路径不受影响：设备采集、查询、分析和导出仍可用。维护、批量删除、数据库修复、派生数据重建、历史迁移和其他破坏性写操作在生产根上默认拒绝，只有进程明确收到 `--allow-production-write`（内部环境变量 `NETCONSOLE_ALLOW_PRODUCTION_WRITE=1`）才会继续。

下列维护 CLI 已接入同一门禁：

- `scripts/maintenance/rebuild_mesh_parsed_data.py`
- `scripts/maintenance/remap_mesh_identity.py`
- `scripts/maintenance/migrate_device_history.py`
- `scripts/maintenance/manage_task_result_rollout.py`
- `scripts/maintenance/upgrade_ap_extension_schema.py`

开发副本通过 marker 明确为 `development`，不会因为目录名称或路径相似而被当作生产根。生产数据的任何变更都必须落在开发副本；副本修改不会回写生产根。已存在的更强安全条件（例如 `--allow-development-root-only`、revision/hash、二次确认）仍然有效，生产授权不能绕过它们。

## 3. 历史复制流程（已退役）

历史上曾使用 `scripts/sync_data_root.ps1` 将完整生产根复制到开发根；该脚本现已退役，当前不得执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_data_root.ps1  # 历史命令，仅供取证
```

脚本执行前显示源路径、目标路径、文件数量和总字节数，并要求输入 `SYNC DATA ROOT`。复制使用 `robocopy /E /COPY:DAT /DCOPY:DAT`，覆盖整个数据根，不只复制 SQLite；完成后重写开发副本 manifest 的 `data_root` 和独立 installation id，写入 development marker，并输出 `SYNC COMPLETE`、文件数、总大小和耗时。

历史上的 `scripts/reset_dev_data.ps1` 会先要求两次输入 `RESET DEV DATA`，然后执行同一完整复制流程；该脚本现已退役，Git history 是唯一恢复来源。

本轮没有在运行中的 NetConsole 进程仍持有生产数据根时执行真实全量同步，因此“同步后两边一致”的现场证据仍为 `PENDING`。脚本已在隔离目录完成小规模复制验证：128 个文件、1,284,942 字节，输出 `SYNC COMPLETE`。现场已有 `D:\NetConsoleData-dev` 的 `demo`、`hzl10` `devices.db` SHA-256 与生产对应文件一致；这证明副本内容可读且当前未发生生产回写，但不替代按任务要求的带空格目标同步。

## 4. 保护机制

保护边界由四层组成：

1. **显式 marker**：`runtime_mode.json` 是持久化环境事实源，不使用 `D:\NetConsoleData - dev` 之类的目录名启发式。
2. **启动识别**：缺失或无效 marker 拒绝持久化启动；健康接口、日志和 UI 同时显示根路径与环境标签。
3. **生产写入门禁**：Backend 维护路由和独立 maintenance CLI 统一调用 `require_data_root_write_allowed`；默认只读业务能力保持开放。
4. **复制安全（历史）**：当时同步/重置脚本拒绝驱动器根和 junction/symlink；同步/重置入口现已退役，当前开发根不得通过整根复制刷新。

生产根当前未执行 `DELETE`、`DROP`、`VACUUM`、checkpoint、数据库迁移、数据修复或 MESH 重建。任何需要生产授权的动作都必须留下命令行授权和审计记录。

## 5. 数据库生命周期检查结果

审计报告：`D:\study\diagnostic\NetConsole\data-root-20260821\lifecycle-audit.json`。该报告记录生成时的带空格开发副本快照；当前现场目录名已核对为 `D:\NetConsoleData-dev`，因此报告中的根路径需视为历史审计证据，不能替代当前目录复核。审计使用只读连接，检查了两套根目录中可读的局点数据库；没有执行写入、删除、重建或压缩。

### `devices.db`

- 当前设备表的大多数站点没有发现重复设备记录；设备名称、型号、序列号、接口、IP、版本等当前态仍由当前表保存，未改变模型。
- 宁波地铁 6 号线的 `device_lldp_neighbors` 发现 2 组 `device_uuid/local_interface` 重复组。这是当前态一致性问题，需要基于采集批次和唯一业务键进一步定位，不能在本任务中猜测删除。
- 旧 legacy history 表没有统一生效“每个资源只保留最近 10 次”：观测到 `hzl10` 接口 68、LLDP 20、光模块 73、AP LLDP 214；宁波地铁 10 号线接口/LLDP/光模块最高 49/49/80；宁波地铁 6 号线 LLDP 最高 156。现有代码只对新 change-aware history 路径提供 bounded retention，旧表和已封存分片按兼容策略保留。
- 建议：先在开发副本上按表、资源键和 producer 版本复现超限来源，确认查询消费者后，再单独设计 legacy retention 迁移；本轮不扩大历史删除范围，也不重构 `HistoryStore`。

### `tasks.db`

- 当前任务库不是永久归档库，但实际事件量仍会增长：宁波地铁 12 号线 `task_events=175094`、`task_snapshots=3911`、`task_results=3572`；`hzl10` `task_events=88119`、`task_snapshots=817`。
- `task_logs` 表未发现；大量结果/日志语义位于 `task_events.payload_json`。这说明不能只按表名判断生命周期，也不能直接删除事件行而不核对 result 引用。
- 宁波地铁 12 号线存在 3 个 snapshot 结果引用异常，需要依据实际 task/result contract 在开发副本中复核。当前任务中心仍以隐藏/预览策略为主，不启用物理 DELETE/VACUUM。
- 建议：补充按任务终态、结果引用、Artifact 存在性和保留期限的只读指标；在 owner、回滚和消费者证据完备前，继续保留当前任务、近期任务、状态和结果引用。

## 6. 发现问题

1. 旧 legacy history retention 与“最近 10 次”目标不一致，存在长期增长风险。
2. 宁波地铁 6 号线当前 LLDP 有重复键，需业务复核。
3. `tasks.db` 的事件和结果表存在明显增长，且 payload 承担了部分日志/结果语义；宁波地铁 12 号线有 3 个结果引用异常。
4. 真实运行进程占用数据根期间不能安全执行全量同步；本轮真实 sync/reset 未执行。
5. 当时现场开发目录为 `D:\NetConsoleData-dev`，不是历史任务要求的 `D:\NetConsoleData - dev`；该历史差异不改变当前 Development Authority，也不授权重命名、删除或整根复制。

## 7. 修复建议

- 当前只在 `D:\NetConsoleData-dev` 按站点、表、资源键建立只读增长基线，确认当前 producer、兼容查询和导出消费者；不要使用历史带空格目标。
- 对 legacy history 先做 bounded COPY/verify 演练和查询 parity 验证；未经单独授权，不删除源行、不 DROP、不 VACUUM。
- 对 tasks 先修复/解释结果引用异常，再由 Task Center owner 制定可回滚的保留策略；不新建第二套 Task 模型。
- 不再执行完整 `sync_data_root.ps1`；如未来需要刷新 Development 数据，必须另行提出受控方案并明确授权。
- 现场 GUI、设备采集、安装包和跨机器验收仍需人工完成；自动化测试和脚本验证不能替代这些验收。
