# PR #90 诊断脚本数据根误写事件与安全收口

日期：2026-10-18
范围：PR #90 最终 GUI 验收使用的隔离诊断脚本；不改变 PR #90 列车在线业务代码。

## 结论摘要

事故入口是 Workspace 外部的一次性验收脚本，不是 Electron、Backend、ApplicationService 或正常数据库维护入口。脚本把 `PathResolver` 的第一个位置参数误当成 `data_root`，实际只设置了 `app_root`，随后由 `PathResolver` 的默认分支解析到持久数据根。`VehicleMrOnlineStore` 初始化时先创建数据库父目录，再打开 SQLite，因而在正式根下产生了合成测试数据库。

已有验收证据确认：新增目标是单独的 `sites/demo` 树，包含一份 `vehicle_mr_online.sqlite`；未发现对应 WAL/SHM；随后只针对该新建目标执行了精确删除，并复核目标不存在。本报告不把这些证据扩大为“整个正式根已完成独立完整性证明”。

## 事件经过

1. `seed_vehicle_mr_scenario.py` 位于 Workspace 外部的 PR #90 GUI 诊断报告目录，仅用于构造隔离列车在线 Fixture。
2. 早期版本调用 `PathResolver(ROOT)`，而不是 `PathResolver(data_root=ROOT)`。
3. `PathResolver` 定义顺序为 `app_root, data_root`；因此 `ROOT` 被写入 `app_root`，`data_root` 保持默认持久根解析。
4. 后续 `VehicleMrOnlineStore(PathResolver(...), "demo")` 构造并初始化数据库。
5. 发现路径不符合预期后停止该路径，精确核验并删除仅由本次脚本创建的 `sites/demo`。
6. 当前安全修复从最新 `github/main` 独立建立，不修改 PR #90 分支，也不再次运行错误脚本。

## 精确调用链

```text
seed_vehicle_mr_scenario.py
  -> ROOT = Path(sys.argv[1]).resolve()
  -> PathResolver(ROOT)                 # 误用：ROOT 进入 app_root
  -> PathResolver.__post_init__         # data_root=None，走默认持久根
  -> VehicleMrOnlineStore(..., "demo")
  -> VehicleMrOnlineStore.initialize()
  -> VehicleMrOnlineStore.connect()
  -> db_path.parent.mkdir(parents=True, exist_ok=True)
  -> sqlite3.connect(db_path)
```

当前正确调用应使用诊断专用安全构造入口：

```python
from netconsole.tools.diagnostic_data_root_guard import (
    create_diagnostic_path_resolver,
)

paths = create_diagnostic_path_resolver(
    data_root=test_root,
    repository_root=repository_root,
    runtime_mode=RuntimeMode.TEST,
)
```

该入口先调用 `require_diagnostic_test_root()`，再只用关键字构造
`PathResolver(data_root=validated_root)`，最后比较
`validated_root == paths.data_root`。不一致统一抛出
`DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED`，因此不会进入 Store、Repository、目录创建或 SQLite 连接。

## 影响范围与证据等级

| 项目 | 结论 | 证据 |
| --- | --- | --- |
| 误写目录 | `sites/demo` 相对正式根 | `CONFIRMED`（既有验收报告和目录检查） |
| SQLite 文件 | `sites/demo/files/rail_transit/online_mr/parsed/vehicle_mr_online.sqlite` | `CONFIRMED`（既有验收报告） |
| WAL/SHM | 未发现 | `CONFIRMED`（既有目录检查） |
| SQLite 表/索引初始化 | `VehicleMrOnlineStore.initialize()` 执行 `CREATE TABLE/INDEX` | `INFERRED_FROM_CODE`；不能替代数据库页级审计 |
| Site Registry 更新 | 该脚本调用链中未发现 Registry writer | `INFERRED_FROM_CODE` |
| 全局任务状态变化 | 该脚本调用链中未发现 Task writer 或 Worker | `INFERRED_FROM_CODE` |
| 其他正式根文件 | 既有精确目录检查未发现 | `CONFIRMED`（检查范围仅为本次新增目标） |
| 删除范围 | 只针对新建的 `sites/demo` | `CONFIRMED`（已有路径校验与删除记录） |
| 删除后目标 | `sites/demo` 不存在 | `CONFIRMED`（已有删除后存在性复核） |
| 正式根整体未受任何影响 | 不能由现有证据推出 | `NOT_VERIFIED` |

### 证据缺口

现有记录不能证明正式根在事件前后的所有文件、SQLite 页、WAL/SHM 或外部系统日志完全一致；本轮不扩大正式根扫描范围，也不打开正式业务 SQLite。若后续需要提高证明强度，应由用户单独授权对限定时间窗口的应用日志、文件系统审计记录和指定路径清单执行只读核验，不能用全根破坏性或重建操作替代。

## 防复发保护

新增：`src/netconsole/tools/diagnostic_data_root_guard.py`

`scripts/maintenance/diagnostic_data_root_guard.py` 仅保留兼容转发。这样工作区外按文件路径启动的一次性诊断脚本可以从已安装的 `netconsole` 包导入守卫，不依赖诊断脚本目录或仓库根恰好位于 `sys.path`。

Guard 不能自动拦截完全绕过它的任意 Python 代码；因此事故脚本
`seed_vehicle_mr_scenario.py` 已实际改为调用
`create_diagnostic_path_resolver()`，而不是只在旁边调用 Guard 后再自行构造
`PathResolver`。未来工作区外诊断必须使用该入口或等价的受控仓库内启动器。

`require_diagnostic_test_root()` 在任何 Repository、目录创建或 SQLite 连接前执行以下 fail-closed 校验：

- `data_root`、`repository_root`、`runtime_mode` 必须显式提供；运行模式必须是 `TEST`。
- 测试根必须是 `<repository-parent>/test-data/NetConsole/<run-id>` 的单层 run directory。
- 缺失、空值、相对路径、路径穿越、正式根/正式根子目录/正式根父目录和大小写/分隔符变体均拒绝。
- 解析并拒绝已有 Symlink/Junction/Reparse Point 路径，避免链接越界。
- `NETCONSOLE_ALLOW_PRODUCTION_WRITE=1` 不得绕过诊断保护。
- `repository_root` 必须是存在的 NetConsole checkout，包含 canonical project markers，且 `git -C <root> rev-parse --show-toplevel` 必须返回该根；伪造或误识别目录在计算 TEST base 前拒绝。
- 无法确定机器正式根时拒绝继续，而不是猜测或回退。
- 统一错误码为 `DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED`。

该模块不被普通 Electron、ApplicationService、DatabaseUpgradeCoordinator、共享 MESH Authority 或业务维护 API 导入；PR #89 的正常 GUI 生产维护授权、确认、锁和事务边界未改变。

## 负面测试

新增 `tests/test_diagnostic_data_root_guard.py`，共 `27 passed`，覆盖：

- 缺失/空/相对 root、非法 Runtime；
- 正式根、正式根子目录、正式根父目录、测试根本身；
- `..`、大小写和分隔符变体；
- Symlink 指向正式根；
- 生产写入授权环境变量仍被拒绝；
- 被拒绝时 `mkdir` 与 `sqlite3.connect` 均未调用；
- 误识别/伪造 `repository_root` 在计算 TEST base 前被拒绝；
- 正常 TEST run root 及 SQLite 初始化通过；
- 原始 `PathResolver(ROOT)` 位置参数错误在 Store 前被识别为 root mismatch；
- 正确关键字构造后的 `VehicleMrOnlineStore` 只在 TEST 根初始化；
- 工作区外按文件路径启动的脚本可从源码包导入 guard 并完成校验；
- 通过临时源码副本构建 Wheel、隔离 Python 环境安装后，工作区外脚本可导入 guard 和安全 PathResolver 工厂，并分别通过 TEST 根与模拟生产根拒绝测试；共享 checkout 不产生或清理 Wheel build 目录。

受影响正常运行代码未改动；Data Environment、Desktop runtime 和 PR #89 维护授权回归需在安全 PR CI 中继续验证。

## PR #90 GUI 交接

既有隔离 Electron 截图和 API 证据继续有效；本轮不重新生成 Fixture，不写正式数据。用户手动检查页面：`轨道交通 → 列车在线情况`。

| 场景 | 预期 |
| --- | --- |
| G01 同 AP 连续刷新 | AP-A 保持车站A |
| G02 AP 切换 | AP-B 显示 `—`，不恢复车站A |
| G03 新 AP 获得站点 | 更新为车站B |
| G04 CT/TC 独立 | AP、站点、RSSI 不跨端填充 |
| G05 显式未知 | 不直接使用历史站点 |
| G06 RSSI | 仅显示数值，不追加 `dBm` |
| G07 页面交互 | 查询、轮询、详情开关、离开/返回、站点筛选和数据一致性正常 |

自动截图/模拟交互可标记 `GUI_AUTOMATED_ACCEPTANCE=PASS`；用户亲自确认前，`GUI_MANUAL_ACCEPTANCE` 必须保持 `PENDING`。

## 剩余风险与建议

- 事故的业务副作用目前没有证据支持，但正式根整体未完成独立文件/SQLite 完整性证明，保留 `NOT_VERIFIED`。
- Workspace 外部临时脚本不属于安全 PR 的长期代码；后续任何类似诊断必须先调用新的 guard，不能只依赖字符串包含 `test-data` 的检查。
- 安全 PR 不应与 PR #90 合并；PR #90 继续等待用户手动 GUI 验收。
- 在安全 PR 的 CI/Review 通过并完成人工复核前，不建议解除数据根安全审查待办。
