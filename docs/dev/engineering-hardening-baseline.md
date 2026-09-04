# NetConsole Engineering Hardening 基线与行为冻结

状态：Phase 0 已完成（只读审计结果固化）

日期：2026-09-04

基线：`1463647471d6d5836a6c0fc692062d35290aa0fd`

分支：`codex-A/engineering-hardening`

Worktree：`D:\study\NetConsole-Workspace\worktrees\engineering-hardening`

## 1. 目的与边界

本文冻结本轮工程加固的可复核起点。Phase 0 只记录事实，不修复业务代码、不调整测试期望、不改变 schema、API、UI、任务状态、设备命令或发布身份。

现有轨旁光模块工作仍属于另一个 dirty worktree：`codex-A/trackside-optical-filter`。本轮不读取其未提交 diff 作为实现输入，不修改、不格式化、不提交、不回滚该 worktree；其状态标记为 `FOREIGN_DIRTY_WORKTREE`，Phase 2 在该任务完成、推送、合入并重新核对后才能开始。

测试和审计使用隔离的 `D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`。未读取或写入 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未触碰 `D:\study\fping`，未制作完整真实数据副本。

## 2. 可复核环境

- Windows 11；CPython 3.13；Node.js `v24.18.0`；pnpm `11.19.0`。
- Renderer 和 Electron 均按各自 `pnpm-lock.yaml` 执行 `pnpm install --frozen-lockfile`。
- Python 使用仓库 `.venv`，开发依赖遵循 `requirements-dev.txt` 与 `constraints.txt` 的仓库规则。
- 本地 Gate 的报告根为源码树下 `.local-reports/`；运行数据根仍是唯一隔离测试根。
- clean worktree 的 `git status --short` 为空；`git diff --exit-code` 通过。

## 3. Phase 0 质量基线

以下结果来自基线 HEAD，命令与结果均按本地质量门的既有定义记录。`FULL_GATE=FAIL` 是基线事实，不代表本轮已授权修复这些问题。

| Gate | 基线结果 |
| --- | --- |
| Renderer Vitest | `180 files / 1281 passed` |
| Renderer `vue-tsc` | PASS |
| Renderer Vite build | PASS；存在既有 chunk size warning |
| Python full regression | `4652 passed, 4 failed, 2 skipped` |
| Electron Vitest | `36 files / 294 passed` |
| Electron typecheck | PASS |
| Electron main build | PASS |
| Architecture Guard | `4/12` failed；其余稳定 guard PASS |
| Ruff full | `4 errors` |
| Main contract smoke | `12 passed` |
| Docs/path guards | `22 passed` |
| `git diff --check` | PASS |
| Change Impact | `L2` |
| Full local gate | FAIL（仅包含上面列出的基线失败） |

### 3.1 Python 精确失败节点

这些 node ID 是当前基线的完整失败清单，后续 CI 只能按精确 node ID/清单处理，不得使用模糊 `-k`、目录级忽略或全局 `continue-on-error`：

1. `tests/architecture/test_architecture_guards.py::test_all_architecture_checks_have_no_unwaived_findings`
2. `tests/architecture/test_architecture_guards.py::test_run_all_works_from_repository_root`
3. `tests/test_version_build_identity.py::test_update_policy_ignores_build_and_hash_changes`
4. `tests/test_web_architecture.py::test_web_and_electron_ast_guards_have_no_unwaived_findings`

### 3.2 Architecture 精确发现

当前未豁免发现共 7 条，来自 4 个 guard；不得直接写入 `config/architecture/exceptions.yaml`，除非确认是真实历史例外并补齐 owner、理由、创建时间、过期时间和对应测试。

| Rule | 文件与行 | 发现 |
| --- | --- | --- |
| `DIRECT_SQL_UNCLASSIFIED` | `tests/test_database_backup_batch_delete.py:23` | 未分类的 `sqlite3.connect` |
| `UI_BUSINESS_LOGIC_UNCLASSIFIED` | `apps/desktop_renderer/src/components/mesh-analysis/meshRssiContext.ts:177` | 候选业务符号 `resolveMeshRssiPoint` |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/job_center/handlers/site_jobs.py:162` | production path 依赖当前工作目录 |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/job_center/handlers/site_jobs.py:190` | production path 依赖当前工作目录 |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/site_storage.py:1572` | production path 依赖当前工作目录 |
| `RUNTIME_PATH_CWD` | `src/netconsole/services/site_storage.py:3100` | production path 依赖当前工作目录 |
| `UNREGISTERED_STORAGE` | `src/netconsole/services/job_center/handlers/site_jobs.py:145` | `devices.db` 没有 storage registry 声明 |

### 3.3 Ruff 精确发现

| Rule | 文件与行 | 发现 |
| --- | --- | --- |
| `F401` | `src/netconsole/backend/api/main.py:65` | `AgentRepository` 未使用 |
| `F401` | `src/netconsole/backend/api/main.py:66` | `TrafficRunRepository` 未使用 |
| `F821` | `src/netconsole/services/database_upgrade/management_service.py:92` | `exc` 未定义，可能是真实缺陷 |
| `F841` | `src/netconsole/services/database_upgrade/management_service.py:307` | `exc` 赋值后未使用 |

上述 4 条只作为 debt 记录。若后续单独做 hygiene commit，必须逐条先验证导入副作用和异常语义，不能为了让 Gate 变绿而批量删除或改写。

### 3.4 产品决策阻塞项

`tests/test_version_build_identity.py::test_update_policy_ignores_build_and_hash_changes` 对同 ProductVersion、不同 build/hash 是否允许更新存在产品语义冲突。本轮固定标记：

`UPDATE_POLICY_BASELINE_CONFLICT=BLOCKED_PRODUCT_DECISION`

不改变 `src/netconsole/core/version.py`、build metadata、`published` 或 update policy 实现，不修改该测试期望；需要产品负责人明确“同 ProductVersion 是否允许 update”后另开变更。

## 4. 行为冻结清单

Phase 0 和 Phase 1 的唯一目标是记录/守护既有行为。除非变更说明明确授权并通过对应 owner 的定向测试，下列行为均视为冻结：

| 领域 | 冻结边界 |
| --- | --- |
| 设备管理 | 稳定设备身份、参与当前调试范围、排序、筛选、分页和编辑语义不变。 |
| 设备详情 | 设备详情字段、秘密字段保护、连接状态和错误码契约不变。 |
| 设备连接/采集 | 连接、版本化 inventory profile、采集任务终态、取消/重试和事实落库边界不变。 |
| 设备导入/导出 | CSV/Excel/template 的空值、`__CLEAR__`、冲突、幂等和用户取消落盘语义不变。 |
| 设备文件/终端 | SSH/SFTP 能力边界、host-key fallback、`.part` 和用户选择路径契约不变。 |
| AC 管理 | 多 AC 作用域、确认审计、FIT-AP 所属关系、Current/Recent10 语义不变。 |
| FIT-AP | snapshot 必须完整才可成功替换；部分失败保留旧 Current；`NOT_COLLECTED` 和终态 payload 一致。 |
| 轨旁 AP | 稳定 `station_id` 关联、规划/上线统计、未关联提示、快照 revision 和导出边界不变。 |
| 轨旁 Optical/LLDP | 现有独立 Trackside adapter/profile、站点身份匹配和冲突 fail-closed 语义不变；Phase 2 暂不改动。 |
| 轨道交通基础资料 | 总览、站点与区间、轨旁 AP、规划、列车与车载 MR 的独立解锁、保存、放弃和只读边界不变。 |
| 列车在线 | 正线资格、AP 位置、Ping 和深采 Runtime Decision 不变。 |
| 车载 MR | CT/CW 合并、VRRP/资格、实时采集、Ping/iPerf、原始日志和会话归档边界不变。 |
| MESH | 导入、解析、主备链、切换、Identity projection、详情缓存失效和报告契约不变。 |
| Ground 无人值守 | 调度、资格、fping、Syslog、深采、归档/恢复以及取消/终态语义不变。 |
| 配置采集 | 快照选择、双文件 Diff、裁剪、导出和 artifact 生命周期不变。 |
| Task Center/Runtime | 七状态、JSONL 事件、任务 owner、协作取消、Artifact 和页面关闭语义不变。 |
| 存储/历史 | Legacy HistoryStore 不重新进入 runtime；Current + Recent10 + 既有 bounded history 语义不变。 |
| Site/DataRoot | PathResolver、站点切换、空壳站点、生产写保护、数据库治理和隔离测试根边界不变。 |
| Settings/Feature Registry | Feature ID、状态、Full/Customer policy、默认关闭项和只读版本状态不变。 |
| WPS/文件同步 | WPS 云/API/KDocs 不扩大进入 NetConsole；本地 `.xlsx` 格式和用户文件交互边界不变。 |
| Electron | Main/Preload/IPC、Backend 生命周期、动态端口/token、托盘、标签和退出语义不变。 |
| 发布身份 | ProductVersion、build number、commit/hash、`published` 和 update policy 不在本轮改变；普通打包不递增版本。 |

## 5. 工程加固的 CI 规则

- Blocking Green Gates：Renderer Vitest/`vue-tsc`/build、Electron tests/typecheck/main build、可独立通过的 architecture guards、main contract、docs/path 和 diff check。
- Python regression 允许只排除上面 4 个精确 baseline node ID；禁止 `-k` 模糊匹配、目录级忽略和全局 `continue-on-error`。
- Baseline Debt Audit 必须使用机器可读清单，逐条比较 architecture findings、Ruff findings 和 Python baseline node ID：旧问题继续存在则报告 debt，旧问题消失则报告可收缩项，新发现直接失败。
- CI 不运行 PyInstaller、NSIS、157 MB 安装包、真实设备、Production/Development Real Data、WPS 云服务或需要秘密的验收。
- `BASELINE_DEBT_COUNT` 的初始逻辑条目数为 `15`：4 个 Python node、7 个 Architecture finding、4 个 Ruff finding；跨套件同源问题不合并计数，避免债务静默消失。

## 6. 后续边界

Phase 2 仍为 `BLOCKED_BY_TRACKSIDE_OPTICAL=YES`。在轨旁 optical dirty worktree 完成独立测试、commit、push、合入并回到最新 `github/main` 后，才重新生成影响矩阵并决定是否迁移 Trackside/FIT-AP/设备 inventory 的命令 Profile。

Phase 4 的 `legacy_tasks.py` 收敛、Phase 5 的 release/package/update 决策本轮只记录，不在本基线文档提交中实现。真实 GUI、安装/升级/卸载、跨机、现场设备、生产数据和 WPS 人工验收均保持 `PENDING`，不被自动化 Gate 的 PASS 替代。
