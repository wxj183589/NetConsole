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

最终 Full Gate 在 clean、已推送的 `a66455b251bf220ca418da01547102c684030246` 上执行，结果 PASS。命令为 `python -m scripts.quality.local_gate --mode full`，并向子进程显式传递已安装的项目 Python 3.13.9 及 `pnpm_config_verify_deps_before_run=false`，以避免 pnpm 非交互依赖重验证尝试删除虚拟存储目录。

| 门禁 | 结果 |
| --- | --- |
| Repository / Workspace layout | PASS |
| Renderer 全量 | PASS，224 files / 1610 tests，production build 完成 |
| Python 全量 | PASS，5870 passed / 2 skipped，35 warnings，1745.59 秒 |
| Electron 合同、类型和构建 | PASS，41 files / 326 tests |
| Architecture guards | PASS，12/12 |
| Main contract smoke | PASS，12 passed |
| Ruff | PASS |
| Docs/path guards | PASS，22 passed |
| Git diff check | PASS |
| Packaged Electron smoke | PASS，冻结 Worker 中文协议、数据库迁移/list API HTTP 200、无人值守状态 HTTP 200、MESH 幂等、归档重名、NOTICE/SBOM 与正常退出 |

机器可读结果保存在 `D:/study/NetConsole-Workspace/worktrees/organization-task-network-services-phase6/.local-reports/local-gate.json`，完整原始输出保存在 `D:/study/NetConsole-Workspace/reports/tests/phase7-full-gate-20261125/attempt5-full-gate.log`。最终结论为 PASS。第一次 gate 的真实代码/测试失败均已修复。后续几次尝试定位并修复了退役功能 smoke 基线、包级 Python 路径及 pnpm 非交互配置问题，失败尝试的日志仍保留在同一报告目录。

## Phase 7.1 沿用状态

2026-11-26 本阶段没有重跑 Full Gate。上文 PASS 结果仍对应 clean、已推送的源码 checkpoint `a66455b251bf220ca418da01547102c684030246`。当前产品分支位于后续报告提交 `266acbcd5b4561130b26277719ca7780089d7bef`。Windows 安装、升级、卸载和安装态业务验收未完成，不能由 Full Gate 或 package smoke 推导为 PASS。安装包静态复核和 VM 阻断记录见 [`PHASE7_WINDOWS_VM_ACCEPTANCE.md`](./PHASE7_WINDOWS_VM_ACCEPTANCE.md)。
