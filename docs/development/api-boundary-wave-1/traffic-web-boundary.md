# Traffic Web 应用边界

Phase 0.5 任务 B 将 Traffic Web 的查询、执行端可用性、取消和重试编排收口到
`src/netconsole/services/traffic/web_application_service.py` 的
`TrafficWebApplicationService`。

- Facade 复用 `TrafficTestApplicationService`、`AgentControllerService`、Task 体系和 Traffic Repository，不新增 Traffic 状态机、Agent 协议或执行适配器。
- `traffic_router.py` 只负责请求 DTO、HTTP 错误边界、响应映射，以及 WebSocket 游标、心跳和事件流。
- Facade 的 run 分页先过滤和排序再分页，并返回 `total`、`has_more`；REST 仍保持当前数组响应契约。
- Facade 按 `traffic_run_id` 编排幂等取消和重试；重试继续由正式 Traffic Service 使用白名单配置创建新 Run/Task。

Phase 0.5 任务 E 已在现有 `create_app()` 组合根中创建一次并注入：

```python
app.state.traffic_web_application_service = TrafficWebApplicationService(
    traffic_service,
    agent_service,
)
```

Network Tools 与 Traffic Router 共用 `src/netconsole/backend/api/traffic_presentation.py` 的纯执行目标和 Run DTO 映射，不再依赖 sibling Router 私有函数。该接线不改变 REST 数组响应、WebSocket 事件、Traffic 协议、Online MR 或 Go Agent 契约。
