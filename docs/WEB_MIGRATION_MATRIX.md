# NetConsole Web 迁移矩阵

## 用途

本文是长期迁移的模块级总览，用来回答“哪些能力进入永久 Web 主界面、哪些仍依赖 Qt、哪些明确冻结”。具体页面与动作的证据矩阵见 [WEB_QT_PARITY_MATRIX.md](WEB_QT_PARITY_MATRIX.md)。

状态以代码、测试和真实验收为准，不以页面是否存在为准。截至当前，没有目标模块达到 `REPLACE_READY`。

## 模块总览

| 模块 | 当前 Qt | 当前 Web | 当前结论 | 长期去向 |
| --- | --- | --- | --- | --- |
| 设备管理 | 生产入口 | 已有列表、详情与部分操作 | `IN_PROGRESS` | Vue + FastAPI，达到 `REPLACE_READY` 后替换 Qt |
| AC 管理 | 生产入口 | 只读与部分受控能力 | `IN_PROGRESS` | Vue + FastAPI，写操作需权限/确认/审计 |
| 轨道交通 | 生产入口/回退 | 主业务展示与部分控制已覆盖 | `IN_PROGRESS` | Vue 主入口，补齐真实设备闭环 |
| 网络工具 | 生产入口 | Ping/fping/iPerf/端口能力部分覆盖 | `IN_PROGRESS` | 本地与 Agent 统一任务模型 |
| 配置采集中心 | 生产入口 | 任务、查看、差异和下载部分覆盖 | `IN_PROGRESS` | 复用正式采集 Service，不重写采集器 |
| 文件管理 | 生产入口 | 只读浏览与受控下载部分覆盖 | `IN_PROGRESS` | Vue 主入口，远程删除不进入首批 |
| Job Center | 辅助/分散入口 | 已有统一页面 | `CONTROLLED_WRITE` | 永久 Web 基础能力 |
| Agent 控制 | 无独立完整 Qt 主入口 | 状态、包、任务与 Fake E2E 已有 | `FAKE_ACCEPTED` | 永久 Web 能力，等待真实 Agent 验收 |
| Desktop Shell | Qt 为生产入口与稳定回退 | Electron 安全外壳、后端生命周期和 Native Bridge 基础可运行 | `FOUNDATION_READY` | 保留唯一 Vue Renderer；签名安装、升级和业务替换另行验收 |
| 全局 Dashboard | 分散展示 | 轨交看板已有，全局首页未完成 | `IN_PROGRESS` | Vue 统一首页 |
| 系统设置 | 本机设置为主 | 部分未开始 | `NOT_STARTED` | 用户设置进 Web；本机能力经 Electron 白名单桥接 |
| 命令、日志等传统工具 | 生产入口 | 未完整迁移 | `NOT_STARTED` | 先收敛 Application Service，再建设 Web |
| SNMP 中心 | 历史代码保留，Feature 禁用 | 无导航 | `EXCLUDED / FUTURE_REBUILD` | 不迁移；未来按新架构独立重建 |
| 无线勘测 | 历史代码保留，Feature 禁用 | 无导航 | `EXCLUDED / FUTURE_REBUILD` | 不迁移；未来按新架构独立重建 |
| 网络工具无线扫描 | 现有能力 | 尚未完成 | `NOT_STARTED` | 与无线勘测区分，按网络工具范围评估 |

## 共同替换门槛

模块只有同时满足以下条件才能标记 `REPLACE_READY`：

- Qt 有效功能覆盖完整；
- Qt 与 Web 使用同一数据源和 Application Service；
- 写操作具备权限、预览、确认、Task 和审计；
- 页面刷新、关闭和恢复不丢失任务状态；
- 重复启动、停止不会生成重复 Task 或 Session；
- 性能不明显慢于 Qt，长任务不阻塞 WebHost；
- 凭据、Token、路径和原始文件不泄露；
- Fake 与真实场景验收均按模块要求通过；
- Qt 旧入口回归正常，并具有一个发布周期的回退方案。

达到门槛后的固定动作是：先将 Web 设为默认入口，再隐藏 Qt 页面；稳定一个发布周期后才允许删除旧页面。

## 明确冻结项

SNMP 中心和无线勘测当前只保留历史代码与数据：

- 不进入 Web 导航；
- 不为它们新增 Qt、Vue 或 Electron 功能；
- Feature Registry 保持禁用；
- 不在本轮迁移中做兼容层或功能补齐；
- 未来若重启，状态从 `FUTURE_REBUILD` 重新立项，不复用旧页面作为目标架构。
