# 测试基线

NetConsole 开发默认先跑与改动直接相关的定向测试，所有待合并提交完成并完成代码审阅后，再运行全量测试。这样可以更快定位模块问题，同时保留最终集成回归门槛。

## 数据隔离

- pytest 在收集测试模块前创建独立的临时 `NETCONSOLE_DATA_ROOT`。
- 测试不得读取或写入开发态 `.local/data`、正式局点数据库、真实会话和报告。
- 需要特定数据布局时使用 `tmp_path`、测试 fixture 或 Fake 服务；不得依赖当前机器已有 Task、Session 或设备数量。
- 独立工作树的虚拟环境若未执行 editable 安装，运行会启动 Python 子进程的测试时应显式设置 `PYTHONPATH=src`；不能把 `ModuleNotFoundError: netconsole` 误判为 Worker 业务失败。

## 开发阶段

每个模块至少运行：

1. 新增或修改的后端 Service、Repository、Router 测试。
2. 直接受影响的既有 Qt 或 Application Service 测试。
3. 对应 Vue 组件、API client 或 Store 的 Vitest。
4. 前端 `npm run build`，以及适用的 Ruff、Go 或文档链接检查。

Electron 改动还需在 `apps/desktop_electron` 运行 `pnpm test`、`pnpm run typecheck` 和 `pnpm run build:main`；触及启动链、preload 或 Vue runtime adapter 时运行 `pnpm smoke:dev`。该冒烟覆盖源码图形环境，不替代 Windows 安装包、签名、升级或目标系统实机验收。

测试断言应验证必要能力和业务契约，不硬编码会随正常扩展变化的全局任务总数或路由总数。

## 合并前

所有并行分支进入同一集成分支后运行：

1. 完整 pytest。
2. 完整前端测试与构建。
3. Ruff 与文档链接检查。
4. Agent 代码受影响时运行 Go 测试和对应构建检查。

全量测试只在合并后的真实代码组合上作为最终门槛；单个并行任务不重复执行全量套件。
