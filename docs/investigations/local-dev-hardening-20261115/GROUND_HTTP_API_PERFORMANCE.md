# Ground HTTP API 本地性能与错误回归

状态：`PASS`（本地 ASGI/HTTP 合同）；现场设备验证：`FIELD_VALIDATION_PENDING`。

证据：`D:\study\NetConsole-Workspace\diagnostic\local-dev-hardening-20261115\http-api-performance.json`。测试使用真实 `create_app`、FastAPI TestClient 和隔离 Site，没有设备连接。

## 路由结果

Heartbeat 列表、MR 监测、Quick Ping 列表、Quick Ping 历史、Syslog records、Job Center summary/tasks、Mesh-Link、AP 分页、ARP 状态均为 HTTP 200；Quick Ping 创建为 202；缺失任务取消为预期 404。每个 GET 采集 3 个样本，记录 P50/P95/P99、响应大小和失败率；脚本观察到的 SQLite locked 次数为 0。

Quick Ping 持久化内部 `_stats_accumulators` 不再泄漏到公开 DTO，异常历史记录不会使 `GET /api/rail-transit/ground-unattended/quick-ping` 返回 500。

Syslog 专项使用配置了外部测试地址的隔离 profile：创建返回 202，Job Center 查询返回 200，取消返回 200/CANCELLED。根因修复是共享任务中心只接受 `PENDING/STARTING/RUNNING/STOPPING`，而原代码把设备调度层的 `QUEUED` 错写进共享状态事件；现在保留 `stage=QUEUED` 展示语义，但任务状态写入合法的 `PENDING`。

未宣称真实设备 Syslog 配置成功；Fake/isolated route 只证明状态持久化、取消和错误边界。
