# 网络工具服务

本目录实现本地 Ping/fping、iPerf、路由、无线扫描和工具箱的 Application/执行适配。参数校验、阈值、进程和结果存储由服务边界管理，不由 Vue 直接执行。

主要入口为 `application_service.py`、`iperf_*`、`wireless_scan_service.py` 和 `job_handlers.py`；Traffic 专用编排在相邻 `traffic/`。修改工具语义时运行网络工具、编码和 Job 测试。

## 用途与边界

本目录实现本地 Ping/fping、iPerf、路由、无线扫描和工具箱的 Service/执行适配；参数、工具进程和结果由受控服务管理，Vue 不直接执行。

## 主要入口

`application_service.py` 编排网络工具，`iperf_*`/`fping_*` 负责执行与解析，`wireless_scan_service.py` 和 `job_handlers.py` 连接扫描/任务；Traffic 有独立子域。

## 依赖关系

服务依赖 `resources/tools`、Tool Path Resolver、Network Repository/Job Center 和 Windows 编码适配；Agent 远端流量由 Traffic/Agent Service 管理。

## 数据与状态

原始工具输出、解析结果、扫描数据库和 Traffic run 位于局点文件/数据库目录；目标凭据不写输出，进程状态通过 Job/Traffic 事件传递。

## 测试与修改

修改参数、阈值、解析、工具路径或扫描字段时运行 Network Tools、Traffic、编码、Job 和工具 Guard 测试，保持 fping/iPerf 语义一致。

## 生成与清理

工具进程输出进入受控 raw/parsed/outputs 目录，临时进程和缓存按 Job/PathResolver 清理；不删除用户正式报告或原始采集。

## 相关文档

参见 [统一流量测试](../../../../docs/TRAFFIC_TEST_ARCHITECTURE.md)、[Agent 流量协议](../../../../docs/AGENT_TRAFFIC_API.md) 和 [网络工具 Skill](../../../../.agents/skills/traffic-test-skill/SKILL.md)。
