# 稳定数据模型

## 用途

本目录保存跨 UI/API/Service 使用的稳定 Python 数据模型、值对象和纯展示摘要模型。

## 边界

模型可以进行轻量、确定性的规范化和格式转换；不得导入 Qt、FastAPI、Electron、Repository 或执行设备、文件、网络和数据库操作。

## 主要入口

- `device.py`、`device_credentials.py`：设备与凭据安全模型。
- `mesh_log_models.py`、`mesh_analysis_params.py`：MESH 分析模型与参数。
- `mesh_series.py`：MESH 指标 ID、单位语义、数值类型与业务状态编码。
- `online_mr_*.py`、`traffic_test.py`：Online MR 与流量测试模型。
- `diagnostics_summary.py`：安全聚合诊断摘要模型。

## 依赖关系

Application Service、Service、Router DTO 映射和测试可以导入本目录；本目录只依赖 Python 标准库和必要的低层 Core 值规则。

## 数据与状态

模型不持有数据库连接，不读取用户文件，不持久化 Token、密码或服务端绝对路径。

## 测试

对应测试位于 `../../../tests/`，以模型或业务专题测试文件覆盖。

## 修改规则

已发布字段、枚举和状态值需要兼容审计；未知值不得伪造成零或空字符串。

## 生成与清理

本目录无生成源码；仅 Python 缓存可安全删除。

## 相关文档

- [开发指南](../../../docs/DEVELOPMENT_GUIDE.md)
- [API/Application 边界审计](../../../docs/API_APPLICATION_BOUNDARY_AUDIT.md)
