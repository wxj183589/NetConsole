# NetConsole 下一阶段开发指南

本文只定义下一阶段最重要的架构约束。后台任务、数据安全、编码、目录和 UI 细则继续遵守 [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) 与 [development/repository-layout.md](development/repository-layout.md)。

## 新功能默认链路

新的用户功能按以下顺序落地：

```text
业务规则 / Domain
    ↓
Application Service
    ↓
FastAPI DTO 与 Router
    ↓
Vue 页面
    ↓
模块定向测试与真实验收
```

除修复现有生产缺陷外，不新增 Qt 业务页面、Qt 业务流程或只供 Qt 使用的新 Service。迁移期 Qt 只能复用永久业务层。

## 依赖规则

### Vue

- 负责展示、交互、轻量输入校验和状态绑定；
- 通过版本化 HTTP/WebSocket API 获取数据和发起操作；
- 不保存明文凭据，不拼接设备命令，不实现业务状态机；
- 页面刷新或重新打开后必须能从服务端恢复任务状态。

### FastAPI Router

- 使用明确的请求/响应 DTO 和白名单字段；
- 只做鉴权、参数校验、调用 Application Service 和响应映射；
- 不直接访问 Repository、SQLite、SSH、SNMP、Agent 运行目录或设备文件；
- 长任务进入 Task/Job 体系，不能阻塞 WebHost。

### Application Service

- 编排业务用例、权限、确认、审计、Task、Session、Mapping 和 Artifact；
- 复用现有 Repository、Parser、Adapter 和路径 helper；
- 不依赖 Vue、Electron 或 QWidget；
- 同一个操作由 Qt 与 Web 触发时必须产生一致状态，不能生成重复任务。

### Electron

Electron 仅在后续独立阶段建设，只允许：

- 窗口、托盘和进程生命周期；
- 服务启动、停止和恢复；
- 系统通知与升级；
- 经白名单验证的 `selectFile`、`selectDirectory`、`openArtifact`、`openFolder`、`launchTerminal`、`notification`。

不得提供通用 `execute(command)`、任意 `open(path)` 或 `run(exe)`，不得在 Electron Main/Preload 中实现设备、数据库或采集业务。

## 写操作要求

涉及设备、配置、文件、Agent 或基础资料的写操作至少具备：

1. 权限检查；
2. 参数白名单；
3. 操作预览；
4. 用户确认；
5. Task/Job 化执行；
6. 审计记录；
7. 幂等启动和停止；
8. 页面刷新后的状态恢复；
9. 明确失败原因与可重试边界。

凭据不得返回 Vue、写入日志、Task 元数据或 Artifact。

## Feature Registry 与导航

- 新页面、Tab、动作和按钮默认注册 Feature Registry；
- Web 导航只展示已开放能力，不以路由存在替代 Feature Gate；
- Qt 与 Web 并行期，功能状态和默认开关必须有唯一来源；
- SNMP 中心和无线勘测保持禁用，不新增 Web 导航；
- 网络工具中的无线扫描是独立功能，不能误用无线勘测的排除结论。

## 测试与合并

- Worker/模块任务优先运行后端、前端和架构定向测试；
- Fake E2E 与真实设备验收分开记录；
- 不把没有环境的真实验收写成已通过；
- 多分支集成前由指挥中心统一检查冲突、迁移矩阵和文档；
- 最终集成执行 Python 全量测试、前端测试与构建、Ruff、文档链接检查及受影响的 Go 测试；
- 纯文档任务只运行文档定向校验和链接检查，除非它与代码改动一起进入集成批次。

## 禁止的捷径

- 在 Vue、Electron 或 Router 中复制 Qt 的业务代码；
- 为满足目录示意图创建空层或机械移动包；
- 绕过 Application Service 直接操作设备或数据库；
- 用前端轮询制造第二套任务状态；
- 未完成真实验收就隐藏或删除 Qt 页面；
- 为被冻结模块添加临时入口；
- 为桌面桥接提供任意命令、任意路径或任意程序执行能力。

## 开发前检查

开始实现前回答：

- 这个功能属于永久架构还是迁移兼容？
- 现有 Qt 业务逻辑位于哪里，哪些可以直接复用？
- Application Service 是否已存在，Router 是否足够薄？
- Task、Session、Mapping、Artifact 与权限审计如何复用？
- Feature Registry、导航、文档和真实验收门槛是什么？
- 失败、刷新、重复启动、停止和回退如何处理？

无法回答时先做审计，不先堆页面。
