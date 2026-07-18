# 展示模型

## 用途

本目录将 Python Core 已确定的中立业务数据转换为 API 或页面所需的只读展示结构。

## 边界

展示模型可以保存 i18n key、显示精度和最终文本格式；不得连接数据库、执行设备命令、修改任务状态或重新计算业务结论。

## 主要入口

- `device_detail_view_model.py`：设备详情展示摘要。
- `fit_ap_view_model.py`、`trackside_view_model.py`：FIT-AP 与轨旁数据展示结构。
- `mesh_series_view_model.py`：MESH 指标标签、精度与最终显示格式。

## 依赖关系

本目录只依赖稳定模型和纯 Core 规则。业务语义由 `src/netconsole/models/` 提供，Vue 不在此层反向参与判断。

## 数据与状态

本目录不保存运行状态，不持有凭据、数据库连接或服务端绝对路径。

## 测试

展示格式测试位于 `tests/test_mesh_series_view_model.py` 及相关专题测试。

## 修改规则

修改显示格式时不得改变原始 API 数值、MESH 统计结果或 ACTIVE/STANDBY 业务编码。

## 生成与清理

本目录无生成源码；仅 Python 缓存可以安全删除。

## 相关文档

- [MR/MESH 日志分析规则](../../../../docs/mr_mesh_log_analysis_rules.md)
- [架构合规说明](../../../../docs/ARCHITECTURE_COMPLIANCE.md)
