# Task Lifecycle 收口记录

完成时间：2026-09-12  
代码冻结基线：`bd6ac6bad1118949b1f30060587f0e9ae42565df`  
代码状态：`READY_FOR_RELEASE`

## 功能范围

- 当前任务与近期任务中心
- Task authority index 修复及跨局点任务归属
- `site_import` 切换局点后的任务稳定访问
- 任务详情和终态展示稳定性
- 从列表移除任务
- Operational Cleanup
- Tombstone Contract
- `JobCenterCleanupResultDTO` contract
- logs、artifacts、Online MR、Ground 与业务数据保护

## 本轮解决的问题

1. 修复切换局点后任务仍在原始任务库、但查询路径跟随新局点而误报 404 的问题。
2. 修复 Renderer 在任务已经进入终态后仍持续轮询的问题。
3. 统一 cleanup DTO 的字段 contract，并保持后端 strict extra 校验与 Renderer 类型一致。
4. 建立普通任务的 Operational Cleanup 边界，清理任务运行记录和临时结果，保留日志、Artifact 与业务数据，降低 tasks.db 长期增长风险。
5. 通过 tombstone 记录受控清理事实，并保护 Online MR、Ground、Artifact 和其它业务数据不被日常任务移除操作影响。

## 验证结果

- Python：`4833 passed, 2 skipped`
- Renderer：`1300 passed`
- Electron：`298 passed`
- Architecture：`12/12 PASS`
- Full Gate：`PASS`
- `NEW_FAILURES=0`

上述验证绑定代码冻结基线 `bd6ac6ba`；后续仅增加本发布日志，不包含产品代码改动。

## 明确边界

### 已完成

Task Lifecycle 产品能力，包括任务归属、查询、详情、终态展示、列表移除、Operational Cleanup、Tombstone Contract 和数据隔离保护。

### 未包含

- Production GC 执行
- Production tasks.db 批量清理
- rollback execution
- maintenance authorization
- Production evidence、preview 或 apply manifest

Production maintenance 仍属于独立运维执行链，不是普通用户 Task Center 操作的前置条件。

## 最终状态

`READY_FOR_RELEASE`

Task Lifecycle 产品代码已完成冻结和 main 合入准备；真实安装包、设备、跨机器和现场 GUI 验收按独立发布流程执行，不由本日志替代。
