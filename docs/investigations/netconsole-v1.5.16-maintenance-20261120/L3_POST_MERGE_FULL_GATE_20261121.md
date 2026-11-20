# NetConsole v1.5.16 L3 合并后 Full Gate

日期：2026-11-21（Asia/Shanghai）
状态：`PASS`

## 固定主线

| 项目 | 证据 |
| --- | --- |
| PR | [#125](https://github.com/wxj183589/NetConsole/pull/125) |
| 合并方式 | GitHub 正常 Squash Merge，无管理员绕过、无 Force Push |
| 合并提交 | `5ba59a41434ee86cca846ac9fac702a8df27b2eb` |
| `POST_MERGE_MAIN_SHA` | `5ba59a41434ee86cca846ac9fac702a8df27b2eb` |
| 本地 `github/main` | 与 `POST_MERGE_MAIN_SHA` 一致 |
| 测试工作树 | `worktrees/netconsole-v1516-post-merge-20261121` |
| Gate 入口 | `python -m scripts.quality.local_gate --mode full` |
| Gate 报告 | `.local-reports/local-gate.json`、`.local-reports/local-gate.md`（工作树内，未提交） |

## Gate 结果

| Gate | Result | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Root layout | PASS | 1 step | 0 | 0 | `ROOT_LAYOUT_GATE=PASS` |
| Workspace layout | PASS | 1 step | 0 | 0 | `WORKSPACE_LAYOUT_CHECK=PASS` |
| Renderer full | PASS | 211 files / 1544 tests | 0 | 0 | Vitest；`3431 modules transformed`；Vite build |
| Python full | PASS | 5620 | 0 | 2 | `5620 passed, 2 skipped, 34 warnings`；1650.59s |
| Electron contract | PASS | 38 files / 315 tests | 0 | 0 | Vitest、typecheck、Main/Preload build |
| Architecture | PASS | 12/12 | 0 | 0 | 12 checks，0 findings，0 waived |
| Main contract smoke | PASS | 12 | 0 | 0 | `12 passed`；11.84s |
| Ruff full | PASS | 1 step | 0 | 0 | `ruff check .` |
| Docs/path guards | PASS | 22 | 0 | 0 | `22 passed`；1.06s |
| Git diff check | PASS | 1 step | 0 | 0 | `git diff --check` |

Gate 总耗时约 29:56；开始 `2026-11-21T01:25:13+08:00`，结束 `2026-11-21T01:55:09+08:00`。Local Gate 报告的 base/head 均为最终主线 SHA，测试在该固定提交上执行；测试数据使用隔离的 `test-data/NetConsole/local-gate-*` 根，运行后由 Gate 回收。

## 评审与限制

- PR 合并前 8 个 GitHub 工程检查全部 SUCCESS，review thread 为 0。
- GitHub Codex Review 因账户 code-review usage limit 耗尽而未完成；没有生成代码 finding，不能记为 Review PASS。
- 本 Gate 不替代真实 Electron GUI、真实 H3C/AC/FIT-AP、Win10 20H2、8 小时稳定性和正式安装包验收。

## 数据安全

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
USER_FILES_MODIFIED=0
REAL_DEVICES_ACCESSED=0
DEVICE_CONFIG_WRITES=0
```

原始 Desktop RAR SHA-256 仍为 `B785746E5C9299C5795DD375C5118308F854AAEA8275F492CF070DA5C347A383`；只读提取目录仍为 `D:\study\NetConsole-Workspace\temp\analysis\netconsole-v1.5.16-maintenance-20261120`，1103 个文件、416760785 bytes，均未清理、移动或覆盖。
