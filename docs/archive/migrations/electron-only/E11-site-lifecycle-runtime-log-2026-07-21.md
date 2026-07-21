# 局点生命周期与运行日志整改交接（2026-07-21）

## 1. 范围与状态

本阶段只处理两类存储安全问题：Legacy/Demo 局点的只读审计与受控回收能力，以及软件运行日志三天保留失效。没有修改设备命令、MESH/Online MR 业务算法、设备数据库 schema 或正式报告内容。

当前状态：

- 局点审计、prepare/apply 回收、30 天恢复和受控 Demo 重建代码已实现并通过临时数据根测试。
- 正式开发数据根只完成只读审计；Legacy 回收和 Demo 重建尚未执行，不能标记为真实数据验收完成。
- 软件运行日志按记录时间清理、轮转、跨文件分页/导出、24 小时自动调度和页面收紧已实现。
- 正式开发数据根的软件运行日志已执行一次 72 小时清理并完成保护哈希复核。
- Electron 真实窗口的最大化/还原、任务卡片和日志表格视觉验收尚未执行。

## 2. 固定数据边界

三天自动清理固定只选择：

```text
<data_root>/runtime/logs/
└─ 受控文件名的软件运行日志
```

缓存和临时文件仍可由用户先扫描、再手工选择并确认；它们不属于三天自动清理。以下内容不得由自动清理或旧磁盘清理入口删除：

- 局点业务 `logs/`、MR 原始 MESH、Online MR raw 和采集日志；
- parsed SQLite、设备数据库、任务数据库和局点基础资料；
- 报告、Artifact、导入 ZIP、用户下载和导出文件；
- archive、migrations、备份、回收 tombstone 和 Demo staging 事务材料。

旧 `data_disk_manager` 不再按目录名递归清空任意 `debug/` 或 `logs/`；软件运行日志统一由日志中心管理。

## 3. 运行日志根因与整改

清理前约 225 万条记录全部来自单个持续追加的 `runtime/logs/app.log`，不是日志 SQLite。旧实现按文件修改时间判断并跳过活动文件，因此应用每次启动虽然提交任务，却始终删除 0 条记录。

当前实现：

1. 按每行前 19 个字符解析本地记录时间，截止时间固定为当前时间减 72 小时。
2. 当前活动文件流式过滤，malformed 行保留；临时文件完成 `flush + fsync` 后原子替换，失败保留原文件。
3. 写入、清空、直接导出和清理共用跨进程日志锁。
4. 跨天或活动文件达到 25 MB 时轮转，日志中心分页和 Export Process 跨当前/轮转文件读取。
5. 自动任务固定只传 `runtime_logs`，Application Service 与 Worker 双重校验。
6. 同一数据根使用跨进程认领；成功后 24 小时内跳过，Backend 持续运行时每 24 小时复查。
7. 轨旁 AP 逐行 INFO 日志收敛为聚合统计；设备连接尝试开始降为 DEBUG。

正式清理结果：

| 指标 | 结果 |
| --- | ---: |
| 清理前大小 | 492,029,875 B |
| 清理后大小 | 18,750,081 B |
| 扫描记录 | 2,253,873 |
| 删除超期记录 | 2,166,461 |
| 保留 malformed | 1,433 |
| 清理后可解析记录 | 85,980 |
| 清理后最早可解析时间 | 2026-07-18 12:23:56 |
| 释放空间 | 473,279,794 B |
| 失败 | 0 |

清理前后 `app.json` 和 `site_registry.json` SHA-256 保持不变；抽样的 Online MR raw、parsed SQLite、ZIP 和 MESH XLSX 哈希全部保持不变。正式清理没有写入仓库根 `data/` 或 `.local/`。

## 4. 局点生命周期能力

局点维护通过 `SiteAuditService`、`SiteCleanupApplicationService` 和 `DemoSiteSeedService` 实现：

- 审计记录 Registry/bootstrap 引用、文件清单、哈希、SQLite 完整性和未知内容；
- 回收采用 prepare/apply、30 分钟单次 token、事务 marker、跨进程锁和失败回滚；
- 回收目标只移入 archive，并保留 tombstone 与 30 天受控恢复入口；
- 未知文件、自定义设备组、损坏 SQLite 和跨局点引用默认阻断；
- 受控 Demo 使用当前 Schema 和少量脱敏不可连接设备，不含密码、SNMPv3 或预置任务，并限制小于 50 MB；
- `isolated_test` 拒绝正式审计/回收/Demo 重建写入。

正式数据根中的 Legacy 和旧 Demo 尚未执行 apply。后续必须重新审计，核对 token 对应 manifest，再分别执行回收和 Demo 重建；不得把本阶段的临时目录测试当作真实数据验收。

## 5. 验证证据

- 日志、系统维护、数据盘和 Export 定向 Python：48 项通过。
- 局点生命周期、存储 API、生成物清理和文档布局组合：96 项通过。
- 轨旁 AP 日志收敛相关组合：73 项通过。
- System Maintenance 定向 Vitest：8 项通过；一次 Web 全量 Vitest：92 个文件、369 项通过。
- Web TypeScript 和 production build 通过。
- 改动范围 Ruff 与 `git diff --check` 通过。

上述自动化不替代 Electron 窗口人工验收。未运行全量 Python、Electron E2E 或安装包 smoke，不得据此声明完整发布门通过。

## 6. 后续顺序

1. 暂停新模块，先在 Electron 正式开发模式验收日志页面高度、分页校正、终态任务折叠和任务窗口入口。
2. 重新只读审计正式 Legacy/Demo，确认当前局点、Registry 和业务代表文件保护哈希。
3. 执行 Legacy prepare/apply，复核回收 tombstone、Registry、当前局点和业务哈希。
4. 执行受控 Demo 重建，验证小于 50 MB、无凭据、无预置任务且不可连接。
5. 完成后再决定是否运行全量门、Electron smoke 和发布流程。

`agent_team/`、现有 stash、用户未提交的拓扑测试、Vite 配置和项目双语规则不属于本阶段提交范围，不得自动覆盖或回收。
