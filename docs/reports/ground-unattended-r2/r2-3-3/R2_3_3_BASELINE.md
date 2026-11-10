# R2.3.3 基线审计

日期：2026-11-10

## 代码基线

- Branch：`codex-A/r2-3-3-ground-unattended`
- R2.3.2 基线：`d3588c5d57cb71e9e0df7fa3d2323f8aeaf28f97`
- 本轮实现提交：`4c7f70ea4ab19d55a2a7bae1e3c504d322691de`
- 验证工作树：`D:\study\NetConsole-Workspace\worktrees\r2-3-3-ground-unattended`
- 主仓库 dirty 状态未覆盖、未 reset、未 stash；未修改其他 Worktree。

## 数据边界

本轮使用：

- 合成 inventory、脱敏 Fixture、loopback UDP 和隔离 SQLite 做实时链路测试。
- 用户提供的 `C:\Users\18358\Desktop\2026-11-09_ground_unattended.zip` 做只读历史回放。
- 历史归档标识 `site_id=hzl10`、`run_id=ground_20261109_fe484f124afe`，按杭州地铁 10 号线局点处理。

未使用或修改：`D:\NetConsoleData`、`D:\NetConsoleData-dev`、真实设备、真实 AC/SSH、`D:\study\fping`。

## 基线结论

R2.3.2 的长稳结论继续保留：`LONG_STABILITY_8H=PARTIAL`、`USER_WAIVED_REMAINING_DURATION=true`、`SOAK_OBSERVED_DURATION=24000.379s`。本轮不重复等待 8 小时。

本轮范围聚焦 Raw 压缩队列 bounded-full 恢复、100 MR 短时突发、阶段可观测性、AC Query Duration、真实 Electron 交互和杭州 10 号线原版归档回放。Full Gate 与 package-smoke 的真实阻断单独记录，不通过删改门禁制造 PASS。
