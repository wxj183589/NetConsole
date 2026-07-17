# 业务服务

## 用途

本目录保存业务规则、用例协作服务、后台任务协议、导出规则、设备能力和跨 Repository 编排。

## 边界

永久 Service 必须是可独立测试的 Python 代码，不依赖 Qt 控件、Electron、Vue 或 FastAPI Request/Response。当前少量 Qt/QProcess/QThread 适配文件属于 E1 待删除兼容层，不得被新代码复用。

## 主要入口

- `job_center/`、`export/`：任务和导出执行契约。
- `agent/`、`traffic/`、`online_mr/`：Agent、流量测试和 Online MR。
- `ac/`、`rail_transit/`、`network_tools/`：AC、轨交和网络工具业务。
- `device_form_rules.py`、`device_batch_operations.py`、`mesh_chart_payload.py`、`mesh_series_metadata.py`：从 Qt UI 抽离的纯规则和批量策略。
- `site_database_recovery.py`：局点数据库结构异常时的受控备份与重建文件流程。

## 依赖关系

上游由 Application Service、FastAPI 组合根和后台 Worker 调用；下游可调用 Repository、Parser、Core、模型和受控 Infrastructure。Service 不得反向导入 `netconsole.ui`。

## 数据与状态

数据库访问优先通过 Repository；文件路径通过 `PathResolver`。备份、删除、导出和清理必须有目录边界、失败保护和可回滚证据。

## 测试

对应测试位于 `../../../tests/`。数据删除和迁移测试必须使用 `tmp_path`，不得触碰真实 `.local/` 或用户数据。

## 修改规则

超过 300ms 的 IO/CPU/网络工作进入 Task Center，导出进入 Export Process；生产设备命令最终通过 Operation ID 和版本化 Command Profile 执行。

## 生成与清理

Service 源码不自动生成；Job/Export 临时协议文件由对应 Runtime 在终态清理，用户原始数据和正式输出不属于普通缓存。

## 相关文档

- [架构](../../../docs/ARCHITECTURE.md)
- [Job Center](../../../docs/JOB_CENTER.md)
- [导出规范](../../../docs/export_process_policy.md)
- [数据布局](../../../docs/DATA_LAYOUT.md)
