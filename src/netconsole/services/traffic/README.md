# Traffic 流量测试服务

本目录提供本地/Agent 流量测试 Application Service、执行适配器、Supervisor、事件 Hub/Store 和 Web 映射。它负责统一 TCP/UDP、fping/iPerf 任务语义，不由 Router 或 Vue 直接启动进程。

主要入口为 `application_service.py`、`local_adapter.py`、`agent_supervisor.py` 和 `web_application_service.py`。修改阈值、事件、取消/重试或恢复时运行 Traffic API、Agent、Repository 和 Web 测试。

## 用途与边界

本目录统一本地/Agent 的 TCP/UDP、fping/iPerf 流量测试应用、执行适配、Supervisor、事件和 Web 映射；Router/Vue 不直接启动进程。

## 主要入口

`application_service.py` 编排用例，`local_adapter.py` 执行本地任务，`agent_adapter.py`/`agent_supervisor.py` 连接 Go Agent，`web_application_service.py` 提供 Web 查询映射。

## 依赖关系

Traffic 依赖 Job Center、Agent Controller、Network Tools、Traffic Repository 和 PathResolver，由 FastAPI/Online MR/Application 调用。

## 数据与状态

运行目录保存 events/summary/remote result，Repository 保存可查询的 run 状态；进度、取消、重试和能力事件通过统一事件 Hub/Store 传递。

## 测试与修改

修改参数、阈值、TCP/UDP 语义、事件、取消/重试或恢复时运行 Traffic API、Application、Adapter、Supervisor、Repository、Agent 和 Web 测试。

## 生成与清理

执行过程进入 Job/traffic runs 受控目录，远端 Agent 包按截止时间和 normal stop 收敛；临时会话清理不得删除正式结果或凭据。

## 相关文档

参见 [统一流量测试架构](../../../../docs/TRAFFIC_TEST_ARCHITECTURE.md)、[Agent 流量协议](../../../../docs/AGENT_TRAFFIC_API.md) 和 [Traffic Skill](../../../../.agents/skills/traffic-test-skill/SKILL.md)。
