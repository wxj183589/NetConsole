# Python Runtime 启动协调

## 用途

本目录负责 Python Core/FastAPI Runtime 的启动、停止、本地监听和迁移期 Shell 分派。

## 边界

只允许开发诊断服务生命周期、运行模式和受控 loopback Web Server；不得承载设备、数据库、采集、报告或 UI 业务逻辑。Qt probe、`auto/qt` 和 Qt Shell 分支已删除。

## 主要入口

- `runtime_supervisor.py`：统一持有和停止 FastAPI Runtime。
- `web_server.py`：随机端口、短期桌面会话和 Uvicorn 生命周期。
- `launcher.py`：仅分派显式 `server` 本机开发诊断；不是正式桌面 Launcher。
- `electron_desktop.py`：无参数 `main.py` 的源码开发桥接，只启动项目本地 Electron 编排器，不持有 Backend 生命周期。

## 依赖关系

本目录可依赖 Core、FastAPI 组合根和运行模式；不得导入 `netconsole.ui`。Electron Main 通过独立 Python Runtime 协议管理后端，不直接导入本目录的业务对象。

## 数据与状态

路径由 `PathResolver` 提供；会话 Token 只在进程内存中存在，不写 URL、日志、数据库或仓库文件。

## 测试

对应测试包括 `tests/test_web_host.py`、Launcher、Electron Runtime 和发布导入图测试。

## 修改规则

Vite/FastAPI 开发入口默认只绑定 `127.0.0.1`；生产不得增加无认证调试后门、任意 Shell、SQL 或文件接口。

## 生成与清理

本目录无版本化生成文件；Python 缓存可安全删除。

## 相关文档

- [Electron Desktop](../../../docs/architecture/DESKTOP.md)
- [当前架构](../../../docs/ARCHITECTURE.md)
- [构建与发布](../../../docs/release/BUILD_AND_RELEASE.md)
