---
name: snmp-collector-design-skill
description: "SNMP GET、GETNEXT、GETBULK、GETSUBTREE、WALK、BULKWALK、TABLEWALK、SET、OID 轮询、timeout、retries、并发、缓存、取消或 H3C AC/AP 采集策略任务时使用。MIB 文件/模块依赖使用 h3c-snmp-mib-skill；纯 CLI parser 或页面配色不使用本 Skill。"
---

# 目标

实现或重构可控、可取消、非阻塞的 SNMP 请求与批量采集，并保持请求模型、OID 映射、结果缓存/持久化和 UI 展示解耦。

# 触发与反例

触发示例：

- “增加 GETBULK/TABLEWALK 并限制返回规模。”
- “SNMP WALK 无法取消，查询还会卡 UI。”
- “为 H3C AC 增加多设备目标表采集和超时策略。”

不应触发：

- “修复 HH3C MIB 模块依赖。”
- “解析 H3C display 命令或只改表格颜色。”

# 输入与输出

- 输入：操作、目标设备/OID、协议参数、频率/并发、持久化和失败策略。
- 输出：可序列化请求、Domain/Job 实现、结构化结果、缓存/数据库影响和验证证据。
- 允许修改生产代码：允许，限 SNMP 模型、服务、Job handler、Repository、轻量 UI 接入及测试；安全策略或 schema 变化必须明确说明。

# 开始前读取

- `netconsole/services/snmp_client.py`、`netconsole/services/snmp_query_service.py`、`netconsole/services/snmp_poll_service.py`。
- `netconsole/services/snmp/`、`netconsole/services/job_center/handlers/snmp_jobs.py`。
- `netconsole/models/snmp_models.py`、`netconsole/repositories/global_mib_repository.py`、`netconsole/repositories/site_snmp_repository.py`。
- `netconsole/ui/pages/snmp_center_page.py`、`netconsole/ui/snmp_collection_helper.py`。
- `tests/test_snmp_query_job.py`、`tests/test_snmp_collection_job.py`、`tests/smoke/snmp/`。

# 工作流程

1. 区分一次性发现、周期状态和高频监控；默认不对大表高频 WALK。
2. 用当前请求模型表达 GET、GETNEXT、GETBULK、GETSUBTREE、WALK、BULKWALK、TABLEWALK 和 SET。
3. 普通查询提交 `snmp_query_execute`，多设备只读批量采集提交 `snmp_collection_execute`；UI 不创建 SnmpClient、线程池或跨线程 Repository。
4. 对 H3C AC/AP 只采集明确目标表，不做全 MIB WALK；GETBULK 限制 `max_repetitions`、`max_rows` 和子树范围。
5. 支持 timeout、retries、interval、concurrency、设备级队列/并发窗口和 cancellation；单设备失败不阻塞其他设备。
6. 结果保存原始 OID、value type、value/decoded value、状态、错误、耗时和可追溯 varbind；UI 字段映射放在 formatter/ViewModel。

# 项目约束

- 当前生产客户端支持 v1/v2c；保留 v3 模型和 UI，但当前内置适配层不支持 v3 请求/SET，不得写成已完整支持。
- 批量并发遵守现有 5～50 边界，每设备独立 Client；Collection 层重试时底层请求 retries 置零，避免重试相乘。
- 缓存去敏并原子写入，不保存 community、v3 密钥等认证字段；SQLite 连接在 Worker 内创建，规避跨线程锁。
- SET 保持显式开关、写 community/安全级别检查和错误反馈；不把批量 SET 混入只读 Collection。

# 验证与失败报告

- 验证单 OID GET、GETNEXT、GETBULK、表 WALK/BULKWALK、取消、部分失败、无响应超时、缓存去敏和唯一终态。
- H3C 任务同时验证 MIB 节点搜索及目标表范围；真实设备 smoke 只能在用户授权的设备清单上执行。
- 输出目标表、频率/并发上限、超时/重试、数据库/缓存影响、旧 SNMP/MIB 兼容性和未验证设备风险。

# 相关 Skills

- MIB/OID 资源：`h3c-snmp-mib-skill`。
- 后台任务协议：`netconsole-job-center-skill`。
- 数据安全：`netconsole-data-safety-skill`。
