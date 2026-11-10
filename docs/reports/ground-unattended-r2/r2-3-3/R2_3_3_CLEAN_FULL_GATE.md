# R2.3.3 Clean Full Gate

## 实际命令

```text
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full --base-sha d3588c5d --paths <本轮受控变更路径>
```

退出码：`1`，`RESULT: FAIL`。这是候选 Worktree 的真实 Full Gate 结果，不是通过修改断言或清理其他工作树得到的结果。

## Suite 结果

| Suite | 结果 | 证据 |
|---|---|---|
| root-layout | PASS | 通过 |
| workspace-layout | PASS | 通过，未跟随 Reparse Point |
| renderer-full | PASS | 210 files / 1,535 tests，typecheck/build 通过 |
| python-full | FAIL | 5,625 passed、38 failed、2 skipped；失败集中于既有架构、DataRoot 隔离路径和文档治理 |
| electron-contract | PASS | 38 files / 306 tests，typecheck、main build 通过 |
| architecture-guards | FAIL | 既有 direct-sql-access、device-command-hardcoding、ui-business-logic findings |
| main-contract-smoke | PASS | 通过 |
| ruff-full | FAIL（门禁当时） | 门禁快照包含新回放脚本的 17 项 lint；随后已修复并独立 `ruff check .` 通过 |
| docs-path-guards | FAIL | 3 项既有 broken link / transient filename / README 缺口 |
| git-diff-check | PASS | 本轮受控差异检查通过 |

Python Full Gate 失败中有 1 项是本轮新增 API Available 字段导致的列表/详情动态时间不一致，已修复；复核命令为定向 Ground 集合，结果 `43 passed`。其余失败未扩展到本轮业务范围，未修改 Mesh/既有治理规则来掩盖。

## 判定

`CLEAN_FULL_GATE=PARTIAL`，不是整仓库 PASS。候选可供后续本地集成继续审阅，但不满足正式发布门禁。
