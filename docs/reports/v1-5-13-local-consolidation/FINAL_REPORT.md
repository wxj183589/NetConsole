# NetConsole v1.5.13 本地最终整合报告

日期：2026-11-11

## 结论

本轮完成了本地功能提交整合和日志统一：Ground Unattended R2.3.3、Syslog/Heartbeat/AC、MESH 等价补丁、v1.5.13 便携数据根均进入集成候选。主仓库 dirty 修改被完整保留；没有远程 Push、远程 Merge 或 Release。

`LOCAL_MAIN_INTEGRATION=PASS_WITH_GATE_CAVEATS`

`DATAROOT_INTEGRATION=PASS_WITH_GATE_CAVEATS`

`MESH_INTEGRATION=PASS_WITH_EQUIVALENT_PATCHES`

`GROUND_UNATTENDED_INTEGRATION=PASS_WITH_TARGETED_EVIDENCE`

`V1_5_13_INTEGRATION=PASS_WITH_GATE_CAVEATS`

`CHANGELOG_1_5_13=PASS`

`BRANCH_CLEANUP=PASS_WITH_PRESERVED_DIRTY_BRANCH`

`WORKTREE_CLEANUP=PASS_WITH_PRESERVED_DIRTY_MAIN`

`DIRTY_CHANGES_PRESERVED=PASS`

`FULL_LOCAL_GATE=PARTIAL`

`RELEASE_READINESS=NOT_READY`

## 数字

- 合并分支数：2 条有效代码线（R2.3.3、v1.5.13）；11 个 Ground 提交和 2 个 v1.5.13 提交移植。
- 已包含、无需重复合并：2 条 Mesh 分支；其提交均为 `git cherry` 等价补丁。
- 回收 Worktree：2 个 Ground Worktree 已回收；当前 v1.5.13 候选 Worktree 在 main 更新后回收；dirty 主仓库不回收。
- 分支清理：5 条已完成分支已用非强制 `git branch -d` 删除；dirty 的 `global-dataroot-disk-policy` 保留，所有原始 tip 由 archive refs 保全。
- 原始主线：`293377a1`；ancestry reconciliation 后候选 HEAD：`e83b87e9`；最终 main HEAD 以本报告提交后的 Git 核验为准。
- Worktree 回收数量：3 个（r2-3-2、r2-3-3、v1.5.13）；主仓库 dirty Worktree 和非 Git `worktrees/test-data` 不计入回收。
- Full Gate：5629 passed / 37 failed / 2 skipped；Renderer 1541、Electron 313 全量测试通过。

## 数据与发布边界

本轮未读取、复制、修改 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未连接真实设备，未触碰 `D:\study\fping`。正式安装器、Windows GUI 安装/升级/卸载、签名、现场设备和 Release 均未创建或宣称通过。
