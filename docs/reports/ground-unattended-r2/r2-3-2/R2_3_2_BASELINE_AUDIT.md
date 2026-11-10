# R2.3.2 基线审计

日期：2026-11-10

## 基线

- 产品仓库：`D:\study\NetConsole-Workspace\NetConsole`
- 既有分支：`codex-A/global-dataroot-disk-policy`
- R2.3.1 基线提交：`de7ca957d371cd8bc29b60d05f69f4c85d8b2190`
- R2.3.1 已有结论：`LOCAL_ACCEPTANCE=PARTIAL`、`FIELD_ACCEPTANCE=NOT_AVAILABLE`、8 小时长稳未运行。
- 主工作树在任务开始前已有 DataRoot、Mesh、Electron 和文档 dirty 修改；本任务未覆盖、回滚或清理这些修改。

## R2.3.1 证据复核

R2.3.1 已有本地 loopback 证据为 100 MR、402 条 Syslog、402 Raw、402 Parser、最终 100/100 AP-B；位置 P50/P95/P99 为 3153/4309/4562 ms；AC delta 301 条，Heartbeat 200 targets。该证据作为回归基线保留，不替代本轮 8 小时实墙钟测试。

## 本轮审计结论

R2.3.2 在独立 Worktree 中继续验证，未使用 `D:\NetConsoleData`、`D:\NetConsoleData-dev`、现场设备或 `D:\study\fping`。R2.3.2 的本地结论必须与 Full Gate 的既有 Mesh/DataRoot/发布保护失败和 `FIELD_ACCEPTANCE=NOT_AVAILABLE` 分开记录。
