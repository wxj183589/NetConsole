# Online MR Agent Fake 验收

## 结论与冻结项

阶段 5B-13B 已完成 Desktop WebHost 的 AGENT 远程控制入口和回环 Fake Agent 全链路自动验收。列车下电期间，下列现场项继续冻结：

- 5C-10A-B：Web LOCAL 自动到期停止真实设备验收；
- 5B-13A-A：Agent 远程执行真实 MR 验收。

本验收不连接真实 MR、`10.122.*`、生产 Agent 或真实凭据，不修改 Go Agent，也不把 Fake 结果写成现场通过。

## 验收链路

```text
/rail-transit/train-communication
  → 独立 AGENT 页签
  → Desktop + 127.0.0.1 + 短期 Cookie + 环境开关
  → OnlineMrAgentWebControlService
  → OnlineMrApplicationService
  → OnlineMrAgentExecutor
  → 正式 OnlineMrAgentHttpClient
  → 127.0.0.1:随机端口 Fake Agent
  → 正式 DownloadService / PackageImporter
  → Task / Session / Mapping
  → Web 最终状态
```

Fake Agent 位于 `tests/support/fake_online_mr_agent.py`，只监听 `127.0.0.1:0`，使用固定测试 Token、pytest 临时目录和正式 Agent 路由。它不模拟 SSH，不读取生产 Profile，不访问外部网络；采集包按正式 required-files 契约即时生成。

## 覆盖矩阵

| 场景 | 验收点 |
| --- | --- |
| capability / profiles / readiness | 默认开关语义、脱敏地址、不返回 Token/路径 |
| start / duplicate / status / normal stop | 固定真实 HTTP 路由、启动幂等、无 force |
| package download / import | 正式流式下载、校验、原子 Session、Task/Mapping 终态 |
| duration | 注入 Controller 时钟，到期后无浏览器也发送正常停止 |
| restart | 从持久 Mapping 查询同一远端 Task，不重复 start |
| transient status | 失败计数累积，恢复后清零，不伪造终态 |
| LOCAL / AGENT mutex | 两个方向都由 Application Service 拒绝并发 |
| invalid / mismatch / conflict | 稳定错误码、保留诊断包、不覆盖 Session |
| Web 安全 | 严格 `127.0.0.1`、短期 Cookie、字段 `extra=forbid` |
| API surface | 只有 GET、start、normal stop；无 delete/force/command/retry |

## 复现命令

使用项目虚拟环境，仅运行定向测试：

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_online_mr_agent_web_fake_acceptance.py
.venv\Scripts\python.exe -m pytest -q tests/test_online_mr_agent_executor.py tests/test_online_mr_agent_http_client.py tests/test_online_mr_web_control_api.py tests/test_online_mr_web_control_service.py
Set-Location apps/web
npm test -- --run src/views/rail-transit/TrainCommunicationView.test.ts
npm run build
```

测试生成的数据库、包、Session 和下载 staging 全部位于 pytest 临时目录。不要把环境开关写进仓库配置，也不要把 Fake URL、Token 或测试输出迁移到生产 Profile。

## 未开放能力

- Agent force stop、远端 package 删除、任意命令、任意 URL、远端路径和多 Agent 编排；
- 生产开关自动开启或持久凭据；
- 自动解析、报告生成或远端包清理；
- 任何真实设备、真实 Agent 或真实凭据验收。
