# 历史残留审计（2026-07-25）

## 范围与方法

本次仅做只读审计，范围包括 2 个 Git stash、1 个 WIP tag 和 `refs/codex/snapshots/*`。snapshot 按对象 ID 去重后逐项检查祖先关系、稳定 patch-id、提交路径和当前主线替代入口；未恢复、删除或改写任何引用。

判定使用四种结论：`建议移植`、`已被主线替代`、`建议弃用`、`等待人工确认`。历史代码不会因为“未合入”而自动恢复。

## Stash 与 WIP

| 引用 | 结论 | 依据 |
| --- | --- | --- |
| `stash@{0}` `wip: non-traffic pending changes before phase 4C` | 建议弃用 | 使用旧根目录 `agent/`、`netconsole/`、`frontend/`、`project/`，与当前 `apps/agent`、`src/netconsole`、`apps/web` 架构不一致；包含旧 Agent 配置和目标密码字段，不能整体恢复。 |
| `stash@{1}` `temp-netconsole-zip-deletion-before-main-push` | 建议弃用 | 仅删除旧根 `netconsole.zip` 构建产物，当前发布链路使用 `dist/`，无功能入口。 |
| `wip/b787-architecture-before-5b4a-split` | 已被主线替代 | 旧分层文档和 `local_process_adapter` 约束已由当前 `docs/DEVELOPMENT_RULES.md`、`scripts/architecture`、`src/netconsole/services/job_center/` 及对应测试承接。 |

## Snapshot refs

下表按 snapshot 对象去重；同一对象的多个 `refs/codex/snapshots/*` 引用共享同一结论。祖先提交或稳定 patch-id 命中主线的内容标记为“已被主线替代”。

| 对象（短 ID） | 引用数 | 主题 | 结论 | 当前依据 |
| --- | ---: | --- | --- | --- |
| `08c47ca4` | 2 | Qt 开发功能只读语义 | 建议弃用 | 依赖已退出活动架构的 Qt 开发功能；当前由 `feature_registry.py`/`feature_flags.py` 的 Electron-only 规则负责。 |
| `08ecdb29` | 1 | Online MR 状态与实时窗口 | 已被主线替代 | 当前 Online MR Application/API/Vue 链路及后续在线 MR 提交已覆盖。 |
| `11c62e13` | 1 | Web 文件管理 | 已被主线替代 | 当前 `apps/web/src/views/file-management/`、`file_management_service.py` 和下载任务恢复链路已接管。 |
| `30217947` | 1 | 设置原子保存与功能开关 | 已被主线替代 | 稳定 patch-id 命中主线 `d0f66aab`。 |
| `341b1baa` | 1 | MESH 图表偏好 | 已被主线替代 | 稳定 patch-id 命中主线 `60cfd3e1`。 |
| `3d3b39f0` | 1 | Web 对等收尾文档 | 已被主线替代 | 已是 `main` 祖先提交。 |
| `57ecad8c` | 1 | 网络工具 Web 功能 | 已被主线替代 | 稳定 patch-id 命中主线 `267d5a1b`，后续由网络工具轮询/游标提交继续修正。 |
| `5af7253c` | 2 | 应用日志与安全维护 | 已被主线替代 | 当前对应主线 `076a3d44` 及系统维护 Application/API。 |
| `5ce647fd` | 1 | 配置快照选择与删除回滚 | 已被主线替代 | 当前对应 `da939783`、配置采集中心和受控删除回滚测试。 |
| `6e80ebc5` | 1 | MESH 链路明细导出 | 已被主线替代 | 稳定 patch-id 命中主线 `c3568494`。 |
| `76d1ad71` | 1 | 配置采集测试补丁 | 已被主线替代 | 当前配置采集 API、任务恢复和测试基线已覆盖该行为。 |
| `901e2529` | 5 | Qt 模块窗口生命周期测试 | 已被主线替代 | 已是 `main` 祖先提交，且 Qt 活动入口已删除。 |
| `938cc784` | 1 | Web 设备管理 | 已被主线替代 | 当前设备管理由 `device_management_web_service.py`、Router、Vue 和后续真实操作闭环承接。 |
| `97011354` | 2 | 文件管理双栏与恢复 | 已被主线替代 | 当前对应 `34d7120b` 及文件管理下载队列恢复实现。 |
| `9ae81833` | 1 | 命令参考取消收敛 | 已被主线替代 | 当前对应命令参考任务取消/终态收敛提交。 |
| `ce96e3a2` | 1 | 统一任务窗口终态与文件安全 | 已被主线替代 | 已是 `main` 祖先提交。 |
| `e20f6e54` | 1 | 首批双轨迁移模块 | 已被主线替代 | 已是 `main` 祖先提交，当前迁移矩阵和 Electron-only 入口已收口。 |
| `e8178f9f` | 1 | FIT-AP 详情保存与历史查询 | 已被主线替代 | 当前对应 `73d2a164` 及 AC/FIT-AP 受控服务。 |
| `e830d05c` | 1 | 移除任务秘密与统一任务交互 | 已被主线替代 | 当前对应 `7246c9d8`，敏感 Bootstrap 与任务摘要规则已进入主线。 |
| `ebbe9160` | 1 | MESH 综合分析报告 | 已被主线替代 | 稳定 patch-id 命中主线 `681d011e`。 |
| `ee88fd01` | 1 | AC 命令参考测试基线 | 已被主线替代 | 已是 `main` 祖先提交。 |
| `f0062538` | 1 | 持续探测实时结果窗口 | 已被主线替代 | 稳定 patch-id 命中主线 `2c440033`。 |

## 安全结论

- `stash@{0}` 的旧 Agent 配置/目标文件和 `D:\NetConsoleData\agents\legacy-localappdata-agent/` 中存在非空敏感字段；本报告不记录字段值。
- 凭据轮换仍未完成，因此不能执行 stash、WIP 或 snapshot 引用删除，也不能执行 reflog 过期和不可达对象 GC。
- 本次未发现“建议移植”的唯一有效补丁；也没有需要阻塞主线的“等待人工确认”项。
- 后续顺序：先轮换 Agent token、Web 密码和设备密码，再复核这些结论，之后由人工批准引用清理。
