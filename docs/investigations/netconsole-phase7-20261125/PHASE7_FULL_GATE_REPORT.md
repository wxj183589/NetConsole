# Phase 7 Full Gate

## 首轮

基线 HEAD 为 `7b8e82f1bf86308c3fe5d83b20d2946dc36ac1bd`，包含当时 Phase 7 未提交修改。执行正常 `python -m scripts.quality.local_gate --mode full`。

结果为 FAIL。Python 5841 passed、8 failed、2 skipped，1826.32 秒。Renderer 1609 passed、1 failed。Electron 326 passed。主线合同 smoke 12 passed，文档门禁 22 passed。Workspace、根布局、最终架构检查、Ruff 和 diff-check 通过。package-smoke 因正式候选要求 clean 被拒绝。

首轮机器可读报告保存在 `D:/study/NetConsole-Workspace/reports/tests/phase7-full-gate-20261125/attempt1-local-gate.json` 和同名前缀 Markdown。控制台输出由当前任务会话保留，首轮未单独保存完整原始日志。

## 失败修复

- 模板 Repository 复用 core.site_identity 的既有 canonical 校验，消除反向依赖。
- 设备管理三个 UI 草稿/展示/DTO 提交函数完成精确 inventory 分类，业务规则仍由既有应用层处理，无新增豁免。
- 补齐四处缺少的目录 README，定向文档回归 9 passed。
- Full 与兼容 Customer Feature Profile 补齐 Registry 已存在的 local_services 页面能力，定向功能开关回归通过。
- 轨旁导出测试补入既有工程上下文四列的固定顺序，保留原业务列断言。源码列来自已有提交 `0a5b4a34`，本轮未改动轨旁导出生产逻辑。相关功能、轨旁与基础设施测试共 65 passed。
- AppLayout 测试使用 Phase 6 已实现的路由名称前缀键，增加前缀合同断言，定向 Renderer 12 passed。

## 最终执行

待本轮 clean checkpoint 推送后，重新执行同一 Full Gate 并将 stdout/stderr 保存至 Workspace 报告目录。最终计数、提交和包级结果将在执行完成后补充。本报告当前状态为 PARTIAL。
