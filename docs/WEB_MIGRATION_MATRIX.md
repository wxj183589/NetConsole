# NetConsole Web 迁移矩阵

## 用途

本文是长期迁移的模块级总览，用来回答“哪些能力进入永久 Electron/Vue 主界面、哪些仍依赖 Qt、哪些明确冻结”。具体页面与动作的证据矩阵见 [Qt/Electron 功能对等矩阵](development/qt-electron-parity-matrix.md)。

状态以代码、测试和真实验收为准，不以页面是否存在为准。截至当前，没有目标模块达到 `COMPLETE`。

## 模块总览

| 模块 | 当前 Qt | 当前 Electron/Vue | 当前结论 | 长期去向 |
| --- | --- | --- | --- | --- |
| 设备管理 | 生产入口 | CRUD/导入导出/诊断已实现；表单测试 Runtime bootstrap、统一任务窗口与诊断 allowlist 仍阻塞 | `PARTIAL` | Electron + Vue + FastAPI，达到 `COMPLETE` 后替换 Qt |
| AC 管理 | 生产入口 | 只读与部分受控能力 | `PARTIAL` | Vue + FastAPI，写操作需权限/确认/审计 |
| 轨道交通 | 生产入口/回退 | 主业务展示与部分控制已覆盖 | `PARTIAL` | Vue 主入口，补齐真实设备闭环 |
| 网络工具 | 生产入口 | Ping/fping/iPerf/端口能力部分覆盖 | `PARTIAL` | 本地与 Agent 统一任务模型 |
| 配置采集中心 | 生产入口 | 任务、查看、差异和下载部分覆盖 | `PARTIAL` | 复用正式采集 Service，不重写采集器 |
| 文件管理 | 生产入口 | 只读浏览与受控下载部分覆盖 | `PARTIAL` | Vue 主入口，远程删除不进入首批 |
| Job Center | 辅助/分散入口 | 已有统一页面，尚未完成 Qt 人工对照 | `IMPLEMENTED_UNVERIFIED` | 永久 Electron/Vue 基础能力 |
| Agent 控制 | 无独立完整 Qt 主入口 | 状态、包、任务与 Fake E2E 已有 | `FAKE` | 永久 Electron/Vue 能力，等待真实 Agent 验收 |
| Desktop Shell | Qt 为生产入口与稳定回退 | Electron 安全外壳、后端生命周期和 Native Bridge 基础可运行 | `IMPLEMENTED_UNVERIFIED` | 保留唯一 Vue Renderer；签名安装、升级和业务替换另行验收 |
| 全局 Dashboard | 分散展示 | 轨交看板已有，全局首页未完成 | `PARTIAL` | Vue 统一首页 |
| 系统设置 | 本机设置为主 | 主题/语言/主题色、工具与终端路径、端口/编码、保存/重载/默认恢复、局点事实与内部 Feature 配置已接入；本机动作经语义白名单 Bridge | `PARTIAL` | 全局 i18n 为 `BLOCKED_ON_GLOBAL_I18N`；Electron 人工与真实外部工具为 `MANUAL_DESKTOP_PENDING / REAL_DEVICE_PENDING` |
| 命令、日志等传统工具 | 生产入口 | 未完整迁移 | `NOT_STARTED` | 先收敛 Application Service，再建设 Web |
| SNMP 中心 | 历史代码保留，Feature 禁用 | 无导航 | `BLOCKED` | 排除本轮迁移；未来按新架构独立重建 |
| 无线勘测 | 历史代码保留，Feature 禁用 | 无导航 | `BLOCKED` | 排除本轮迁移；未来按新架构独立重建 |
| 网络工具无线扫描 | 现有能力 | 尚未完成 | `NOT_STARTED` | 与无线勘测区分，按网络工具范围评估 |

## 共同替换门槛

模块只有同时满足以下条件才能标记 `COMPLETE`：

- Qt 有效功能覆盖完整；
- Qt 与 Web 使用同一数据源和 Application Service；
- 写操作具备权限、预览、确认、Task 和审计；
- 页面刷新、关闭和恢复不丢失任务状态；
- 重复启动、停止不会生成重复 Task 或 Session；
- 性能不明显慢于 Qt，长任务不阻塞 WebHost；
- 凭据、Token、路径和原始文件不泄露；
- Fake 与真实场景验收均按模块要求通过；
- Qt 旧入口回归正常，并具有一个发布周期的回退方案。

达到门槛后的固定动作是：先将 Electron 设为默认入口，再隐藏 Qt 页面；稳定一个发布周期后才允许删除旧页面。普通浏览器只保留源码开发、诊断和 API 联调用途，不单独发布或验收。

## 明确冻结项

SNMP 中心和无线勘测当前只保留历史代码与数据：

- 不进入 Web 导航；
- 不为它们新增 Qt、Vue 或 Electron 功能；
- Feature Registry 保持禁用；
- 不在本轮迁移中做兼容层或功能补齐；
- 未来若重启，应建立新的迁移任务并从 `NOT_STARTED` 重新评估，不复用旧页面作为目标架构。
