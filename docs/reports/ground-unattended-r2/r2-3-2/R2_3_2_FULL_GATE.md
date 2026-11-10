# R2.3.2 Full Gate

## 命令

在候选 Worktree 根执行，候选基于 R2.3.1 实际 HEAD `de7ca957d371cd8bc29b60d05f69f4c85d8b2190`，本轮工具修复提交为 `a91a1916`：

```text
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full
```

证据日志：`D:\study\NetConsole-Workspace\reports\tests\r2-3-2-clean-full-gate\rerun-full-gate.log`。

## 结果

`RESULT: FAIL`，但失败拆分如下：

| Suite | 结果 | 证据 |
|---|---|---|
| root-layout | PASS | 通过 |
| workspace-layout | PASS | 通过 |
| renderer-full | PARTIAL | 并发 Full Gate 时 1 项 Mesh 性能阈值失败；独立复跑 Renderer 全量 210 files/1535 tests passed |
| python-full | PARTIAL | 5624 passed、36 failed、2 skipped；失败集中在既有 Mesh/DataRoot/生产维护/文档治理 |
| electron-contract | PASS | 38 files/306 tests、typecheck、main build 通过 |
| architecture-guards | FAIL | 既有 direct-sql-access、device-command-hardcoding、ui-business-logic |
| main-contract-smoke | PASS | 通过 |
| ruff-full | PASS | 通过 |
| docs-path-guards | FAIL | 既有 Mesh report README 缺口及治理文件问题 |
| git-diff-check | FAIL | 既有 Mesh phase11-9 文档 trailing whitespace |
| package-smoke | NOT_AVAILABLE | package 构建到达正式发布保护，但要求最终提交已 push 且 HEAD 与 upstream 对齐；本任务明确禁止 push |

独立复核：`tracksideSeriesColors.test.ts` 5 passed；`syslog_v2_stress.py::test_20000_mock_ingress_burst_keeps_raw_and_bounded_queues` 在 Gate 并发期间超时，停止并发后独立复跑 `1 passed in 48.93s`。因此该项不归因于 Ground 数据完整性缺陷。

## 判定

本轮 Full Gate 不能作为整仓库 PASS：失败项与候选基线中的 Mesh/DataRoot/架构/文档治理及正式安装器 push 对齐约束相关，未通过修改断言、删除 dirty 文件或绕过安装器来消除。Ground 专项和独立重跑证据单独保留，故 `FULL_LOCAL_GATE=PARTIAL`、`LOCAL_ACCEPTANCE=PARTIAL`、`RELEASE_READINESS=NOT_READY`。

## 后续定向复核

- Renderer 独立全量：210 files / 1,535 tests passed。
- Electron 独立全量：38 files / 306 tests passed；typecheck、main build passed。
- Electron packaging/development-data-root 定向：30 passed。
- `ruff`、新增脚本 `py_compile`、`git diff --check`（候选本轮文件）通过。
- 正式 package-smoke 未绕过安装器保护：流程要求最终提交已 push 且 HEAD 与 upstream 对齐，本任务明确 `Push=NO`，因此不生成发布 PASS。

`FULL_LOCAL_GATE=PARTIAL`。不能把已有全仓库基线失败或发布 push 保护提升为 R2.3.2 Ground PASS；这些失败与本地 Ground 专项通过结果分开记录。
