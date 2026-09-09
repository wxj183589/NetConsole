# NetConsole v1.5.6 主线收口验收报告

验收日期：2026-09-09（Asia/Shanghai）

范围：分支全量审计、有效成果适配合入、RC/main/v1.5.6 三层回归、Full/Customer 打包、双远端发布点同步和本地分支/工作树回收。

结论：`FINAL_ACCEPTANCE = PASS`，仅代表代码、自动化回归、包内冒烟、发布身份和本地 Git 治理通过。真实 Windows GUI 安装、服务器安装和真实设备 E3 未在本轮执行，分别保持 `PENDING` / `NOT RUN`。

## A. Initial Baseline

| 项目 | 初始事实 |
| --- | --- |
| initial main SHA | `6d0cd921c07d7a6a48d46b7278019fdcf4d4712f` |
| initial GitHub main SHA | `6d0cd921c07d7a6a48d46b7278019fdcf4d4712f` |
| initial version | `v1.5.5` |
| initial local branch count | 6；创建一次性 RC 后为 7 |
| initial remote branch count | 40 个物理分支引用：GitHub 39、NAS 1，排除 remote `HEAD` alias |
| initial dirty status | clean |
| production data | 未访问、未复制、未修改 `D:\NetConsoleData` |
| development real data | 未访问、未复制、未修改 `D:\NetConsoleData-dev` |

完整逐分支事实、tip、merge-base、ahead/behind、patch-unique 数、文件域、风险与决策见 [v1.5.6 主线分支收口清单](../investigations/V1_5_6_BRANCH_CONSOLIDATION_INVENTORY.md)。

## B. Branch Audit

以下表格覆盖初始清单中的每个逻辑分支；同类分支合并成一行展示，但未省略分支名。

| branch | classification | unique commits | decision | reason |
| --- | --- | ---: | --- | --- |
| `main` | `EXACT_MAIN` | 0 | 基线 | 与初始 `github/main` 同 SHA。 |
| `nas/main` | `MERGED_ANCESTOR` | 0 | 普通 fast-forward 同步 | 初始落后 88，tip 已在 main 历史；发布时同步到 `ebcd3535`。 |
| `codex-A/engineering-hardening` | `MERGED_ANCESTOR` | 0 | 验证后本地退休 | tip 是 main ancestor，已有 merge `ab2f4c64`；不制造空 merge。 |
| `codex-A/engineering-hardening-latest-integration` | `MERGED_ANCESTOR` | 0 | 本地退休 | 全部提交已在 main。 |
| `codex-A/formal-main-merge` | `UNIQUE_REQUIRES_ADAPTATION` | 4 | 逐提交重放后本地退休 | 仅有长期测试和历史证据，无生产代码 unique diff。 |
| `codex-A/ssh-relay-auto-host-key` | `PATCH_EQUIVALENT` | 0 | 不合并，本地退休 | `git cherry` 两项均为 `-`，主线已有等价提交。 |
| `codex-A/trackside-ap-compact-unauth` | `PATCH_EQUIVALENT` | 0 | 不合并，本地退休 | `git cherry` 为 `-`，主线已有等价提交。 |
| `codex-A/v1.5.6-main-consolidation-20260909` | `INTEGRATED_RC` | 0（最终） | fast-forward 进入 main 后本地退休 | 最终 RC tip `af139928` 是 main ancestor。 |
| `codex-A/data-root-production-guard`, `codex-A/device-default-group-sort`, `codex-A/fix-fit-ap-lldp-convergence`, `codex-A/history-store-full-retirement-20260829`, `codex-A/local-gate-baseline`, `codex-A/perf-evidence-validation`, `codex-A/perf-site-loading`, `codex-A/perf-site-switch-phase2`, `codex-A/production-cutover-blockers`, `codex-A/production-storage-governance-20260829`, `codex-A/remove-production-gui-guard-mesh-raw-export`, `codex-A/root-layout-governance`, `codex-A/site-ssh-relay`, `codex-A/tasks-db-main-integration`, `codex-A/trackside-ap-authority-closure`, `codex-A/tray-site-sync`, `codex-A/typed-retention-authority-fix`, `codex-A/unify-trackside-ap-optical-header` | `MERGED_ANCESTOR` | 各 0 | 不重复合并 | 所有 tip 均已在 main 历史。 |
| `codex-A/ssh-relay-p1-main` | `EXACT_MAIN` | 0 | 不重复合并 | 与初始 main 完全同 SHA。 |
| `codex-B/fix/udp-syslog-reliable-spool` | `UNIQUE_REQUIRES_ADAPTATION` | 3 | 适配为 `0b6f7307` | 保留 UDP 可靠 spool、磁盘保护、归档隔离及长期测试；舍弃根目录临时报表。 |
| `codex-B/fix/storage-io-profile` | `UNIQUE_REQUIRES_ADAPTATION` | 4（其中前三个属于 UDP 栈） | 增量适配为 `53b70cad` | 只检测 DataRoot 所在卷，保守 fallback，不引入未实现声明。 |
| `codex-B/feat/field-diagnostic-bundle` | `UNIQUE_REQUIRES_ADAPTATION` | 7（嵌套前两层） | 末 3 项适配为 `7446d695` | 当前局点/当前卷、Raw 默认关闭、受管 Artifact/Task Center/Save As。 |
| `codex-B/sites-root-storage-audit`, `codex-B/storage-analysis`, `codex-B/storage-audit-utility`, `codex-B/storage-deep-analysis`, `codex-B/storage-lifecycle-analysis`, `codex-B/storage-management-view`, `codex-B/storage-real-data-validation`, `codex-B/storage-report-generator`, `codex-B/storage-retention-policy` | `MERGED_ANCESTOR` | 各 0 | 不重复合并 | 已在 main；不恢复旧实现，也不复制真实数据。 |
| `recovery/main-dirty-20260829`, `recovery/tasks-db-audit-20260827` | `RECOVERY_PROTECTED` | 各 0 | 永久保留远端 | 恢复引用不因内容已进入 main 而删除。 |

审计硬结论：`BRANCH_INVENTORY = COMPLETE`，`UNPROVEN_BRANCH_MERGE = 0`。

## C. Integrated Functions

| 来源 branch / commit | 新 main commit | 功能 | 影响范围 | risk | 主要 consumer |
| --- | --- | --- | --- | --- | --- |
| `formal-main-merge` `cc9a5256` | `af4d4df2` | RC 基线完成记录 | Docs | L1 | 发布治理、历史审计 |
| `formal-main-merge` `ff7282f3` | `81c364f6` | RC 报告格式修正 | Docs | L0 | 文档消费者 |
| `formal-main-merge` `50e2f29c` | `d22cdba6` | E3 真实设备只读复验阻断记录 | Docs | L1 | E3 验收、现场维护治理 |
| `formal-main-merge` `01c288e0` | `d7ff8236` | E3 SSH 根因和离线连接路径契约 | Tests, Docs | L2 | target/credential/PathResolver/Netmiko/Command Guard/Relay |
| `formal-main-merge` 历史语境修正 | `486cd932` | 明确旧 RC、旧版本、旧 main 均为当时事实 | Docs | L0 | 历史审计 |
| `codex-B/fix/udp-syslog-reliable-spool` `2f6114a2`, `2a90b5f6`, `b1f42b71` | `0b6f7307` | Ground UDP 可靠落盘、受管 spool、磁盘保护、归档隔离 | Backend, API DTO, Renderer types, Tests, Docs | L3 | Ground Supervisor/Receiver/Archive/UI |
| `codex-B/fix/storage-io-profile` `d6bbefef` | `53b70cad` | 数据盘介质检测和 Ground 自适应写入策略 | Core Storage, Ground, Renderer, Tests, Docs | L3 | DataRoot、Supervisor、Raw writer |
| `codex-B/feat/field-diagnostic-bundle` `cc16c04e`, `41091dcb`, `6678f5e8` | `7446d695` | 现场诊断包和受管导出流程 | Backend/API/Export/Task/Renderer/Tests/Docs | L3 | System Maintenance、Artifact、Task Center、Save As |
| 集成树质量债务 | `6a7d8c34` | 质量 baseline 清零并对齐 Registry | Config, Quality scripts, Backend, Tests, Docs | L3 | full local gate、architecture guard |
| 首轮 full gate 根因修复 | `af139928` | Ground DTO、legacy flush 兼容、长期文档命名 | Backend, Renderer, Tests, Docs | L3 | Ground API/diagnostic、Raw writer、docs/path guard |
| 正式版本步进 | `ebcd3535` | v1.5.6 产品版本、桌面身份、UI、更新日志 | Python, Electron, Renderer, Release Docs | L4 | Backend/Renderer/Electron/NSIS/update policy |

## D. Skipped Branches

- `already merged`：所有 `MERGED_ANCESTOR` 分支不再合并；其提交已在 main 历史中。
- `patch-equivalent`：SSH Relay host-key 与轨旁 AP 分支通过 `git cherry` 证明 patch 等价，不把旧分叉树回灌到新 main。
- `superseded`：旧 RC 中的当前状态声明不作为今天状态；保留历史 SHA，并由 `486cd932` 添加历史语境。
- `obsolete/temporary`：codex-B 根目录一次性 Audit/Review 报告未进入主线；长期边界进入 canonical Docs 和测试。
- `experimental/unknown`：没有未证明分支被盲合。
- `protected`：两个 `recovery/*` 和全部 GitHub 远端分支继续保留。

## E. Conflict Resolution

本轮 cherry-pick 没有文本冲突；以下为首轮全量门禁暴露并修复的语义冲突。

| file / area | 当前 main 行为 | 旧分支行为 | 最终行为与原因 | 验证 |
| --- | --- | --- | --- | --- |
| `src/netconsole/models/api/ground_unattended.py`、Renderer Ground types、field diagnostic safe fields | DTO/前端类型是正式契约 | 新指标写入 runtime，但 API/诊断契约不完整 | 补齐 6 个存储/落盘指标，保持端到端同名字段 | Ground/diagnostic 组合 116 passed；full gate |
| `src/netconsole/services/ground_unattended/syslog_runtime.py` | Fleet Ping 依赖逐文件 `flush_records/flush_interval` | 新 profile 逻辑无条件按 byte threshold 和跨文件 durable sync | 仅显式传入 `storage_profile` 时启用 byte threshold/periodic durable sync；未显式传入保持旧语义。正式 Syslog Supervisor 显式传 profile | 定向 9 passed；新增 profile 正向契约；full gate |
| `docs/storage/FIELD_DIAGNOSTIC_*`、`STORAGE_IO_*` | 活动文档必须使用长期能力/基线命名 | 引入 `*_AUDIT.md` 活动文档 | 重命名为 `FIELD_DIAGNOSTIC_CAPABILITY.md`、`STORAGE_IO_BASELINE.md`，修复索引 | docs/path guard、full gate |
| storage profile | 当前 DataRoot 是唯一数据位置 authority | 旧实现可能扩大卷扫描与声明 | 只检测 DataRoot 所在卷；识别失败使用保守策略 | storage profile tests、full gate |
| field diagnostic export | 受管 Artifact、Task Center、Save As 是统一边界 | 旧分支存在扩大扫描/Raw 收集风险 | 当前局点/当前卷；Raw 默认 false 且需显式勾选 | field diagnostic/system maintenance/renderer tests |

首轮 RC full gate 的 3 个失败类别全部被 `af139928` 修复，修复后 RC、main 和 v1.5.6 三轮权威 full gate 均通过；`MAIN_FUNCTION_REGRESSION = 0`。

## F. Regression

| 阶段 | command | exit | 结果 | duration |
| --- | --- | ---: | --- | --- |
| E3 长期契约 | `.\.venv\Scripts\python.exe -m pytest tests/test_e3_ssh_connection_path.py -q` | 0 | 3 passed | 未单独采集 |
| E3 consumer gate | 依据 Change Impact 选择 SSH factory、Netmiko、credential、collection、Command Guard、SSH/Site Relay、H3C、interface discovery、shadow/replay、repository isolation 测试并运行 `pytest ... -q` | 0 | 205 passed, 1 warning | 未单独采集 |
| 首轮失败修复定向 | `.\.venv\Scripts\python.exe -m pytest <Ground/storage/diagnostic targeted tests> -q` | 0 | 9 passed | 未单独采集 |
| 修复后组合 | `.\.venv\Scripts\python.exe -m pytest <Ground/storage/diagnostic/docs consumers> -q` | 0 | 116 passed | 237.64s |
| RC full | `.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full` | 0 | Python 4798 passed, 2 skipped, 33 warnings；Renderer 181 files / 1296 tests；Electron 37 files / 298 tests；main smoke 12 passed, 3 warnings；其余 quality/docs/diff gates PASS | Python 1349.42s |
| RC architecture | `.\.venv\Scripts\python.exe scripts\architecture\run_all.py` | 0 | 12/12 PASS | 见命令输出 |
| RC diff | `git diff --check` | 0 | PASS | <1s |
| RC collect | `.\.venv\Scripts\python.exe -m pytest --collect-only -q` | 0 | 4800 collected | 4.18s |
| main post-merge full | `.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full` | 0 | Python 4798 passed, 2 skipped；Renderer 1296；Electron 298；architecture 12/12；main smoke 12；全部 gate PASS | Python 1375.26s |
| v1.5.6 final full | `.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full` | 0 | Python 4798 passed, 2 skipped；Renderer 1296；Electron 298；architecture 12/12；main smoke 12；全部 gate PASS | Python 1322.75s |
| package preflight | `.\scripts\build\package_local.ps1 -Edition preflight -NoOpenOutput` | 0 | 环境、Git、locked dependencies、Customer 配置 PASS | 见命令输出 |
| formal package | `.\scripts\build\package_local.ps1 -Edition both -NoOpenOutput` | 0 | tests passed；Full/Customer build、manifest、package smoke、hash recheck PASS | 266.345s |

三轮 full gate 均绑定各自 clean HEAD；最后一轮绑定 `ebcd35356a136bddd016de399b89bb2c49fac6ef`。测试数据仅在 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>` 隔离根中生成并由 runner 回收。

## G. Main Smoke

| 模块 | 自动化状态 | 人工/真实环境边界 |
| --- | --- | --- |
| Desktop | PASS | 包内 Electron smoke PASS；真实 GUI 安装 PENDING |
| Site | PASS | 自动化 CRUD/切换契约；真实 GUI PENDING |
| Devices | PASS | 自动化管理/凭据脱敏/兼容 profile |
| SSH Relay | PASS | 离线 factory/relay/host-key/Command Guard；真实设备 NOT RUN |
| AC | PASS | 自动化只读 API；真实 AC NOT RUN |
| FIT-AP | PASS | 全量回归 PASS；真实 AC/AP NOT RUN |
| LLDP | PASS | 全量回归 PASS；真实拓扑 NOT RUN |
| Optical | PASS | 全量回归 PASS；真实光模块 NOT RUN |
| Rail | PASS | Rail 基础数据与消费者回归 PASS |
| Trackside AP | PASS | fixed snapshot/compact/unauth 回归 PASS；现场验收 NOT RUN |
| MESH | PASS | package smoke 含 import idempotency；真实数据写验收 NOT RUN |
| Online MR | PASS | main contract smoke PASS；真实设备 NOT RUN |
| Ground | PASS | UDP/spool/storage/health/diagnostic 回归和 package smoke PASS |
| Task | PASS | main contract smoke 与终态消费者回归 PASS |
| History | PASS | Current/Recent10/bounded history 全量回归 PASS；未恢复 Legacy HistoryStore |
| Export | PASS | main contract smoke、Artifact/Save As/duplicate-safe archive PASS |
| Settings | PASS | main contract smoke PASS；真实 GUI PENDING |

`REAL_DEVICE_E3_RETRY = NOT RUN`。历史事实保持：`PHASE2D_E3_STATUS=FAIL`、`REAL_DEVICE_CONNECTION_ATTEMPTED=YES`、`FIRST_COMPARABLE_CYCLE=NOT_STARTED`、`PRODUCTION_ACTIVATION_EXECUTED=NO`、`PRODUCTION_CUTOVER_EXECUTED=NO`；后续 `ROOT_CAUSE_CATEGORY=E3_HARNESS_BUG` 不能替代真实设备 PASS。

## H. Version 1.5.6

| 消费者 | 最终事实 |
| --- | --- |
| `src/netconsole/core/version.py` | `APP_VERSION = "v1.5.6"`，产品版本事实源 |
| `apps/desktop_electron/package.json` | `version = 1.5.6` |
| Electron `productName` | `NetConsole v1.5.6 by wxj` |
| build metadata | `NETCONSOLE_BUILD_METADATA_JSON` 注入 build commit/time/dirty/build number/published；不改变 ProductVersion |
| installer metadata | `product_version=1.5.6`、`file_version=1.5.6.0`、`build_number=0`、`published=false` |
| UI display | Renderer title `NetConsole v1.5.6 by wxj` |
| release commit | `ebcd35356a136bddd016de399b89bb2c49fac6ef` |
| annotated tag | `v1.5.6^{}` = `ebcd35356a136bddd016de399b89bb2c49fac6ef` |

`PYTHON_ELECTRON_VERSION_SYNC = PASS`。本地正式打包清单的 `published=false` 是预期策略；本任务没有伪装为自动更新源发布。

## I. Package

发布目录：`D:\study\NetConsole-Workspace\release\v1.5.6\build-0-ebcd3535`

| edition | installer | size | SHA256 | git commit | packaged dirty | package smoke | real GUI install | server installation |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| Full | `NetConsole-Full-1.5.6.0-ebcd3535-x64-setup.exe` | 157134683 bytes | `4fb80b4591965a490549fad033bebb98b4772f1f055790688131f4d67f630e34` | `ebcd3535` | false | PASS | PENDING | PENDING |
| Customer | `NetConsole-Customer-1.5.6.0-ebcd3535-x64-setup.exe` | 157134880 bytes | `94e5971e6f69b279c6031269f5d1f428e53ec67dc3893babb8a0bb7b1ffd5d3b` | `ebcd3535` | false | PASS | PENDING | PENDING |

两个安装包的 SHA256 已在归档后重新计算并与 `SHA256SUMS.txt`、各自 `.release.json` 和 `BUILD_SUMMARY.json` 一致。`FULL_PACKAGE = PASS`，`CUSTOMER_PACKAGE = PASS`，`PACKAGE_IDENTITY = PASS`。

## J. Branch Retirement

| 项目 | 结果 |
| --- | --- |
| before count | 7 个本地分支、3 个 worktree（含主工作树） |
| removed worktrees | `engineering-hardening`、`formal-main-merge`；移除前均 clean，路径已解析并验证位于受控 worktrees 根内 |
| deleted local branches | `codex-A/engineering-hardening`、`codex-A/engineering-hardening-latest-integration`、`codex-A/formal-main-merge`、`codex-A/ssh-relay-auto-host-key`、`codex-A/trackside-ap-compact-unauth`、`codex-A/v1.5.6-main-consolidation-20260909` |
| protected branches | 全部 GitHub 远端分支；尤其 `recovery/main-dirty-20260829`、`recovery/tasks-db-audit-20260827` |
| after count | 1 个本地分支 `main`、1 个主 worktree |
| remote result | 未删除任何远端分支；指定分支远端 tip 与回收前本地 tip 一致，可恢复 |

`LOCAL_WORKTREE_RETIREMENT = PASS`，`LOCAL_BRANCH_RETIREMENT = PASS`，`REMOTE_BRANCHES_RETAINED = YES`。

## Specified Branch Integration

### `codex-A/engineering-hardening`

- initial tip：`65a6e2550e071075a3d40325799166197e9378b8`
- merge-base：`65a6e2550e071075a3d40325799166197e9378b8`
- 初始关系：main behind/ahead branch = `38 / 0`；最终回收前为 `51 / 0`
- ancestor result：`git merge-base --is-ancestor codex-A/engineering-hardening main` exit 0，`ENGINEERING_HARDENING_ANCESTOR = YES`
- unique commits：0
- existing main merge：`ab2f4c649887db34c9c6d510bf541eb8ca2a6178`（合并工程加固到正式主线）
- current verification：engineering-hardening workflow、baseline-aware regression、architecture contract、Python/Renderer/Electron、main smoke、docs/path guard、baseline debt、DataRoot 隔离与正式 full gate 均由当前 main 再验证；不回退到旧文件版本
- final classification：`MERGED_ANCESTOR`
- retirement：worktree clean 后移除；同名远端 tip `65a6e255` 已确认存在；本地 branch 使用安全删除回收

硬结论：`ENGINEERING_HARDENING_UNIQUE_COMMITS = 0`，`ENGINEERING_HARDENING_IN_MAIN = PASS`，`ENGINEERING_HARDENING_REGRESSION = 0`。没有制造第二个 merge commit，因为 branch 已是 main ancestor；额外 merge 只会产生无功能差异的治理噪声。

### `codex-A/formal-main-merge`

- initial tip：`01c288e04b6d678ef2a0f9af6eac7f33602a0e6a`
- initial merge-base：`bc9c00f09d2e6698a2c25391ea917ef3872ff98e`
- 初始关系：main behind/ahead branch = `5 / 4`；最终回收前为 `18 / 4`
- unique commits：原始 4 个；回收前 `git cherry -v main branch` 全部为 `-`
- unique files：4 份历史文档 + `tests/test_e3_ssh_connection_path.py`
- production diff：`src/`、`apps/`、`config/`、`resources/`、`scripts/build/` unique = 0
- tests integrated：E3 connection path 3 tests 正式进入 main；consumer suite 205 passed，full gate 三轮通过
- docs integrated：4 个 source commit 分别重放为 `af4d4df2`、`81c364f6`、`d22cdba6`、`d7ff8236`；另有 `486cd932` 添加历史语境
- patch equivalence：四对 source/replay commit 的 stable patch-id 均完全相同
- historical status：E3 首次真实设备 FAIL、已连接尝试、未开始首轮可比采集、未执行生产激活/切换均原样保留
- conflicts：无文本冲突；旧 RC 的“当前”措辞按历史语境修正，不修改历史 SHA；无旧生产实现回灌
- retirement：同名 GitHub 远端 tip `01c288e0` 已确认；完整等价证据成立后移除 clean worktree，并按用户授权强制回收非祖先的本地 branch

硬结论：`FORMAL_MAIN_MERGE_AUDIT = COMPLETE`，`FORMAL_MAIN_VALID_TESTS_IN_MAIN = PASS`，`FORMAL_MAIN_VALID_EVIDENCE_IN_MAIN = PASS`，`E3_CONNECTION_PATH_CONTRACT_IN_MAIN = PASS`，`FORMAL_MAIN_PRODUCTION_UNEXPECTED_DIFF = 0`，`FORMAL_MAIN_MERGE_INTEGRATION = PASS`。

## K. Final State

| 项目 | 最终状态 |
| --- | --- |
| `FINAL_MAIN_SHA` | `ebcd35356a136bddd016de399b89bb2c49fac6ef`（受测、打包、打标签的最终产品树；本报告随后以 docs-only commit 入库） |
| `FINAL_GITHUB_MAIN_SHA` | 发布锁定时为 `ebcd35356a136bddd016de399b89bb2c49fac6ef`；本报告推送后 main 仅前进一个 docs-only 治理提交 |
| `FINAL_NAS_MAIN_SHA` | 发布锁定时为 `ebcd35356a136bddd016de399b89bb2c49fac6ef`；本报告推送后同 GitHub docs-only 前进 |
| `FINAL_VERSION` | `v1.5.6` |
| `FINAL_TAG_SHA` | GitHub/NAS `v1.5.6^{}` = `ebcd35356a136bddd016de399b89bb2c49fac6ef` |
| `WORKTREE_CLEAN` | PASS（发布锁定点 clean；最终报告提交后再次复核） |
| `RC_FULL_GATE` | PASS |
| `MAIN_POST_MERGE_FULL_GATE` | PASS |
| `V1_5_6_FINAL_FULL_GATE` | PASS |
| `ARCHITECTURE_GATE` | PASS（12/12） |
| `PACKAGE_GATE` | PASS（Full + Customer） |
| `GITHUB_MAIN_PUSH` | PASS |
| `NAS_MAIN_PUSH` | PASS |
| `LOCAL_BRANCH_CLEANUP` | COMPLETE（7 → 1） |

最终硬结论：

```text
BRANCH_INVENTORY = COMPLETE
UNPROVEN_BRANCH_MERGE = 0
ENGINEERING_HARDENING_IN_MAIN = PASS
FORMAL_MAIN_MERGE_IN_MAIN = PASS
E3_CONTRACT_IN_MAIN = PASS
MAIN_REGRESSION = 0
RC_FULL_GATE = PASS
MAIN_POST_MERGE_FULL_GATE = PASS
V1_5_6_FINAL_FULL_GATE = PASS
ARCHITECTURE_GATE = PASS
FULL_PACKAGE = PASS
CUSTOMER_PACKAGE = PASS
PACKAGE_IDENTITY = PASS
LOCAL_WORKTREE_RETIREMENT = PASS
LOCAL_BRANCH_RETIREMENT = PASS
REMOTE_BRANCHES_RETAINED = YES
V1_5_6_VERSION_BUMP_ALLOWED = YES
REAL_DEVICE_E3_RETRY = NOT RUN
REAL_WINDOWS_GUI_INSTALL = PENDING
SERVER_INSTALLATION = PENDING
FINAL_ACCEPTANCE = PASS
```
