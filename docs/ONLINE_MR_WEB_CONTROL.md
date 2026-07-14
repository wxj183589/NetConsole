# Web 本地 Online MR 受控启停

## 当前能力

阶段 5C-10A 在 `/rail-transit/train-communication` 的 MR 详情中增加 LOCAL Online MR 受控入口。它只把严格业务 DTO 转换为既有 `OnlineMrApplicationService` 调用，不创建第二套采集器、Worker、Traffic 协调器、Session Repository 或打包逻辑。

当前只提供：

- `POST /api/rail-transit/online-mr-control/start`；
- `POST /api/rail-transit/online-mr-control/{operation_id}/stop`；
- `GET /api/rail-transit/online-mr-control/status`；
- `GET /api/rail-transit/online-mr-control/{operation_id}`。

没有 force-stop、retry、Agent start/stop、command、delete、配置更新或路径访问路由。强制停止继续只使用已验收的 Qt/Service 安全入口，`executor=AGENT` 仍未开放。

## 四重安全条件

启动和正常停止必须同时满足：

1. 环境变量 `ONLINE_MR_WEB_CONTROL_ENABLED=1`；默认值为 `0`，普通生产配置保持关闭；
2. FastAPI 运行于 `RuntimeMode.DESKTOP`，请求 URL 主机严格为 `127.0.0.1`；
3. 请求已通过当前主程序启动时生成的短期 WebHost Cookie；
4. 请求局点等于主程序当前局点，执行端固定为 `LOCAL`。

Server 模式、`localhost` 别名、无 Cookie、跨局点和非 LOCAL 请求均拒绝。WebHost 仍只绑定随机 `127.0.0.1` 端口；临时令牌不进入 URL、任务、数据库或业务日志。

## 请求白名单

启动 DTO 只接受正式 MR 标识、设备标识、采集时长、采集项、间隔、Radio、fping 和 iPerf Client 参数。所有 DTO 使用 `extra=forbid`；`username`、`password`、`token`、`command(s)`、`agent_url`、数据库路径和输出路径等未知字段返回 422。

后端从当前局点正式基础资料解析 MR，再从 `DeviceRepository` 读取受控连接地址和凭据，补齐正式设备/MR 名称、`owner=web_local` 和 `executor=LOCAL`。响应只返回 Task/Session/Mapping 状态、采集器状态和相对 package reference，不返回凭据或服务端绝对路径。

单个 Online MR operation 沿用现有 `FpingConfig`，因此每台 MR 绑定一个 fping 目标。需要同时观察 CT/TC 时分别选择两台正式 MR；不为 Web 扩充第二套多目标 Traffic 契约。

## 生命周期与幂等

启动调用 `OnlineMrApplicationService.start_local_collection()`；正常停止只调用 `OnlineMrApplicationService.stop_operation()`。停止顺序保持：

```text
Traffic 停止与 flush
→ SSH collector/writer 关闭
→ metadata
→ 原子打包
→ Task / Session / Mapping 终态
```

同一局点、同一设备已有活动 Mapping 时，重复启动返回既有 operation；这也覆盖 Legacy Qt 已启动的会话。重复停止由 ApplicationService 终态判断幂等，不重复生成 ZIP 或改写终态。页面卸载、切换路由或隐藏只停止前端轮询，不停止后台采集。

前端状态映射为 `preparing / starting / running / stopping / stopped / completed_with_warnings / failed / aborted`。活动 operation 每 1.5 秒刷新，非活动状态每 5 秒刷新；停止中明确提示正在等待 Traffic flush 与原子打包。

## 验证边界

自动测试使用 fake ApplicationService/ProcessAdapter，不连接真实 MR。代码完成后只允许定向测试和前端生产构建，不以 fake 结果替代现场验收。

真实设备验收属于独立阶段 5C-10A-A，必须取得明确授权后才可开启安全开关并连接设备。验收前不得推送本阶段本地提交。
