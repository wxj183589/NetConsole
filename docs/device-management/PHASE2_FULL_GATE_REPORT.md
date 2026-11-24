# NetConsole Phase 2.5 Full Gate 报告

## 结论

`PASS`。本报告记录 Phase 2 首轮失败、独立诊断和最终 canonical Full Gate 结果。真实局点、真实设备、安装包和现场长时任务不属于本次自动化 Gate，仍需后续现场验收。

## 执行信息

- 产品分支：`codex-A/device-management-phase2`
- Full Gate 执行 HEAD：`c24e2c8aa9eb2d4db0b9508ee32d03c40af00395`
- 产品最终 HEAD（文档收口后）：`8c4514135eca7d662f2a47bfb8ef7bb5e464a176`
- Phase 1 基线：`907183a4`
- 正式命令：`python -B -m scripts.quality.local_gate --mode full --base-sha 907183a4 --head-sha HEAD`
- 开始：`2026-11-24 15:12:41`（Asia/Shanghai）
- 结束：`2026-11-24 15:43:32`（Asia/Shanghai）
- 退出码：`0`
- 原始日志：`D:\study\NetConsole-Workspace\reports\tests\device-management-phase2\full-gate.log`

## 最终门禁

| Suite | Result |
| --- | --- |
| root-layout | PASS |
| workspace-layout | PASS |
| renderer-full | PASS — 216 files, 1577 passed |
| python-full | PASS — 5744 passed, 2 skipped, 34 warnings |
| electron-contract | PASS — 41 files, 324 passed |
| architecture-guards | PASS — 12/12 |
| main-contract-smoke | PASS — 12 passed |
| ruff-full | PASS |
| docs-path-guards | PASS — 22 passed |
| git-diff-check | PASS |

Renderer `vue-tsc -b` 和 Vite build、Electron typecheck/build 均通过。Python 的 34 条 warning 为既有 Starlette deprecation warning，不影响退出码。

## 首轮失败与处理

首轮日志 `full-gate-a5ffea65.log` 记录了三个独立问题：

1. `tracksideSeriesColors.test.ts` 的 770 series / 44,251 points 用例测得 `102.7486ms`，阈值为 `100ms`。未修改阈值、未删除断言。先前独立顺序运行 10 次全部通过，结果为 P50 `24.605ms`、P95 `26.642ms`、最大 `28.469ms`，失败 `0`；随后将 Renderer Vitest `maxWorkers` 固定为 `2`，最终 Full Gate 在原始阈值下通过，结论为共享主机资源竞争导致的计时抖动，不是产品性能回退。
2. 文档路径门禁发现 `PHASE2_BRANCH_INTEGRATION_AUDIT.md` 的活动文档文件名不符合治理规则。文件已重命名为 `PHASE2_BRANCH_INTEGRATION.md`，引用同步更新并纳入产品提交。
3. 发布资源测试 `test_clean_build_runtime_subset_copies_only_imported_modules_and_assets` 首轮未找到 Renderer dist 资源，原因是 Renderer 套件在性能失败后中断、未执行后续 build。最终 Renderer build 生成 dist，发布资源测试随 Python Full Gate 通过；未发现发布资源代码回归。

## 环境

- Windows 11 专业工作站版，版本 `10.0.26200`，x64。
- Python `3.13.9`，解释器：`D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe`。
- Node `v24.18.0`；pnpm `11.25.0`；Electron `43.1.1`。
- D: 盘：已用 `215803641856` bytes，可用 `449915236352` bytes。
- Full Gate 前未发现 pytest、Vitest、local_gate、Electron runtime 等竞争测试进程。
- 测试使用仓库隔离 basetemp；未访问生产数据、真实开发数据或真实设备。

## 数据和剩余范围

- `PRODUCTION_DATA_MODIFIED=0`
- `REAL_DEVICE_MODIFIED=0`
- `DATABASES_REMOVED=0`
- 未执行真实局点、真实设备配置、安装包安装/升级/卸载和现场长时验收。
