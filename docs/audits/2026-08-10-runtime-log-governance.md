# 运行日志生命周期治理审计（2026-08-10）

## 结论

本次治理确认现场约 246 MB 的 `electron.log` 主要不是大块设备采集内容，而是受管 Backend 的重复异常 traceback 被 Electron 逐行转存造成的。运行日志与 raw/artifact 的边界已在代码、测试和策略事实源中固化；滚动和容量清理是磁盘保险，不能替代源头降噪。

证据等级：现场文件统计为 `CONFIRMED`；WPS 外部 writer 的单文件滚动为 `UNVERIFIED`（该 writer 不在本仓库）；raw/artifact 完整性为 `CONFIRMED`（自动化 SHA-256 回归）。

## 现场根因

样本 `electron.log` 为 258,058,311 字节、2,158,118 行。其中 `ELECTRON_BACKEND_OUTPUT` 为 2,103,583 行、252,431,645 字节，占约 97.8%；Python stderr 为 2,099,229 行。最大单行 728 字节，超过 8 KB 和 16 KB 的行均为 0；renderer console 合计约 303 KB，因此不是大 payload、polling 响应或 renderer 转储主因。

旧日志格式没有 level 字段，2,158,118 行均只能归为 legacy；按管道前缀统计为 stderr 2,099,229 行、stdout 4,354 行、其他 Electron 事件 54,535 行。Top 20 事件如下：

| 排名 | 事件 | 行数 | 字节数 |
| ---: | --- | ---: | ---: |
| 1 | `ELECTRON_BACKEND_OUTPUT` | 2,103,583 | 252,431,645 |
| 2 | `ELECTRON_RENDERER_LOAD_STARTED` | 9,463 | 905,466 |
| 3 | `ELECTRON_RENDERER_LOAD_STOPPED` | 9,461 | 914,929 |
| 4 | `ELECTRON_TRAY_MENU_UPDATED` | 5,479 | 312,303 |
| 5 | `ELECTRON_RENDERER_CONSOLE_ERROR` | 4,892 | 303,304 |
| 6 | `ELECTRON_WORKSPACE_WINDOW_FOCUSED` | 4,462 | 285,568 |
| 7 | `ELECTRON_UTILITY_PROCESS_GONE` | 3,978 | 600,656 |
| 8 | `ELECTRON_STARTUP_TIMELINE` | 3,598 | 363,267 |
| 9 | `ELECTRON_RENDERER_WORKLOAD` | 1,168 | 500,964 |
| 10 | `MESH_MEMORY_PROFILE` | 1,168 | 529,204 |
| 11 | `ELECTRON_BACKEND_STATUS` | 1,151 | 76,616 |
| 12 | `ELECTRON_RENDERER_LOAD_FINISHED` | 1,079 | 91,604 |
| 13 | `ELECTRON_WINDOW_VISIBLE` | 520 | 37,448 |
| 14 | `ELECTRON_BACKEND_READY` | 498 | 41,830 |
| 15 | `ELECTRON_BACKEND_STOPPING` | 449 | 25,144 |
| 16 | `ELECTRON_BACKEND_SHUTDOWN_SENT` | 449 | 27,389 |
| 17 | `ELECTRON_MAIN_WINDOW_REGISTERED` | 367 | 22,754 |
| 18 | `ELECTRON_STORAGE_MODE` | 364 | 24,388 |
| 19 | `NETCONSOLE_STORAGE_ROOT_SELECTED` | 364 | 50,578 |
| 20 | `ELECTRON_TRAY_CREATE` | 364 | 18,564 |

Top 消息签名同样指向该异常：Pydantic `extra_forbidden` 文档行 442,225 次，多组 `Extra inputs are not permitted` 各约 49,000 次，`Traceback` 头 35,243 次，supervisor `_tick()` 栈行 27,284 次。其余事件与该数量级相差两个数量级以上。

`GroundUnattendedSupervisor._run()` 的周期调度会读取 profile。旧实现把数据库行 `SELECT *` 直接交给 `GroundUnattendedProfileDTO(extra=forbid)`；数据库出现新增字段后，每轮都产生相同的 `extra_forbidden` traceback。Electron 的 `attachLineLogger()` 又把 stderr 的每一行写成 `ELECTRON_BACKEND_OUTPUT`。样本约 24,611 次重复异常，每次约 85 行、10.3 KB；按 1 秒周期估算，理论上可接近 0.89 GB/天。

## 修改后的策略

- `src/netconsole/resources/log_policy.json` 是统一事实源：应用事件 16 KB、context 32 KB、traceback 256 KB；Electron/Python 单文件 20 MB、保留 7 天；WPS 保留 3 天且策略目标 5 MB；startup/crash 诊断保留 30 天；总量上限 300 MB，清理到 250 MB，每小时检查。
- Electron logger 使用异步队列，按大小和本地日期滚动为 `electron-YYYYMMDD-HHmmss-NNNN.log`。同日序号递增；Windows rename/EBUSY 失败写入 fallback 并继续追加，不中断主流程。生产默认 `INFO+`，开发可显式启用 `DEBUG`。
- Backend stdout 只消费协议控制消息，生产不逐行落盘；stderr 按受控事件分类。应用大对象只写 UTF-8 安全摘要和 `payload_truncated=true original_bytes=...`，不改变 raw/artifact。
- Python `app.log` 复用现有跨进程锁，按 20 MB 和日期滚动；默认不落盘 DEBUG。Ground profile 读取只投影 DTO 已知字段，新增数据库列不再触发重复 traceback；首次异常、60 秒摘要和恢复事件即时保留。
- `LogHousekeeper` 只处理已识别的 rotated electron/app、过期 WPS、诊断和 archive 文件。活动日志、数据库升级审计、最近 5 分钟仍可能被 WPS 占用的文件及未识别文件均受保护；按 rotated electron -> app -> WPS -> diagnostics -> archive 的顺序最旧优先清理。

## 完整性与边界

raw collection 明确 `truncate=false`，继续复用既有 `MeshStorageService.archive_raw_file_with_metadata`。10 KB、64 KB、256 KB、1 MB 输入的归档 SHA-256 回归已覆盖；因此应用日志限长不会截断 SSH/CLI/MESH/Syslog/配置/iperf 等原始证据。

WPS stdout/stderr 的 writer 位于仓库外，本次只纳入其文件识别、保留期、容量清理和活动文件保护；不能据此宣称外部进程已经实现单文件滚动。

## 残余风险

现场统计来自单个运行目录样本，未替代安装包和真实 WPS 进程人工验收。若其他外部程序使用未识别命名写入 `runtime/logs`，Housekeeper 会保护该文件而不是删除它；应先补充分类规则再清理。
