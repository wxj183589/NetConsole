# NetConsole v1.5.16 维护审计

日期：2026-11-20
范围：NetConsole 原版；不包含 NetConsole-Next。
基线：`github/main` `6671f86ecd8bb9a2d3f12d5b0ccfe6b309cb4998`。
开发分支：`codex/netconsole-original-maintenance-20261120`。

## 边界与证据

- 仓库根：`D:\study\NetConsole-Workspace\NetConsole`；远端 `github` 指向原版 NetConsole 仓库；`github/main` 在最终 fetch 后仍为 `6671f86e`。
- 主工作树：`main@6671f86e`；本任务 Worktree：`worktrees/netconsole-original-maintenance-20261120`；另一个既有 detached Worktree 未修改。
- 主工作树中既有未跟踪调查目录未被改动；开发使用独立 Git Worktree。
- 现场压缩包 SHA-256：`B785746E5C9299C5795DD375C5118308F854AAEA8275F492CF070DA5C347A383`。
- 压缩包只解压到 Workspace 任务目录并只读分析，没有覆盖 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`。
- 日志复核到 Renderer 进程退出、Quick Ping DTO 多余内部字段、关闭阶段缺少 `task_snapshots` 表，以及局点导入失败后重试恢复等线索。日志线索不是单一根因结论。
- 未连接现场设备，未下发配置，未修改生产数据库，未恢复回收站数据。

## 历史分支结论

逐项比较了任务书列出的七条历史分支：

- `field-fault-fixes`、`mr-arp-v5-base-data`、`mr-arp-audit-fixes`：只核对现场修复、V5/ARP 和解析差异，main 已有等效能力时不重复移植。
- `ground-unattended-final`、`chatgpt/ground-unattended-bugfix`：只提取仍适用的行为契约，过期的自动修复/重复开关不带回。
- `v1.5.16-runtime-audit`：复用运行时审计结论，不把历史制品 smoke 当作本轮功能验收。
- `release-v1.5.16`：仅精确整合 `6e72b67a` 的版本标识与同步测试，形成本分支 `c5b9bf1f`；不整体合并旧业务代码。

业务修复均在当前 main 组合上重新实现和测试，没有用分支名中的 `final`/`bugfix` 代替逐文件审查。

## 变更影响

变更影响检查最终判定为 L3（高风险区域 `task-center`，要求合并后 main 复验）。本轮同时触及持久配置、设备命令安全、后台生命周期、Renderer 路由和跨模块契约，因此仍按更严格范围执行 Python 全量、Renderer 全量、Electron contract、架构检查和 main contract smoke。执行结果以测试报告为准。

## 数据安全声明

```text
MAINTENANCE_AUTHORIZED=NO
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
REAL_DEVICE_COMMANDS_SENT=0
```
