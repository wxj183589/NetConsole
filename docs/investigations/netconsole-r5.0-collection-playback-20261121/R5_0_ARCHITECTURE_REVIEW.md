# R5.0 架构复审

## 范围与基线

- 产品基线：`6dc938c7`，独立 Worktree 与分支 `codex/netconsole-r5.0-collection-playback-20261121`。
- 只维护原版 NetConsole；不修改版本、Electron 进程模型、构建和发布配置。
- Change Impact 工具判定 `L2`：变更限定在 Ground Unattended Application/Repository/API/Renderer 领域，没有修改共享图表基础层。
- 并行 Worktree 审计未发现目标文件重叠；主仓库原有未跟踪调查目录保持未触碰。

## 决策

一个 Electron 与一个 Backend 保持不变，页面内提供“实时采集 / 历史回放”两个工作区。实时采集继续使用原上下文和生命周期；历史回放拥有独立选择、请求取消、generation、时间窗和图表状态，仅调用 GET 查询接口。

MESH 历史索引读取使用 SQLite URI `mode=ro&immutable=1` 与 `PRAGMA query_only=ON`。若 WAL 非零则返回 `GROUND_PLAYBACK_WAL_UNSTABLE`，不以可能遗漏 WAL 的 immutable 视图继续回放。历史回放没有启动 Heartbeat、Quick Ping、Syslog、AC 或 Mesh-Link 的调用，也没有写接口。

## 边界

- 未拆分 Backend/Electron 进程。
- 未改采集调度器、默认启停策略或 Syslog 生命周期。
- 未修改 DataRoot、Migration、Feature Registry、数据库 Schema。
- 真实数据 GUI 启动未执行，原因见 GUI 验收报告。
