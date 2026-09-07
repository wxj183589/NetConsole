# Formal Main Merge & RC Baseline Verification

日期：2026-09-08  
Agent：codex-A  
Codex-Thread：01a06938-7fc7-7741-a94c-c1007d93899b

## 结论

正式主线合并已完成，工程门禁与 Full/Customer RC 包验证通过。由于最新 `github/main` 在 E0 之后新增并合入了 H3C 设备连接、采集和设备操作相关语义，必须重新进行真实设备只读复核；本阶段严格不连接真实设备，因此不宣布 RC 可进入生产 Cutover。

```text
FORMAL_MAIN_MERGE=PASS
FORMAL_MAIN_BASELINE_ESTABLISHED=YES
RC_BASELINE_READY=NO
PHASE2D_E1_STATUS=HOLD
REAL_DEVICE_REVALIDATION_REQUIRED=YES
REAL_DEVICE_CONNECTED=NO
PRODUCTION_DATA_TOUCHED=NO
```

## Preflight

- E1 独立 worktree：`codex-A/formal-main-merge`。
- 开始时以最新 `github/main` 为基线：`e412eca7ff82a01eb108ef859c292bf17e9050a4`。
- 形式合并前工作树 clean；未使用 reset、restore、stash、clean、rebase、squash 或 force push。
- 正式主线最终验证前后均未连接真实设备，未执行生产备份、恢复、activation 或 Wave 1。
- 主仓库和 DevStatus 主 checkout 未被本阶段修改；所有变更在独立 worktree 完成。

## Main Drift Audit

E0 记录的主线锚点为 `6e6b4db062ed644250ebe4abdd1d0eac40d315a1`，工程加固集成分支期望头为 `8a380ccbd2b973a66ff229a8c0369ff11fa7fbfa`。最新主线相对 E0 新增了 8 个 SSH Relay/site 相关提交，并涉及 H3C collector、device operation、Netmiko connection、site storage 等关键路径。

```text
MAIN_DRIFT=YES
MAIN_DRIFT_CLASSIFICATION=SEMANTIC_REVALIDATION_REQUIRED
INTEGRATION_EXPECTED_HEAD=8a380ccbd2b973a66ff229a8c0369ff11fa7fbfa
MERGE_BASE=6e6b4db062ed644250ebe4abdd1d0eac40d315a1
REMOTE_MAIN_BEFORE_MERGE=e412eca7ff82a01eb108ef859c292bf17e9050a4
```

Drift commits audited：

```text
e412eca7 记录v1.5.5客户版交接提交
654a6fcc 补充v1.5.5交接提交
44dbffb5 更新v1.5.5最终Production包信息
a110e1e9 补齐v1.5.5正式包收口信息
323f67ad 收口v1.5.5 SSH Relay现场验收
9fe16726 补齐SSH中转现场打包报告
bc0d2054 收口局点 SSH 中转统一设备连接出口
25165252 增加局点级 SSH 中转能力
```

关键路径 drift 触发离线回归和后续真实设备复核要求；没有借此自动扩大设备范围或自动连接 C7/C9 设备。

## Formal Merge

使用正常 non-fast-forward 合并：

```text
MERGE_COMMAND=git merge --no-ff --no-commit github/codex-A/engineering-hardening-latest-integration
MERGE_RESULT=PASS
MERGE_CONFLICTS=0
MERGE_COMMIT=ab2f4c64
```

随后仅进行了两类收口变更：架构基线行号锚点维护，以及 CI runner 的隔离测试根、Python/Renderer 依赖和 Electron 环境修复。没有修改生产采集器、Parser、DTO、Repository contract、Command Profile 或任务状态机。

最终正式主线提交序列包含：

```text
ab2f4c64 合并工程加固到正式主线
c91811f7 维护架构基线行号锚点
85426208 修正工程门禁的隔离路径与依赖
dd38313a 完善主线门禁的 CI Python 环境
d5554c11 修正 Electron 门禁的 Python 工作目录
cbc06c88 统一 CI 测试数据根的安全映射
```

CI 修复仅作用于 GitHub Actions runner：使用每次运行独立的测试根，并通过 runner-only junction 兼容既有固定测试路径；不指向生产数据，也不改变应用运行时生产路径。

## RC Baseline Verification

本地正式 worktree 回归结果：

- Python targeted core：149 passed。
- Python full regression：4760 passed，2 skipped，4 deselected；无新增失败。
- Renderer：串行完整测试 1290 passed；typecheck、build PASS。
- Electron：37 个测试文件、298 tests passed；typecheck、main build PASS。
- Main drift focused tests：63 passed。
- Shadow、B1 rehearsal、replay、repository、device inventory、docs/path：67 passed。
- Main contract：12 passed。
- Ruff、compileall、`git diff --check`：PASS。
- Architecture：稳定 green gates PASS；exact baseline 命中既有 7 项架构债务，未增加新项。
- Baseline audit：manifest PASS，`ARCHITECTURE_BASELINE_NEW=0`，`NEW_FAILURES=0`，`BASELINE_DEBT_MATCH=PASS`。

已知基线债务按仓库 manifest 保留并精确匹配；本阶段未掩盖、删除或扩大基线。

## RC Packages

Full 与 Customer 均从 formal main 的应用代码构建，版本一致为 `1.5.5`，`PACKAGED_DIRTY=false`，安装包 smoke、Electron packaged smoke、7-Zip 提取完整性检查均通过。构建为本地 RC 验证，`PUBLISHED=false`；未执行 release、tag、publish 或自动更新发布。

## Remote CI

远端 workflow 已覆盖 Python、Renderer、Electron、Architecture、Main contract、Docs/path/diff、Baseline audit。运行 `34151945963` 已验证模块路径、隔离数据根、Renderer 串行化和 Electron 依赖修复，但 Python job 暴露出另一个 runner 环境差异：GitHub hosted Python `3.13` 解析为 `3.13.15`，而项目受控 Notice/打包事实源是 `3.13.9`，导致 4 个与 SBOM/干净 PyInstaller 构建事实源一致性相关的失败。该问题不是业务代码回归；CI runner 已进一步固定为项目事实源 `3.13.9`，等待同一正式主线重新验证。

```text
REMOTE_MAIN_CI_REQUIRED=YES
REMOTE_MAIN_CI_INITIAL_RUN=34151945963
REMOTE_MAIN_CI_INITIAL_STATUS=FAIL_ENVIRONMENT_VERSION_MISMATCH
REMOTE_MAIN_CI_STATUS=REVALIDATION_PENDING
REQUIRED_CHECKS_STATUS=NOT_CONFIGURED
```

GitHub `main` 分支保护查询返回 404，表示当前仓库未配置分支保护规则；本阶段仍执行了完整 workflow 验证，没有绕过检查。

## Production Safety

```text
REAL_DEVICE_CONNECTED=NO
PRODUCTION_DATA_TOUCHED=NO
PRODUCTION_BACKUP=NOT_EXECUTED
PRODUCTION_RESTORE=NOT_EXECUTED
PRODUCTION_ACTIVATION=NOT_EXECUTED
WAVE0_EXECUTED=NO
WAVE1_EXECUTED=NO
C9_ACTIVATED=NO
WIRELESS_CONTROLLER_ACTIVATED=NO
ZTE_ACTIVATED=NO
OTHER_C7_SWITCH_ACTIVATED=NO
```

E1 不继承之前真实设备验证或维护窗口批准，不执行 `DEVICE-NB10-C7-01` 的新的真实设备复核。由于 main drift 触及 H3C 连接/采集语义，下一次真实设备复核必须由单独授权流程重新确认范围、维护窗口、备份和 owner approval；在此之前默认生产路径继续为 Legacy。

## Change Classification

```text
LEGACY_COLLECTOR_CHANGED=NO
PARSER_CHANGED=NO
DTO_CHANGED=NO
REPOSITORY_WRITE_PATH_CHANGED=NO
PROFILE_CHANGED=NO
OPERATION_ID_ADDED=NO
FEATURE_FLAG_ADDED=NO
API_CHANGED=NO
UI_CHANGED=NO
TASK_STATE_MACHINE_CHANGED=NO
DATABASE_SCHEMA_CHANGED=NO
```

本阶段有正式主线合并和 CI/baseline governance 变更，但没有在 E1 现场修改生产业务代码或数据库 schema。

## Evidence and Handoff

- 本阶段没有生成真实设备 raw CLI evidence、生产数据库备份或凭据。
- 测试输出和构建目录均为本地/runner 临时产物，不提交 Git。
- 本报告不包含 IP、hostname、用户名、密码、Token、SNMP community、MAC 或序列号。
- Secret scan 与 tracked diff 敏感信息检查通过。
- DevStatus 通过独立 worktree 更新，记录正式主线 HEAD、回归门禁、CI、RC 包和待办的真实设备复核。

## Final Decision

```text
FORMAL_MAIN_MERGE=PASS
RC_ENGINEERING_GATES=PASS
RC_PACKAGE_VALIDATION=PASS
REAL_DEVICE_REVALIDATION_REQUIRED=YES
PHASE2D_E1_STATUS=HOLD
PHASE2D_E_READY=NO
PHASE2D_READY=NO
PRODUCTION_PATH=LEGACY
```

本阶段仅建立正式主线工程基线，不构成 Production Cutover 批准。下一步是经单独审批后，对受影响的 H3C 连接/采集语义执行限定设备的真实只读复核；不得自动进入 Wave 0、Wave 1、Comware 9、AC、ZTE 或其他未授权范围。
