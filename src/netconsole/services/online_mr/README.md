# Online MR 永久业务层

## 用途

本目录承载 Online MR 的 Application Service、LOCAL/AGENT 执行、Traffic 协调、会话、事件、解析、诊断和查询契约，供 FastAPI 与 Electron Renderer 复用。

## 边界

本目录不得依赖 PySide6、Qt 页面、Electron 或 FastAPI Request/Response。设备命令以 `collection_commands.py` 为当前事实源；后续统一接入版本化 Command Profile 时不得在页面、Router 或普通 Service 新增命令副本。

## 主要入口

- `application_service.py`：Online MR 用例、Task/Session/Mapping 和执行端编排。
- `collection_service.py`：LOCAL SSH 采集生命周期。
- `traffic_coordinator.py`：fping/iPerf 与采集停止、flush、最终化协调。
- `fping_v5_probe.py`：纯 Python fping 执行、统计、事件和会话摘要。
- `query_service.py`：会话、日志、指标和 Artifact 的只读查询。
- `agent_executor.py`：受控 Agent 远程执行和包导入闭环。

## 数据与安全

会话路径由 `collection_paths.py` 和 `PathResolver` 决定；raw、metadata、parsed 和 ZIP 不写仓库。密码、Agent Token、桌面会话 Token、绝对路径和私有请求不得进入公共 DTO、日志、Task 快照或采集包。

## 测试

优先运行 Online MR Application、collection、fping、Traffic、Agent 和 Web control 定向测试。缺少真实 MR、Agent 或 iPerf 服务端时必须标记现场验收待定，Fake/回环结果不能替代真实验收。

## 迁移状态

正式 LOCAL 主路径由 Application Service 持有 Traffic 和 SSH 生命周期。历史 Signal/QThread Adapter 已删除，不得重新建立桌面专属业务层。

## 相关文档

- [Online MR 实时采集](../../../../docs/rail-transit/online-mr/README.md)
- [Online MR Agent](../../../../docs/rail-transit/online-mr/AGENT_EXECUTOR.md)
- [架构一致性审计](../../../../docs/architecture/COMPLIANCE.md)
