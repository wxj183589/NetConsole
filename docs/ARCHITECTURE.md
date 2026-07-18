# NetConsole 当前架构

## 产品边界

NetConsole 当前正式桌面产品只有 Electron。Electron Main/Preload 承载窗口、受管 Backend 生命周期和白名单本机能力；Vue 3 是唯一 Renderer；FastAPI/Python Core 是永久业务层。本机 Browser 与无 Shell Server 只用于源码开发、诊断和 API 联调，不构成独立产品或失败回退。

Qt/PySide6/QFluentWidgets 源码、入口、运行依赖和发布链已经删除。历史行为只通过 Git 与[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)追踪，不能恢复 Qt 入口规避未完成业务。

## 启动链

```mermaid
flowchart LR
    P["PyCharm / python main.py"] --> D["Electron 开发编排"]
    D --> E["Electron Main / Preload"]
    E --> V["Vue Renderer"]
    E --> B["受管 FastAPI Backend"]
    V --> B
    B --> A["Application Service"]
    A --> S["Domain Service / Parser"]
    A --> R["Repository"]
    A --> J["Task / Export Process"]
    R --> DB["SQLite / 受控文件"]
```

- 无参数 `main.py` 与 `apps/desktop_electron` 的 `pnpm dev` 进入同一开发编排链。
- 打包态由 Electron 以内部 `--electron-backend` 启动冻结 Backend。
- Backend 只监听随机 loopback 端口，桌面会话令牌每次启动重新生成，不写 URL、日志或 SQLite。
- `main.py --mode web|server` 只用于显式本机开发诊断。

## 永久分层

| 层 | 允许职责 | 禁止职责 |
| --- | --- | --- |
| Electron Main/Preload | 窗口、进程、IPC、原生选择器、受控打开/下载 | 设备命令、SQL、Parser、业务状态机、任意命令/路径桥接 |
| Vue Renderer | 页面、表单、表格、图表、轻量显示转换 | SSH/SNMP、数据库、文件业务、命令选择、核心算法 |
| FastAPI Router | 鉴权、DTO、Service 调用、HTTP/WS 映射 | 直接 SQL、设备连接、目录扫描、长任务和业务规则 |
| Application Service | 用例编排、校验、任务、事务与跨服务协作 | Electron/Vue/FastAPI Request、宿主对象 |
| Domain Service / Parser | 设备与业务规则、解析、归一化、报告 | UI、HTTP、IPC |
| Repository | SQLite 查询、事务、迁移、分页与记录映射 | UI、设备命令和业务判定 |

## 后台任务与导出

预计超过 300ms 的网络、磁盘、解析、批量和 CPU 工作进入 Job Center。`TaskApplicationService/TaskRuntime` 维护七状态、JSONL 事件、协作取消和 `tasks.db`；`LocalProcessAdapter` 负责 Worker 进程和 Windows 进程树回收。所有正式导出进入独立 Export Process，先写临时文件，成功后原子替换。

页面关闭不等于停止任务。任务取消、重试、Artifact 下载和打开能力必须由任务 owner 明确授权，不能由前端伪造状态。

## 数据与资源

- 版本唯一来源：`src/netconsole/core/version.py`。
- Feature 唯一来源：`src/netconsole/core/feature_registry.py`。
- 路径唯一来源：`src/netconsole/core/paths.py`。
- 开发数据位于 `.local/`，打包态位于系统应用数据目录；运行数据不得写回源码。
- 主应用、Task、Agent、Traffic、Online MR 与 MESH 数据各有独立 Repository/领域路径，不跨线程或进程共享 SQLite connection。
- 随包 fping/iPerf 唯一来源为 `resources/tools/`，构建不得联网下载业务工具。

## 当前完成边界

“Qt 已删除”只表示技术栈和启动架构完成收口，不表示所有业务都通过人工或真实设备验收。模块状态以[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)、Navigation Registry、Feature Registry 和测试为准；自动测试不能把 `PARTIAL`、`IMPLEMENTED_UNVERIFIED` 或 `REAL_DEVICE_PENDING` 提升为 `COMPLETE`。

SNMP Center、通用 MIB/OID 平台和无线勘测属于批准删除项。设备管理只保留 SNMP v1/v2c 基础识别；网络工具无线扫描是独立能力。

## 架构门

新增功能必须沿 `Application Service -> FastAPI -> Vue` 建设，并通过 Electron 白名单本机能力完成桌面闭环。架构边界、历史迁移分类和未解决项见[架构一致性规则](ARCHITECTURE_COMPLIANCE.md)及[当前审计报告](archive/migrations/electron-only/ARCHITECTURE_COMPLIANCE_REPORT.md)。
