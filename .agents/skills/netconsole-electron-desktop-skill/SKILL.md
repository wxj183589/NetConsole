---
name: netconsole-electron-desktop-skill
description: "NetConsole Electron Main、Preload、IPC、Native Bridge、受管 Python Backend 生命周期、单实例、工作区窗口、托盘、桌面通知或 Desktop-only runtime 任务时使用。普通 Vue 页面业务、Python 领域 Service 或 NSIS/发布制品任务不使用本 Skill。"
---

# 目标

维护 Electron 唯一桌面宿主及其安全边界，使 Main、Preload、唯一 Vue Renderer 和受管 FastAPI Backend 共享一套明确、可回收、可验证的运行时契约。

# 触发与反例

触发示例：

- “修改 Electron Main/Preload IPC 或 Native Bridge。”
- “修复 Backend 启停、重连、托盘、多窗口或单实例恢复。”
- “增加受控本机文件选择、通知或外部程序动作。”

不应触发：

- “只修改某个 Vue 业务页面或 FastAPI 领域逻辑。”
- “构建 NSIS、调整 Full/Customer 包或发布制品。”

# 输入与输出

- 输入：目标桌面能力、受信调用方、DTO、生命周期阶段、安全边界、失败和恢复行为。
- 输出：Main/Preload/Shared/Renderer Adapter 或 Backend lifecycle 的最小修改、兼容风险、自动验证与人工桌面缺口。
- 允许修改生产代码：允许，限 Electron 宿主、桌面 Platform Adapter 和必要的 Python runtime adapter；不得把业务规则搬进 Electron。

# 开始前读取

- `docs/architecture/DESKTOP.md`、`docs/architecture/NATIVE_BRIDGE.md`、`docs/ARCHITECTURE.md`。
- `apps/desktop_electron/src/main/`、`apps/desktop_electron/src/preload/`、`apps/desktop_electron/src/shared/`。
- `apps/desktop_renderer/src/platform/`、`src/netconsole/backend/electron_runtime.py`、`src/netconsole/backend/api/main.py`。
- `apps/desktop_electron/tests/`、`tests/test_electron_runtime.py` 和目标 Bridge/Renderer Adapter 测试。

# 当前架构事实

- Electron 是唯一正式桌面外壳，`apps/desktop_renderer` 是唯一 Vue Renderer；普通 Browser 仅用于开发诊断，不建立第二套产品链。
- Main 只负责窗口、进程、动态回环 Origin、会话、CSP、导航和白名单本机动作；设备、采集、数据库、报告和业务状态机留在 Python Application Service。
- Preload 通过 `contextBridge` 逐项暴露固定方法；Main 和 Preload 都必须校验 DTO 与 sender。
- Backend 由 Main 以参数数组、`shell=false` 和动态端口启动；临时令牌只保存在内存受信链，不能进入 URL、日志或持久化配置。
- Qt/PySide6/QFluentWidgets 已退出活动架构，不得增加兼容导入、回退壳或第二套桌面 Bridge。

# 工作流程

本领域变更通常属于 L4；编码前先组合 `netconsole-change-review-skill`，确认所有窗口、Renderer、Backend、Bridge 和发布消费者及合并后回归。

1. 先标明变更属于窗口、IPC、Bridge、Backend lifecycle、下载、托盘/通知、工作区或 Renderer runtime adapter，并画出调用双方。
2. 对 IPC/Bridge 定义强类型 DTO、固定 channel、长度/枚举/未知字段限制和 sender 校验；同时修改 Shared、Preload、Main、Renderer 类型与测试。
3. 保持 `nodeIntegration=false`、`contextIsolation=true`、`sandbox=true`、导航/新窗口/权限拒绝和生产 CSP；Feature Gate 不能替代 Main 安全校验。
4. 维护 Backend `starting -> ready -> stopped|failed`、动态 Origin/Token generation、健康检查、重绑定和 `shutdown -> shutdown_ack -> exit` 顺序；写操作不得在连接恢复时自动重放。
5. 多窗口、托盘和单实例必须复用同一个 Backend 与 Vue Renderer；窗口恢复不能重新加载页面、重建 Backend 或跨局点恢复业务状态。
6. 文件或外部程序能力只增加语义 ID、opaque ID 或短期 capability；Main 自行解析已授权路径和固定动作，不接受 Renderer 提供任意路径、URL、命令或 argv。
7. 网络、磁盘、压缩、报告和批量工作不得阻塞 Main 或 Renderer；交给现有 Application Service、Job 或 Export Process。
8. 将自动测试、源码 smoke、正式包 smoke、Windows GUI/托盘/对话框人工验收分开报告。

# 禁止模式与不变量

- 不暴露完整 `ipcRenderer`、通用 `invoke/send`、`fs`、环境变量、任意 URL、命令字符串或 `shell=true`。
- 不把 API Token、Cookie、密码、完整本机路径、数据库路径或设备凭据返回 Renderer。
- 不为一个窗口、标签或业务模块创建第二个 Backend、第二套 Renderer 或 Electron 专属业务 Core。
- 不把 Browser 开发联调、Vitest 或源码 smoke 写成正式 Electron GUI、安装包或真实设备验收通过。
- 不重新引入 Qt，也不靠恢复旧桌面入口规避缺失能力。

# 验证与失败报告

- 在 `apps/desktop_electron` 运行受影响 Vitest、`pnpm run typecheck` 和 `pnpm run build:main`；生命周期改动按需运行 `pnpm smoke:dev` 或对应 workspace/tray smoke。
- 在 `apps/desktop_renderer` 运行受影响 Platform Adapter/调用方 Vitest 和 `pnpm build`；Python adapter 改动运行对应 pytest。
- 覆盖非法 sender、未知字段、路径/URL/命令注入、Backend 未就绪、重启 generation、重复停止、下载中退出和资源清理。
- 报告 IPC 双方、Runtime/安全不变量、Main/Renderer 阻塞风险、兼容性、实际命令和未执行的 Windows 人工验收。

# 相关 Skills

- L3/L4 影响审计：`netconsole-change-review-skill`。
- 安装包与发布：`netconsole-release-packaging-skill`。
- 用户文件选择和最终保存：`netconsole-user-file-interaction-skill`。
- 数据根和 SQLite：`netconsole-data-safety-skill`。
