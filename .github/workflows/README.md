# GitHub Actions 工作流

## 用途与边界

本目录存放持续集成工作流。快速门禁先按 Change Impact Matrix 输出风险等级和消费者，再执行 PR 的常规反馈；全量 Python 回归用于发现快速组合未覆盖的跨模块失败。工作流只安装锁定依赖、执行既有入口并报告结果，不修改仓库或业务数据。

## 主要入口

- `quality-gate.yml`：PR 与 `main` 推送触发的 Change Impact Audit、Python 核心、Renderer、Electron 检查及稳定聚合状态。
- `python-full-regression.yml`：PR、`workflow_dispatch`、每日定时和 `main` 推送触发的完整 `pytest -q` 阻断门禁。

`main` 推送会重新运行两个 workflow，不复用 PR 结果。`Regression gate complete` 聚合影响审计和三个消费者门；`Python full regression` 保持独立，以便 Branch protection / Ruleset 同时要求快速集成门和完整 Python 门。合并后的任一失败表示当前 `main` 基线不可发布，必须通过后续最小修复恢复，workflow 本身不能回滚提交。

## 禁止事项

- 不设置 `continue-on-error`，不删除失败测试或把失败转成非阻断提示。
- 不在 CI 中连接真实设备、读取机器级 NetConsole 数据根或提交生成物。
- 修改命令、架构或数据契约时，先修改正式源码/配置与测试，再更新工作流。

## 测试与修改

工作流变更后本地至少运行相同的命令和 `git diff --check`。Python 全量任务在仓库内临时 `.venv` 中按约束文件安装依赖，隔离 Runner 预装包，并保留完整失败节点输出。
