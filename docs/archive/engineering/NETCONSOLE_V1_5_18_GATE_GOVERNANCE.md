# NetConsole v1.5.18 Gate 专项治理报告

日期：2026-11-23（Asia/Shanghai）
候选工作树：`D:\study\NetConsole-Workspace\worktrees\release-v1.5.18-20261123`
分支：`codex-A/release-v1.5.18-20261123`

## 1. 结论

`GOVERNANCE_STATUS=PARTIAL`
`RELEASE_STATUS=PARTIAL`

本轮完成了三个历史 Gate 的根因审计，并安全修正了 Workspace Layout 检查器的两个真实治理缺陷：

- 已注册的 `NetConsole-DevStatus` Git Worktree 现在纳入管理路径核对；未知普通目录仍继续报告为 `UNMANAGED_WORKTREE_DIRECTORY`。
- 规范主 checkout `D:\study\NetConsole-Workspace\NetConsole` 不再被误报为 `WORKTREE_OUTSIDE_CONTAINER`。
- 已提交且有明确历史用途的 `artifacts/` 工程证据目录登记为保留目录；新报告、日志、截图和构建输出仍不得写入该目录。

以下问题没有被掩盖，也没有通过降低检查强度解决：

1. Root Layout 仍被仓库根目录已跟踪的 v1.5.17 历史文件阻断。
2. Architecture Guard 仍被三个真实 Renderer 业务逻辑符号阻断。

因此未合并 `main`、未构建 Installer/Portable、未推送 `main`，也未修改产品业务实现、真实数据或其他 Worktree。

## 2. 初始 Git 基线

| 项目 | 证据 |
| --- | --- |
| 候选 HEAD | `f10b8a6131a5b672d6f10a99cadfba3482d3dbbb` |
| 候选远端 | `github/codex-A/release-v1.5.18-20261123`，初始与本地一致 |
| 主线 | `github/main` = `9e463778f0ece54fb16cb31c877da86ff8bce438` |
| 候选提交链 | `aa0a7c0a` → `9226b2c0` → `eb7c78c0` → `f10b8a61` |
| 候选初始状态 | clean；本轮仅在候选 Worktree 修改治理文件 |
| 保护检查 | 主仓库、DevStatus 主 checkout、其他 Worktree 和真实数据均未纳入本轮提交范围 |

## 3. 三个 Gate 根因分析

### 3.1 Architecture Guard

原始发现包含四个符号：`normalizeMac`、`normalizedStatus`、`classifyPingStatus`、`naturalSecondLossBuckets`。源码与 `github/main` 一致，说明不是 v1.5.18 候选新引入的业务变更。

审计后分类如下：

| 符号 | 位置 | 结论 |
| --- | --- | --- |
| `normalizeMac` | `mrMonitoringChartOptions.ts` | 仅生成图表去重/配色键，已登记为 `DISPLAY_ONLY`，不再产生 Guard finding |
| `normalizedStatus` | `pingChartStatus.ts` | 归一原始状态别名，参与 Ground Ping 业务状态判定；真实架构债务 |
| `classifyPingStatus` | `pingChartStatus.ts` | 根据状态、丢包率、`ok`、RTT 判定业务状态；真实架构债务 |
| `naturalSecondLossBuckets` | `quickPingStatistics.ts` | 去重样本并聚合自然秒丢包统计；真实架构债务 |

本轮没有把后三项改成 `DISPLAY_ONLY`、没有加入 `exceptions.yaml` 豁免，也没有修改 Ground 业务实现。当前执行结果为 `ui-business-logic: FAIL (3 findings)`。后三项需要独立的 Backend 事实源迁移和 Consumer Audit，不能作为本次历史发布 Gate 的安全小修复处理。

### 3.2 Root Layout

检查器按现行仓库根文件白名单执行，发现以下已跟踪历史文件：

- `NETCONSOLE_V1_5_17_RELEASE_NOTES.md`
- `V1_5_17_CHANGELOG.md`

两者均由提交 `23e82b7d6e0ee2e5b5953a57422c87a416343480`（`docs(release): record v1.5.17 build and handoff`）引入，属于历史发布资料，不是本轮创建。按任务要求没有删除、移动、扩大白名单或伪造通过。当前 `ROOT_LAYOUT_GATE=FAIL`，需要独立的历史文件迁移方案、引用审计和用户授权后才能处理。

### 3.3 Workspace Layout

原始问题包含主仓库 `artifacts/`、Workspace reports 下错误职责目录，以及 DevStatus Worktree 识别不足。审计确认：

- `artifacts/` 已在候选历史提交中跟踪，并明确保存控制台重构工程证据；属于历史保留目录，不应删除。
- `NetConsole-DevStatus` 的三个 Worktree 由其自身 `git worktree list --porcelain` 真实注册，不能按普通未知目录处理。
- 主 checkout 是 Workspace 固定边界，不是必须位于 `worktrees/` 的 Codex 任务树。
- `reports/release-v1.5.18-20261123` 是本轮生成的日志目录，已将其中唯一日志移入现有 `reports/build/release-v1.5.18-20261123`；没有删除历史证据。

治理后完整检查结果：`WORKSPACE_LAYOUT_CHECK=PASS`，`REPARSE_POINTS=NOT_FOLLOWED`，`DESTRUCTIVE_ACTIONS=NONE`。

## 4. 修改文件

- `config/architecture/ui_business_logic.yaml`：登记四个历史符号；保留真实业务逻辑债务为 `BUSINESS_LOGIC`，不加豁免。
- `scripts/check_workspace_layout.py`：登记历史 `artifacts/`、识别 DevStatus 注册 Worktree，并排除固定主 checkout 误报。
- `docs/development/repository-layout.md`：记录 `artifacts/` 仅为历史证据容器，禁止新增运行/构建输出。
- `docs/development/workspace-layout.md`：记录固定 DevStatus 仓库的 Worktree 注册检查规则。
- `tests/quality/test_workspace_layout.py`：覆盖 DevStatus Worktree、未知普通目录、历史 artifacts 目录和主 checkout 边界。
- 本报告：记录根因、证据、状态和剩余整改项。

没有修改 Electron、Renderer、Python 业务逻辑、数据库 Schema、生产数据或 DevStatus。

## 5. 验证结果

| 检查 | 结果 |
| --- | --- |
| `python -m scripts.check_workspace_layout --repo-root . --workspace-root D:\study\NetConsole-Workspace` | `PASS` |
| `python -m scripts.quality.check_repository_root_layout` | `FAIL`：两份 v1.5.17 历史根文件 |
| `python scripts/architecture/check_ui_business_logic.py` | `FAIL`：3 项真实业务逻辑债务 |
| `python -m pytest tests/quality/test_workspace_layout.py tests/quality/test_repository_root_layout.py -q` | `22 passed` |
| `python -m pytest tests/quality/test_workspace_layout.py tests/quality/test_repository_root_layout.py tests/architecture/test_architecture_guards.py -q` | `35 passed, 2 failed`；失败为上述 Architecture Guard 汇总断言和 run-all 断言 |
| `PYTHONPATH=<candidate> .venv\Scripts\python.exe -m pytest tests/test_version_build_identity.py tests/test_changelog_sync.py -q` | `8 passed`；Python、Electron、HTML 和 CHANGELOG 均为 `1.5.18` Authority |
| `python scripts/build/sync_runtime_changelog.py --check` | `PASS` |
| `local_gate --mode full` | `FAIL`：Root Layout；Python `5709 passed, 2 skipped, 3 failed`（均为 Architecture Guard）；Architecture Guard；首次 `git-diff-check` 仅因本报告 3 行行尾空格失败 |
| Full Gate Renderer | `219 files / 1583 tests passed`；`vue-tsc` 和生产构建 `PASS` |
| Full Gate Electron | `41 files / 324 tests passed`；`tsc --noEmit` 和 Main/Preload 构建 `PASS` |
| Full Gate 主线契约 Smoke | `12 passed` |
| Full Gate Ruff / 文档路径 | `PASS`；文档路径 `22 passed` |
| `git diff --check 9e463778..HEAD`（清理报告行尾空格后） | `PASS` |
| 真实 Electron / SSH / SFTP | 沿用候选报告中已记录的真实回环证据；本轮未重新执行 GUI 现场验收 |
| Installer/Portable | `NOT RUN`；按任务约束未构建正式制品 |

## 6. 数据与工作区影响

```text
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

没有复制完整真实数据根，没有修改 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`，没有清理、移动或删除其他 Worktree、DevStatus 历史资料或候选分支历史文件。

## 7. 后续建议

1. 为 `pingChartStatus.ts` 和 `quickPingStatistics.ts` 制定独立 Backend 事实源迁移任务，完成 L4 Consumer Audit 后再重新运行 Architecture Guard。
2. 对两份 v1.5.17 根文件完成引用、发布流程和回滚方案审计；获得授权前保持原位并维持 Root Layout 阻断。
3. 两项阻断解决并完成正式全量回归前，不合并 `main`，不构建正式 Installer/Portable，不把候选标记为发布 PASS。
