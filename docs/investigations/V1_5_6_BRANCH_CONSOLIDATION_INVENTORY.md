# v1.5.6 主线分支收口清单

审计时间：2026-09-09（Asia/Shanghai）  
事实基线：`main = github/main = 6d0cd921c07d7a6a48d46b7278019fdcf4d4712f`  
初始物理引用：本地 6、GitHub 39、NAS 1（均排除 remote `HEAD` alias）；创建一次性 RC 后本地为 7。为避免把同名本地/远端重复当成功能分支，下表按逻辑分支合并展示，并把 SHA 不同的 `nas/main` 单列，共 41 行。所有 short SHA 均由本轮 `git rev-parse` 获取。

`behind/ahead` 是 `git rev-list --left-right --count main...<ref>` 的结果；`unique` 是 `git log --cherry-pick --right-only main...<ref>` 的 patch-unique 数。`files` 优先记录 patch-unique 文件数；候选旧栈同时注明三点 diff 文件数。

## 完整清单

| branch | location / upstream / worktree | tip / merge-base | behind / ahead / unique | date / tip subject | files / domains | risk | classification | action / reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `main` | local+github / `github/main` / no | `6d0cd921` / `6d0cd921` | 0 / 0 / 0 | 2026-09-09 / 补充 v1.5.5 最终验收与发布收口记录 | 0 | L0 | `EXACT_MAIN` | 作为初始正式基线，不重复合并。 |
| `nas/main` | nas / remote / no | `3cde965d` / `3cde965d` | 88 / 0 / 0 | 2026-09-02 / 完善 v1.5.5 版本同步校验 | 0 unique | L0 | `MERGED_ANCESTOR` | NAS 落后但其 tip 已在 main 历史中；最终仅普通 push 同步，不删除分支。 |
| `codex-A/data-root-production-guard` | github / remote / no | `695a9ca7` / same | 195 / 0 / 0 | 2026-08-21 / 增加 DEV COPY tasks payload 深度分析 | 0 unique | L0 | `MERGED_ANCESTOR` | 全部提交已在 main。 |
| `codex-A/device-default-group-sort` | github / remote / no | `6b910f4d` / same | 81 / 0 / 0 | 2026-09-03 / 修复设备管理默认分组排序 | 0 unique | L0 | `MERGED_ANCESTOR` | 全部提交已在 main。 |
| `codex-A/engineering-hardening` | local+github / same-name / yes | `65a6e255` / same | 38 / 0 / 0 | 2026-09-07 / 记录 Wave 0 备份门禁阻断 | 0 unique | L1 | `MERGED_ANCESTOR` | 已由主线 merge `ab2f4c64` 收口；验证当前实现后退休本地 worktree/branch，不制造空 merge。 |
| `codex-A/engineering-hardening-latest-integration` | local+github / same-name / no | `8a380ccb` / same | 27 / 0 / 0 | 2026-09-07 / 记录最新主线集成验证 | 0 unique | L0 | `MERGED_ANCESTOR` | 全部提交已在 main；最终可安全删除本地副本。 |
| `codex-A/fix-fit-ap-lldp-convergence` | github / remote / no | `027d48af` / same | 194 / 0 / 0 | 2026-08-21 / fix(fit-ap): show converged latest lldp relations | 0 unique | L0 | `MERGED_ANCESTOR` | 全部提交已在 main。 |
| `codex-A/formal-main-merge` | local+github / local upstream `github/main` / yes | `01c288e0` / `bc9c00f0` | 5 / 4 / 4 | 2026-09-09 / docs(dev): 记录 E3 SSH 根因与离线修复验证 | 5 / Tests, Docs | L2 | `UNIQUE_REQUIRES_ADAPTATION` | 逐提交重放到最新 RC；保留失败历史和长期离线契约，不回灌旧 RC 状态。 |
| `codex-A/history-store-full-retirement-20260829` | github / remote / no | `99d427e4` / same | 149 / 0 / 0 | 2026-08-29 / 完善开发数据 HistoryStore 退役入口 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main；禁止恢复 Legacy HistoryStore。 |
| `codex-A/local-gate-baseline` | github / remote / no | `4804c456` / same | 166 / 0 / 0 | 2026-08-27 / 清理主线 local gate 既有阻塞项 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/perf-evidence-validation` | github / remote / no | `474c8fe6` / same | 196 / 0 / 0 | 2026-08-21 / perf: optimize site loading and large table performance | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/perf-site-loading` | github / remote / no | `474c8fe6` / same | 196 / 0 / 0 | 2026-08-21 / perf: optimize site loading and large table performance | 0 unique | L0 | `MERGED_ANCESTOR` | 与上一分支同 tip，已在 main。 |
| `codex-A/perf-site-switch-phase2` | github / remote / no | `4a13213e` / same | 195 / 0 / 0 | 2026-08-22 / perf(site): eliminate backend restart bottleneck during site switching | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/production-cutover-blockers` | github / remote / no | `97e21d01` / same | 159 / 0 / 0 | 2026-08-28 / 修复生产切换期间数据库恢复契约 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main；本轮不执行 Production cutover。 |
| `codex-A/production-storage-governance-20260829` | github / remote / no | `ee1e7e10` / same | 154 / 0 / 0 | 2026-08-29 / 修正存储退役零字节文件门禁 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/remove-production-gui-guard-mesh-raw-export` | github / remote / no | `58542cf9` / same | 85 / 0 / 0 | 2026-09-03 / feat: 收口轻量包与完整版统一导入链路 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/root-layout-governance` | github / remote / no | `962a4ae8` / same | 168 / 0 / 0 | 2026-08-27 / 收口仓库根目录工程文档并增加布局门禁 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main；根目录临时报表不得回灌。 |
| `codex-A/site-ssh-relay` | github / remote / no | `9fe16726` / same | 64 / 0 / 0 | 2026-09-07 / 补齐SSH中转现场打包报告 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/ssh-relay-auto-host-key` | local+github / same-name / no | `a48dc5f` / `e412eca7` | 58 / 2 / 0 | 2026-09-08 / SSH Relay 跳板机主机指纹自动维护与启动恢复 | 0 patch-unique；36 historical triple-dot / Backend, Renderer, Tests, Docs | L1 | `PATCH_EQUIVALENT` | 两个提交均由 `git cherry` 标记 `-`；main 等价提交为 `0bb837ff`、`f9ac0965`，不再合并。 |
| `codex-A/ssh-relay-p1-main` | github / remote / no | `6d0cd921` / same | 0 / 0 / 0 | 2026-09-09 / 补充 v1.5.5 最终验收与发布收口记录 | 0 | L0 | `EXACT_MAIN` | 与初始 main 完全同 SHA。 |
| `codex-A/tasks-db-main-integration` | github / remote / no | `447b3ede` / same | 167 / 0 / 0 | 2026-08-27 / 收口 tasks.db 结果存储轻量化与治理契约 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/trackside-ap-authority-closure` | github / remote / no | `59bb760a` / same | 158 / 0 / 0 | 2026-08-29 / 收口轨旁AP采集与上线离线光衰权威口径 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/trackside-ap-compact-unauth` | local+github / same-name / no | `5ebe6b1d` / `e412eca7` | 58 / 1 / 0 | 2026-09-08 / 轨旁AP紧凑布局与未认证快照语义修正 | 0 patch-unique；21 historical triple-dot / Backend, Renderer, Tests | L1 | `PATCH_EQUIVALENT` | `git cherry` 为 `-`，main 等价提交 `0bb837ff`；不覆盖更新后的主线实现。 |
| `codex-A/tray-site-sync` | github / remote / no | `afa2e5cf` / same | 73 / 0 / 0 | 2026-09-04 / docs: record tray site sync gui acceptance | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/typed-retention-authority-fix` | github / remote / no | `be7e639d` / same | 165 / 0 / 0 | 2026-08-27 / 修复 typed retention Blob authority apply 一致性 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/unify-trackside-ap-optical-header` | github / remote / no | `c75bc9e2` / same | 73 / 0 / 0 | 2026-09-07 / 统一轨旁AP光衰问题表头 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-A/v1.5.6-main-consolidation-20260909` | local / none / yes | `6a7d8c34` / `6d0cd921` | 0 / 9 / 9 | 2026-09-09 / 清零主线质量基线债务 | 51 / Backend, Renderer, Tests, Docs, Config | L4 | `ACTIVE_WORKTREE_PROTECTED` | 当前一次性集成 RC；完成全量 gate 后仅以 ff-only 进入 main。 |
| `codex-B/fix/udp-syslog-reliable-spool` | github / remote / no | `b1f42b71` / `14636474` | 76 / 3 / 3 | 2026-09-04 / fix: add udp spool disk guard and archive isolation | 13 triple-dot / Ground Backend, Renderer, Tests | L3 | `UNIQUE_REQUIRES_ADAPTATION` | 保留 3 个生产/测试提交的语义，以当前 Ground 契约适配；根目录临时报表不保留。 |
| `codex-B/fix/storage-io-profile` | github / remote / no | `d6bbefef` / `14636474` | 76 / 4 / 4 | 2026-09-07 / fix: add adaptive storage io profiles for hdd and ssd | 22 triple-dot；13 incremental / Storage, Ground, Renderer, Tests, Docs | L3 | `UNIQUE_REQUIRES_ADAPTATION` | 在前一栈上适配当前数据卷检测和保守 fallback，移除未实现字段/声明。 |
| `codex-B/feat/field-diagnostic-bundle` | github / remote / no | `6678f5e8` / `14636474` | 76 / 7 / 7 | 2026-09-07 / 接入Ground只读健康快照 | 39 triple-dot；17 incremental / Export, Task, Storage, Ground, Renderer, Tests, Docs | L3 | `UNIQUE_REQUIRES_ADAPTATION` | 在前两组之上只集成末 3 个提交；收敛当前局点/当前卷，Raw 改为显式选择。 |
| `codex-B/sites-root-storage-audit` | github / remote / no | `fcb1635f` / same | 191 / 0 / 0 | 2026-08-22 / storage: analyze global sites storage usage | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-analysis` | github / remote / no | `2d71131c` / same | 194 / 0 / 0 | 2026-08-21 / storage: add readonly site storage analysis reports | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-audit-utility` | github / remote / no | `d1448a54` / same | 195 / 0 / 0 | 2026-08-21 / 修复存储审计文件数量统计 | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-deep-analysis` | github / remote / no | `f2cd6e80` / same | 189 / 0 / 0 | 2026-08-22 / storage: expose history database size fields | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-lifecycle-analysis` | github / remote / no | `d7d25ff7` / same | 188 / 0 / 0 | 2026-08-22 / storage: add lifecycle governance analysis report | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-management-view` | github / remote / no | `aaf4bd16` / same | 185 / 0 / 0 | 2026-08-24 / feat: add storage management view | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-real-data-validation` | github / remote / no | `43679671` / same | 192 / 0 / 0 | 2026-08-22 / storage: validate audit reports with real site copy | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main；本轮不复制真实数据。 |
| `codex-B/storage-report-generator` | github / remote / no | `65b1bb73` / same | 193 / 0 / 0 | 2026-08-22 / storage: add readonly storage audit report generator | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `codex-B/storage-retention-policy` | github / remote / no | `cb9dd3de` / same | 187 / 0 / 0 | 2026-08-22 / storage: add retention policy analysis | 0 unique | L0 | `MERGED_ANCESTOR` | 已在 main。 |
| `recovery/main-dirty-20260829` | github / remote / no | `f2abbd4d` / same | 168 / 0 / 0 | 2026-08-29 / 保全主工作区任务存储与验收修改 | 0 unique | high | `RECOVERY_PROTECTED` | 即使已成为祖先仍保留远程恢复引用；禁止删除。 |
| `recovery/tasks-db-audit-20260827` | github / remote / no | `023667de` / same | 166 / 0 / 0 | 2026-08-29 / 保全 tasks-db 审计 worktree 修改 | 0 unique | high | `RECOVERY_PROTECTED` | 保留远程恢复引用；禁止删除。 |

## 真正 unique 的提交与文件

### `codex-A/formal-main-merge`

| source SHA | subject | files | classification | still valid | integration action |
| --- | --- | --- | --- | --- | --- |
| `cc9a5256bd22674a94ccb902b89a78707c9bb67c` | finalize RC baseline validation | 两份 RC 历史文档 | `VALIDATION_EVIDENCE` + `HISTORICAL_STATUS` | yes | 重放为 `af4d4df2`。 |
| `ff7282f3b1f2d4ac77dac54c07fe280c17c8046f` | 修正 RC 报告格式 | RC 文档 | `DOCUMENTATION` | yes | 重放为 `81c364f6`。 |
| `50e2f29cd0a17890451448fbd12550525720f5bf` | 记录 E3 只读复验阻断 | E3 历史报告 | `VALIDATION_EVIDENCE` + `HISTORICAL_STATUS` | yes | 重放为 `d22cdba6`；历史 FAIL 不改。 |
| `01c288e04b6d678ef2a0f9af6eac7f33602a0e6a` | 记录 E3 SSH 根因与离线修复验证 | 根因文档 + `tests/test_e3_ssh_connection_path.py` | `TEST_CONTRACT` + `VALIDATION_EVIDENCE` | yes | 重放为 `d7ff8236`；另以 `486cd932` 明确旧 RC 的历史语境。 |

Unique 文件仅为：

- `docs/dev/formal-main-merge-rc-baseline.md`
- `docs/dev/rc-baseline-finalization.md`
- `docs/dev/interface-discovery-e3-real-device-revalidation-report.md`
- `docs/dev/interface-discovery-e3-ssh-root-cause.md`
- `tests/test_e3_ssh_connection_path.py`

Production 路径（`src/`、`apps/`、`config/`、`resources/`、`scripts/build/`）unique diff 为 0。

### `codex-B` 三层功能栈

- UDP 层 `2f6114a2`、`2a90b5f6`、`b1f42b71`：有效代码/测试适配为 `0b6f7307`。5 份仓库根目录报告属于 `TEMPORARY_EVIDENCE`，不保留；有效边界写入 canonical Ground README 和测试。
- Storage 层 `d6bbefef`：适配为 `53b70cad`，只检测数据根所在卷，缺省使用保守策略，不保留未实现 profile 字段。
- Field Diagnostic 层 `cc16c04e`、`41091dcb`、`6678f5e8`：适配为 `7446d695`，只扫描当前局点/当前数据卷，Raw 默认关闭并需要用户明确勾选，复用受管 Artifact、Task Center 与 Save As。

## 审计结论

- 真正需要集成的历史成果只有 formal-main-merge 的 4 个 docs/test 提交和 codex-B 的 7 个嵌套提交；它们均按当前 main 语义重放或适配，没有整条盲合。
- 其余普通历史分支均为 main ancestor、exact main 或 patch-equivalent；再 merge 只会产生空提交或回灌旧实现。
- 两个 recovery 分支无条件保护；所有 GitHub 远程分支均保留。
- 本地 branch/worktree 在最终 main、v1.5.6 gate、package 和 tag 完成前继续保护。

