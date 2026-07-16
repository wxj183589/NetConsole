# NetConsole Web 迁移计划

## 目标与边界

迁移目标是让 Electron Desktop + Vue 成为永久桌面主界面、FastAPI 成为永久业务入口，Qt 在迁移期继续承担现有生产入口与回退，完成验收后逐模块退出。普通浏览器只保留开发、诊断和 API 联调，不作为第三套正式产品入口。

Electron 安全外壳基础已在独立目录建立；这不授权批量改名、搬目录、删除 Qt 或绕过业务迁移门槛。最终架构见 [ARCHITECTURE_NEXT.md](ARCHITECTURE_NEXT.md)，当前覆盖事实见 [WEB_MIGRATION_MATRIX.md](WEB_MIGRATION_MATRIX.md)。

## 固定迁移流程

每个模块必须依次完成：

1. **审计 Qt 现状**：页面能力、输入、Service、Repository、数据库、文件、状态机和异常处理。
2. **收敛共享业务层**：把设备、数据库和业务规则放入 Application Service 或既有共享组件。
3. **提供 FastAPI 契约**：使用白名单 DTO、权限、审计和稳定错误语义；Router 不直连设备与数据库。
4. **建设 Vue 页面**：先只读，再受控操作；不在 Vue 重写业务规则。
5. **Qt/Electron 并行验收**：数据、Task、Session、Mapping、Artifact 和状态恢复保持一致。
6. **真实环境验收**：设备、Agent、权限、性能、恢复和凭据安全全部达标。
7. **逐模块替换**：Electron 默认，Qt 入口先隐藏并保留一个发布周期回退，稳定后再删除。

## 状态门槛

| 状态 | 含义 | 是否可替换 Qt |
| --- | --- | --- |
| `NOT_STARTED` | 尚未形成 Electron 业务能力 | 否 |
| `UI_ONLY` | 只有静态 UI 或前端临时状态 | 否 |
| `READ_ONLY` | 读取真实数据，但 Qt 操作未迁移 | 否 |
| `FAKE` | 主要证据仍是 Fake 数据或 Fake 执行 | 否 |
| `PARTIAL` | 已有部分真实闭环，但缺少 Qt 能力或验收 | 否 |
| `IMPLEMENTED_UNVERIFIED` | 真实调用链和自动测试已具备，待人工对照 | 否 |
| `REAL_DEVICE_PENDING` | 人工软件流程通过，待真实设备/现场验收 | 否 |
| `COMPLETE` | 功能、自动测试、人工对照和真实设备验收全部通过 | 是 |
| `BLOCKED` | 由产品决策、授权或环境冻结 | 不迁移/待解锁 |

任何模块不得因“页面已存在”直接进入 `COMPLETE`。唯一详细定义见 [Qt/Electron 功能对等矩阵](development/qt-electron-parity-matrix.md)。

## 当前阶段

当前处于“Core/API 收敛、Vue 建设与 Electron/Qt 并行迁移期”：

- Launcher/Core 生命周期第一阶段已完成，支持 Qt、Web 和 Server 模式；
- Vue、FastAPI、Task/Session/Mapping/Artifact 与 Agent 链路已有实际能力；
- 多个 Qt 页面仍直接持有页面级业务对象，共享 Application Service 尚未全部收敛；
- 当前默认入口和稳定回退仍是 Qt；
- 当前没有目标模块达到 `COMPLETE`；
- Electron 安全外壳、Python supervisor、白名单 Native Bridge 和 Vue 双运行时 Adapter 已形成可运行基础，但尚未进入正式安装发布，也未替代任何 Qt 业务页面。

## 执行顺序

### 阶段一：先修架构约束

- 固化目标架构、开发指南和迁移矩阵；
- 禁止新增 Qt 业务页面；
- 审计 Router 直连 Repository、设备或文件系统的情况；
- 为现有 Web 模块补齐统一 DTO、权限、审计、任务状态和错误语义；
- 明确 SNMP 中心、无线勘测为 `BLOCKED`，当前排除迁移；未来如重启需独立立项。

### 阶段二：补齐永久 Web 能力

按业务依赖和真实环境可用性推进：

1. 设备管理；
2. 网络工具；
3. 配置采集中心；
4. 文件管理；
5. Agent 远程执行和多 Agent；
6. AC 受控写操作；
7. 统一首页、设置、权限与审计。

任务内先跑模块定向测试；多个任务完成并准备合并时，再由指挥中心执行全量回归。

### 阶段三：Electron 默认与 Qt 退出

- 每个模块达到 `COMPLETE` 后，将 Electron 设为默认入口；
- Qt 页面先隐藏，不立即删除；
- 保留一个发布周期的回退开关和数据兼容；
- 回退期结束后删除对应 Qt 页面和仅为它服务的适配代码；
- 所有模块完成后再移除 Qt 运行依赖。

### 阶段四：Electron 外壳

基础外壳已提前完成，用于尽早验证生命周期、安全边界和唯一 Vue Renderer；继续扩展仍以 Electron 主流程稳定、API 契约成熟为前提：

- Electron 独立位于 `apps/desktop_electron/`，Qt Legacy 继续位于 `apps/desktop/`，当前不互相替换；
- 当前已具备安全窗口、Python 进程生命周期和白名单 Native Bridge，托盘、签名安装、升级仍待后续任务；
- 复用现有 Vue 构建和 FastAPI 服务，不复制页面或业务逻辑；
- 完成本机路径、终端启动、升级签名和安全审计后，再进入默认桌面发布。

## 每个任务的交付清单

- 明确当前状态和目标状态；
- 记录复用的 Application Service、Repository、Task、Session 和 Artifact；
- 记录 Feature Registry 与 Web 导航变化；
- 给出模块定向测试结果；
- 写明 Fake 验收、真实验收和冻结项；
- 合并前由指挥中心检查跨模块回归；
- 更新 [WEB_MIGRATION_MATRIX.md](WEB_MIGRATION_MATRIX.md) 和必要的专题文档；
- 未达门槛时不得隐藏或删除 Qt 入口。
