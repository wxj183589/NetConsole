# Web 本地 Online MR 受控启停

## 当前能力

阶段 5C-10A 在轨交 Electron 页面中增加 LOCAL Online MR 受控入口。它只把严格业务 DTO 转换为既有 `OnlineMrApplicationService` 调用，不创建第二套采集器、Worker、Traffic 协调器、Session Repository 或打包逻辑。

当前只提供：

- `POST /api/rail-transit/online-mr-control/start`；
- `POST /api/rail-transit/online-mr-control/{operation_id}/stop`；
- `POST /api/rail-transit/online-mr-control/{operation_id}/force-stop`；
- `POST /api/rail-transit/online-mr-control/recover`；
- `GET /api/rail-transit/online-mr-control/status`；
- `GET /api/rail-transit/online-mr-control/{operation_id}`。

LOCAL 强停调用既有 Service 安全入口，恢复调用既有 Mapping reconcile/recover；没有 retry、Agent force-stop、command、delete、配置更新或路径访问路由。AGENT 执行器使用独立受控契约，本 LOCAL 控制 DTO 不暴露 Agent Profile、Token、URL 或远端命令。

## 四重安全条件

启动、停止、强停和恢复必须同时满足：

1. `create_app()` 的 `online_mr_web_control_enabled` 显式为真；正式 Electron Runtime 固定显式启用，其他宿主未传参时才读取默认关闭的 `ONLINE_MR_WEB_CONTROL_ENABLED`；
2. FastAPI 运行于 `RuntimeMode.DESKTOP`，请求 URL 主机严格为 `127.0.0.1`；
3. 请求已通过当前主程序启动时生成的短期 WebHost Cookie；
4. 请求局点等于主程序当前局点，执行端固定为 `LOCAL`。

Server 模式、`localhost` 别名、无 Cookie、跨局点和非 LOCAL 请求均拒绝。WebHost 仍只绑定随机 `127.0.0.1` 端口；临时令牌不进入 URL、任务、数据库或业务日志。

## 请求白名单

启动 DTO 只接受正式 MR 标识、设备标识、采集时长、采集项、间隔、Radio、fping 和 iPerf Client 参数。所有 DTO 使用 `extra=forbid`；`username`、`password`、`token`、`command(s)`、`agent_url`、数据库路径和输出路径等未知字段返回 422。

后端从当前局点正式基础资料解析 MR，再从 `DeviceRepository` 读取受控连接地址和凭据，补齐正式设备/MR 名称、`owner=web_local` 和 `executor=LOCAL`。响应只返回 Task/Session/Mapping 状态、采集器状态和相对 package reference，不返回凭据或服务端绝对路径。

单个 Online MR operation 沿用现有 `FpingConfig`，因此每台 MR 绑定一个 fping 目标。需要同时观察 CT/TC 时分别选择两台正式 MR；不为 Web 扩充第二套多目标 Traffic 契约。

## 生命周期与幂等

启动调用 `OnlineMrApplicationService.start_local_collection()`；正常停止调用 `stop_operation()`；强停调用 `force_stop_operation()`；重启恢复调用 `recover_mappings()`。正常停止顺序保持：

```text
Traffic 停止与 flush
→ SSH collector/writer 关闭
→ metadata
→ 原子打包
→ Task / Session / Mapping 终态
```

同一局点、同一设备已有活动 Mapping 时，重复启动返回既有 operation；这也覆盖应用重启后恢复的活动会话。重复停止由 Application Service 终态判断幂等，不重复生成 ZIP 或改写终态。页面卸载、切换路由或隐藏只停止前端轮询，不停止后台采集。

强停先走既有有界协作停止，再由 Application Service 决定是否强制终止。无法确认 writer flush 或文件稳定时保留 raw，返回 `data_integrity=partial`，不伪造正常完成或正式完整 ZIP。恢复只核对持久 Mapping/Task/Session，不删除 raw，不从前端路径重建会话。

前端状态映射为 `preparing / starting / running / stopping / stopped / completed_with_warnings / failed / aborted`。活动 operation 每 1.5 秒刷新，非活动状态每 5 秒刷新；停止中明确提示正在等待 Traffic flush 与原子打包。

## 验证边界

自动测试使用隔离的 ApplicationService/ProcessAdapter 契约替身，不连接真实 MR。代码完成后只允许定向测试和前端生产构建，不以替身结果替代现场验收。

真实设备验收属于独立阶段 5C-10A-A，必须取得明确授权后才可开启安全开关并连接设备。验收前不得推送本阶段本地提交。
