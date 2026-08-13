# NetConsole Python 包

## 用途

本目录承载 NetConsole 的 Python Core、FastAPI、Application Service、Repository、Parser、模型、基础设施和只读版本化资源。

## 边界

永久业务代码不得依赖 Electron、Vue、FastAPI Request/Response 或桌面控件。旧 `ui/`、`app.py` 和 Qt 专属 Adapter 已删除，不得重新创建或作为新功能落点。

## 主要入口

- `backend/`：FastAPI 与 Electron Python Runtime。
- `application/`、`services/`：业务用例编排和领域服务。
- `repositories/`、`parsers/`、`infrastructure/`：存储、协议和外部适配。
- `core/`、`models/`：共享规则、路径、版本和稳定数据模型。

## 依赖关系

依赖方向为 API/桌面适配层到 Application Service，再到 Service、Repository、Parser 和 Core；下层不得反向导入 UI。

## 数据与状态

所有运行路径由 `core/paths.py` 与运行环境 helper 解析；源码目录不得保存用户数据库、会话、报告或凭据。

## 测试

测试位于 `../../tests/`。开发阶段先运行受影响定向测试，最终组合按测试基线执行全量门禁。

## 修改规则

Router 保持薄层，长任务进入 Task Center，导出进入 Export Process；不得在 Vue、Electron 或 Router 中复制业务规则。

## 生成与清理

Python 缓存可安全删除；包内版本化资源不可按缓存处理。

## 相关文档

- [当前架构](../../docs/ARCHITECTURE.md)
- [开发规则](../../docs/DEVELOPMENT_RULES.md)
- [数据布局](../../docs/storage/DATA_LAYOUT.md)
