# Phase 7 设备任务中心

## 交付范围

本轮复用现有 DeviceTaskApplicationService、Job Center、LocalProcessAdapter、WebExportProcessAdapter 和 WebArtifactStore。接口继续保持七种既有任务状态，设备配置写入维持关闭。

- 设备 UUID、分组、局点全部设备、组织节点及下级四类目标，提交时冻结 UUID，最多 64 台。
- 组织目标读取已初始化的组织事实与资产关联，不触发组织初始化或自动推断。
- 串行或 1 至 8 台并发，每台设备内部按命令顺序执行。
- LLDP、诊断、版本、无线信息、MESH 和自定义查询支持单条命令 5 至 120 秒超时。备份与光衰使用原采集器策略。
- 取消复用既有任务停止机制，设备连接前、查询命令前后检查取消，等待完成的 future 使用 200ms 周期检查取消。
- 终态任务才允许失败或部分成功设备重试，历史任务缺少执行设置时沿用旧默认值。已保存模板重试要求使用当前版本重新预览。
- 逐设备结果增加采集耗时。结束任务可导出 XLSX，包含任务、模板版本、设备、状态、时间、耗时与完整脱敏结果。长 JSON 按 30000 字符分段，避免 Excel 单元格截断。
- 增加无线信息收集与 MESH 收集两个实际任务类型。无线采集复用能力表及 AP 列表、地址、射频解析器。MESH 采集复用现有 AC Mesh-Link 命令、格式验证和 V5/V9 解析器，必要时使用既有 V5 命令兼容回退。
- 两个新类型只面向 H3C AC。其他角色明确跳过。解析数据只保存在任务结果，身份、AP Current、MESH Current、关联与历史状态写入继续由原 AC/MESH 服务负责。每台设备保留前 128 条解析记录并报告完整记录数及截断状态。
- 导出固定动作已登记，先选择用户保存位置，再启动独立 Export Worker。Artifact 来源、受管目录、取消、查询与共享保存协调器均已接入。

## 既有模板能力

Jinja2 已覆盖注释、变量、条件、循环、过滤器、StrictUndefined、类型参数验证、沙箱与渲染规模限制。模板库具有局点隔离、版本、复制、启停和预览摘要。保存接口拒绝配置变更类型，检查所有条件分支及循环体的静态命令骨架，要求固定只读命令名称。变量只承担查询参数。实际渲染结果在执行入口再次逐条通过只读白名单。历史配置模板可读取和预览。

## iPerf 复用评估

现有 `TrafficTestApplicationService.start_iperf_client` 接受 `parent_task_id`、`correlation_id`，由本机 Traffic Adapter 执行并注册 controller 任务。`POST /api/traffic/iperf/client` 已传递关联参数，Job Center 已提供模块归属、任务查询与统一取消。Online MR 已复用该链并保存 iperf_runs/iperf_intervals。

后续设备任务中的性能测试应调用该服务并关联父任务。组织设备 UUID 与本机 iPerf 服务端 IP、协议、版本及端口之间尚无统一任务参数映射，本轮保留网络工具现有性能测试入口。网络性能测试涉及实际流量，设备只读 CLI 模板无法表达其生命周期。iperf2/iperf3 服务端兼容性由本轮网络服务审计负责。

## 验证与边界

- Python 任务中心、导出框架、API 边界和 Job Center 共 98 项定向测试通过，覆盖组织下级选择、互斥目标范围、参数边界、终态重试、取消前零设备连接、XLSX 长结果还原、只读模板保存策略，以及真实 Export Worker 生成可公开下载的 Artifact。
- Renderer 的 Job Center 与任务详情 23 项通过，固定导出动作审计与共享保存协调器 14 项通过。
- Ruff、vue-tsc 和 diff 空白检查通过。Python 测试存在既有 Starlette httpx 弃用提示。
- 新增组织流程使用隔离 fixture 验证。真实设备版本模板、LLDP 和导出已通过，详见同目录 PHASE7_DEVICE_TASK_LAB.md。Electron GUI 的 Phase 7 验收待主 Agent 汇总。
- 新增无线/MESH 采集相关的任务中心、现有 AC Mesh-Link 服务、设备命令能力与 API 边界共 132 项定向测试通过。Renderer Job Center 与导出入口审计 21 项通过，vue-tsc 和 Ruff 通过。
- 消费者审阅后补齐权限错误检查，复用 CLI_FAILURE_MARKERS，明确的查询失败会终止本设备采集。新增零 AP 下地址/射频权限失败、地址命令兼容回退、未知版本跳过四项回归，任务中心 33 项测试通过。
- FIT-AP 独立角色采集、文件传输父子任务关联、定时执行与持续监控仍需后续业务接入。既有无线/MESH Current、SFTP、iPerf 入口继续使用各自的执行链。
- 配置备份与光衰执行中对取消的响应受原采集器及进程停止宽限控制。取消任务的结果继承原 Job Center 语义，当前不提供已完成设备的独立部分结果恢复。

本轮仅使用 Workspace 下隔离测试根。

```text
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```
