# NetConsole Task Lifecycle 功能代码冻结验收报告

日期：2026-09-12  
审计基线：`bd6ac6bad1118949b1f30060587f0e9ae42565df`  
分支：`main`  
代码状态：`READY_FOR_RELEASE`

## 1. 审计结论

Task Lifecycle 的正常业务路径可以冻结。当前代码未发现需要继续修改的业务缺陷，且相对父提交 `46bdadefeb3194d6d11a965390f8334a6c167b7d` 的 Full Gate `NEW_FAILURES=0`。

本次只完成代码质量审计和验收文档生成，没有执行 Production GC、VACUUM、原子替换、rollback owner/source drift 处理、Production evidence 生成或 Production gate 操作。

## 2. 功能范围

本次审计覆盖：

- Task Center、Task API 及任务详情/日志入口
- Task authority index 与跨站点任务路由
- Task cleanup、Operational cleanup、tombstone
- `JobCenterCleanupResultDTO`
- Task owner lifecycle、storage registry 及 maintenance capability 的边界
- Log Center、Artifact、Online MR、Ground 数据隔离

## 3. 代码审计结果

### 3.1 日常 Task Lifecycle 与 Production maintenance 已隔离

- `src/netconsole`、`apps/desktop_renderer`、`apps/desktop_electron` 的正常运行路径没有引用 `ProductionMaintenanceCapability`、rollback owner、Production evidence 或 Production gate。
- Task Center 的“从列表移除”调用普通 Task API / Job Center cleanup service，不要求 rollback owner、evidence bundle、maintenance authorization 或 Production gate。
- 日常任务清理不会触发 Production GC 流程。
- Production maintenance 保持在独立模块和独立执行链中，不污染普通任务生命周期。

### 3.2 清理边界符合产品模型

清理服务在终态任务上执行受控事务，删除任务自有的 `events`、`snapshots`、临时 `results` 及无引用的 task result blob，并写入 retention tombstone。

清理服务明确保留并隔离：

- logs
- artifacts 及其文件
- Online MR 数据
- Ground 数据
- business data

Artifact manifest、Online MR 映射、Ground 引用、结果 authority、持久化引用和确认条件会在执行前后复核；用户不能通过 Task Center 删除业务制品。

### 3.3 Authority index 与 schema 兼容

- authority index 只承担跨站点任务定位，使用原子写入，旧 schema v1 条目仍可读取。
- task cleanup schema 的升级是显式操作；普通读取和日常清理不会隐式执行大规模迁移或启动时批量改写数据库。
- 旧 tasks.db 数据保持可读，未引入强制 migration。

### 3.4 生命周期模型

对外终态保持 `COMPLETED`、`FAILED`、`CANCELLED`；`PENDING`、`RUNNING` 等运行态由现有状态转移规则管理，`STARTING`、`STOPPING` 是内部过渡状态，不改变产品可见的生命周期语义。

终态任务的产品流程为：查看近期任务 → 从列表移除 → Operational cleanup。清理任务运行记录和临时结果，同时保留日志、制品和业务数据，符合产品设计。

### 3.5 GUI Task Center

Renderer 的 Task Center 测试覆盖当前任务、完成任务、列表移除、详情打开和日志入口相关契约；移除提示明确表示只清理任务运行记录并保留日志/文件/导出结果。

GUI 正常路径没有展示或依赖 Production maintenance 信息，也没有 `PRODUCTION_WRITE_CONFIRMATION_REQUIRED` 之类的 Production gate 依赖。

本轮未进行真实安装包/真实设备上的人工 GUI 验收；GUI 结论限定为代码和自动化测试层面的冻结结论。

## 4. 已完成项

- task authority fix
- cleanup contract
- tombstone contract
- DTO contract
- GUI remove
- storage isolation

## 5. 明确不包含

- Production GC
- rollback execution
- maintenance authorization
- Production evidence / preview / apply manifest
- Production tasks.db、HistoryStore、业务数据、日志、Artifact、MESH、Online MR、Ground 或原始文件的运维变更

## 6. 测试结果

| Gate | 结果 |
|---|---|
| Python relevant tests | `246 passed` |
| Python Full | `4833 passed, 2 skipped, 33 warnings` |
| Renderer | `1300 passed`；`vue-tsc`、Vite build 通过 |
| Electron | `298 passed`；typecheck、main build 通过 |
| Architecture | `12/12 PASS` |
| Main contract smoke | `22 passed` |
| Docs path guards | `12 passed` |
| Ruff | PASS |
| Git diff check | PASS |
| Full Gate | `PASS` |
| NEW_FAILURES | `0` |

已知非阻断输出：Python 运行时报告 33 个既有 deprecation warnings；Renderer 测试探针可能输出本地 `:3000` 连接拒绝噪声但最终测试通过；Vite 报告少数 chunk 超过建议大小。这些均未形成新增失败。

## 7. 风险与边界

1. 本报告是代码冻结验收，不是 Production maintenance 执行授权，也不代表 Production tasks.db 已完成 GC。
2. rollback owner/source drift、Production evidence producer、preview/apply manifest 仍属于运维执行链，不纳入本次代码状态判断。
3. 真实 GUI、安装包、设备和跨机器验收仍需按各自发布流程单独执行；本报告不把自动化测试升级为现场验收。

## 8. 最终判断

`CODE_STATUS=READY_FOR_RELEASE`

在本报告限定的 Task Lifecycle 产品代码范围内，Full Gate 通过且没有业务缺陷，代码可以冻结；不需要继续修改产品代码。
