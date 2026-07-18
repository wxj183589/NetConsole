# 业务服务

## 用途

本目录保存业务规则、用例协作服务、后台任务协议、导出规则、设备能力和跨 Repository 编排。

## 边界

永久 Service 必须是可独立测试的 Python 代码，不依赖桌面控件、Electron、Vue 或 FastAPI Request/Response。Qt/QProcess/QThread 适配层已删除，不得重新创建或被新代码复用。

## 主要入口

- `job_center/`、`export/`：任务和导出执行契约。
- `agent/`、`traffic/`、`online_mr/`：Agent、流量测试和 Online MR。
- `ac/`、`rail_transit/`、`network_tools/`：AC、轨交和网络工具业务。
- `device_form_rules.py`、`device_batch_operations.py`、`mesh_chart_payload.py`：从历史桌面 UI 抽离的纯规则和批量策略。
- `device_detail_query_service.py`：从设备快照、任务和现有业务 Query Service 组合设备详情只读 DTO。
- `device_operation_service.py`：校验 Operation ID、设备平台与 Profile 后，把设备刷新提交到现有 Task Center。
- `device_command_profile_service.py`：从版本化资源选择命令 Profile；未命中或未验证时失败关闭。
- `site_database_recovery.py`：局点数据库结构异常时的受控备份与重建文件流程。

## 依赖关系

上游由 Application Service、FastAPI 组合根和后台 Worker 调用；下游可调用 Repository、Parser、Core、模型和受控 Infrastructure。Service 不得反向导入 `netconsole.ui`。

## 数据与状态

数据库访问优先通过 Repository；文件路径通过 `PathResolver`。备份、删除、导出和清理必须有目录边界、失败保护和可回滚证据。

## 测试

对应测试位于 `../../../tests/`。数据删除和迁移测试必须使用 `tmp_path`，不得触碰真实 `.local/` 或用户数据。开发阶段优先运行受影响 Service/Command Profile/Task 定向测试；当前低 CPU 限制下，本轮文档同步未运行测试或构建。

## 修改规则

超过 300ms 的 IO/CPU/网络工作进入 Task Center，导出进入 Export Process；生产设备命令最终通过 Operation ID 和版本化 Command Profile 执行。

设备详情当前只为 `device.inventory.collect` 登记 `h3c.comware.switch.generic.device-inventory.v1`。执行边界是 H3C + `switch` + Comware 且 Profile 明确可执行；未知/未验证厂商、角色、平台或 Profile 不得回退执行 H3C 命令。软件版本未知时只允许资源显式声明的通用只读匹配。H3C AC 和 MR 仍由各自领域 Service 负责，设备详情仅查询关联事实；Huawei/ZTE 当前只支持已入库快照展示和接口归一化，不代表命令已验证。真实设备状态保持 `REAL_DEVICE_PENDING`。

设备详情 LLDP Query 映射不得公开邻居 `capabilities`、`model`，即使历史 Repository 行仍包含这些兼容字段；其余 LLDP 公开字段和底层历史数据保持不变。

## 生成与清理

Service 源码不自动生成；Job/Export 临时协议文件由对应 Runtime 在终态清理，用户原始数据和正式输出不属于普通缓存。

## 相关文档

- [架构](../../../docs/ARCHITECTURE.md)
- [Job Center](../../../docs/JOB_CENTER.md)
- [导出规范](../../../docs/export_process_policy.md)
- [数据布局](../../../docs/DATA_LAYOUT.md)
- [设备管理页面](../../../apps/web/src/views/devices/README.md)
- [版本化 Command Profile 清单](../../../docs/archive/migrations/electron-only/COMMAND-PROFILE-device-inventory-2026-07-18.md)
