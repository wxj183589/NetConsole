# hzdt-09 真实数据只读回放报告

## 环境

- DataRoot：`D:\NetConsoleData-dev`
- `runtime_mode.json`：`mode=development`
- `application.json`：`current_site=active_site_id=hzdt-09`
- `site_registry.json` 与 `site_meta.json`：`hzdt-09` 对应杭州地铁9号线，目录 `sites/hzdt-09`
- 生产安装实例指向 `D:\NetConsoleData`，未用于本次测试。

## 可追溯样本

MR `8e6773e7-2be2-45a2-b4bb-7505b139ada8`（train:35/CW）：

- 主地址 `10.82.25.235`，备用地址 `192.168.35.250`；
- 15:50 的主地址 1 分钟汇总：60 发、44 成功、16 丢包，RTT 20.5/45.1545/68.3 ms；
- 同窗口备用地址：60 发、41 成功、19 丢包，RTT 18.2/105.2488/2170 ms；
- 15:47–15:50：20 条实际切换、15 个由相邻证据证明的 Peer 区间；
- 首个窗口裁剪区间：qsdj-y180，MAC `4c:e9:e4:f0:9d:40`，原始 RSSI 41，归一化 -41 dBm；
- 丢包表包含主/备用地址的真实开始、恢复与未恢复记录。

压缩原始日志通过内存流读取，未解压落盘。最终产品代码的 MESH 历史连接使用 `mode=ro&immutable=1` 与 `PRAGMA query_only=ON`，并拒绝非零 WAL。

## 数据安全偏差

初始 Site 指纹：365 文件、291109010 bytes、聚合 SHA-256 `6AAF48C23E1743F541F1783C760B2ED3AE4303654E819334984EAF96C07C7BD0`。

复核指纹：379 文件、291338386 bytes、聚合 SHA-256 `7FAC3B0F8791B4FDCE1CD58119EB611F0339C5547EE15944D22BAD3F887D0DB3`。

根因是早期诊断脚本用普通 `mode=ro` 枚举打开 Site 内 SQLite；SQLite WAL 模式新增 14 个零长度 WAL 或 32 KiB SHM sidecar，并更新 2 个既存 SHM 的时间戳，发生时间为 2026-11-21 19:45:45，Ground index SHM 后续更新到 19:59:24。未发现主数据库、Raw 日志或历史记录内容修改，也没有删除数据库；但文件系统零变化目标已失败，必须报告 `DEV_REAL_DATA_MODIFIED=1`。按安全规则没有删除或清理这些 sidecar。
