# NetConsole v1.5.18 Console R2 分支完整审计

日期：2026-11-24

## 1. 审计对象与结论

主要审计对象：

- 分支：`codex-A/console-r2-independent-terminal-netmiko`
- Worktree：`D:\study\NetConsole-Workspace\NetConsole`
- 分支 HEAD：`aa0a7c0a146432f6786149afb816488c62463d15`
- 设备管理整合：`5b39c89b`
- 当前审计基线：`main@970677235801b66267f46395b4f3e8c2a57900ac`
- v1.5.18 发布基线：`f842d7ed1601158b4cc783ad4a0e526d02d0462c`

审计确认：`aa0a7c0a`、`9226b2c0`、`5b39c89b`、`f842d7ed` 和历史线索 `9e463778` 均为当前 `main` 的祖先；`git log main..codex-A/console-r2-independent-terminal-netmiko` 为空，因此目标分支不存在尚未进入 main 的独有已提交 Commit。遗漏风险全部来自来源 Worktree 的未提交修改、未跟踪文件和工程证据，不能仅依据提交差异判断。

来源 Worktree 在审计时包含 64 个已跟踪修改和 114 个未跟踪文件，共 178 个实际文件；Stash 为空。来源 Worktree 在归档完成前保持原状。

## 2. 文件级分类

| 分类 | 数量 | 处理 |
| --- | ---: | --- |
| 已跟踪且与 main 字节一致 | 51 | 已通过其他 Commit 进入 main，不重复迁移 |
| 已跟踪且与 main 不同 | 13 | 逐文件审查；3 项有效产品改造进入本轮集成，其余为旧实现、测试桩或文档回退 |
| 未跟踪且与 main 字节一致 | 20 | 已进入 main，不重复迁移 |
| 未跟踪且同路径 main 文件不同 | 5 | 均为 `9226b2c0` 前的中间版本，由 main 新实现替代 |
| 未跟踪且 main 无同路径文件 | 89 | 报告、截图、日志、SQL 审计和验收证据；回收前完整归档并校验 SHA-256 |

五个被 main 新实现替代的未跟踪产品文件：

- `apps/desktop_renderer/src/components/console/ConsoleCommandBar.test.ts`
- `apps/desktop_renderer/src/components/console/ConsoleCommandBar.vue`
- `apps/desktop_electron/scripts/capture-console-sftp-electron.mjs`
- `scripts/acceptance/console_sftp_fixture.py`
- `tests/test_terminal_live_recording.py`

明确不迁移：

- `apps/desktop_renderer/src/views/devices/README.md`：来源内容声称健康检查未实现，与 `5b39c89b` 后的当前事实冲突，迁移会造成文档回退。
- `apps/desktop_renderer/src/views/settings/SystemSettingsView.test.ts`：仅补充旧测试桩，当前 main 已由新的测试和实现覆盖。
- 其余同内容文件、旧版本 Console 命令栏和验收脚本：不覆盖 main 的更新实现。

## 3. 功能差异矩阵

| 功能域 | 分支已有实现 | main 已有实现 | 缺失内容 | 最终处理 |
| --- | --- | --- | --- | --- |
| 设备管理 | 分类、CRUD、Site/分组、凭据、筛选分页、详情、健康检查相关 dirty 链路 | `5b39c89b` 已形成 Backend/API/Renderer/Test 完整闭环；`97067723` 已记录整合结果 | 无 | 已整合，不重复迁移 |
| 交互式控制台 | `aa0a7c0a` 的 SSH/Telnet 独立会话边界及后续 dirty 证据 | `aa0a7c0a` 与 `9226b2c0` 已包含独立终端、新窗口、重连、状态保持、录制、快捷按钮和批量发送 | 无有效产品缺口 | 保留 main |
| 多会话及分屏 | 同设备多 Session、多标签、分屏、跨页面恢复 | `aa0a7c0a`、`9226b2c0` 已进入 main，并有 Renderer/Electron 回归 | 无 | 已进入 main |
| SFTP | 独立连接、目录操作、传输队列、上传下载、取消重试、续传校验及证据 | `aa0a7c0a`、`9226b2c0` 已进入 main；五个旧未跟踪文件被新实现替代 | 仅设备写操作互斥未闭环 | 本轮只为 `device.sftp.enable` 增加共享设备写锁，不改变文件传输连接职责 |
| Netmiko | 自动化连接、采集、任务执行与交互式终端隔离 | `aa0a7c0a` 及后续 main 已包含隔离边界 | AC 配置写与 SFTP 启用可能在同设备并发 | 本轮引入共享设备级写资源键 |
| 文件下载 | 设备文件下载与 SFTP 生命周期兼容 | main 已有当前实现和测试 | 无 | 保留 main |
| 导航及系统设置 | 配置采集、命令参考独立入口的 dirty 修改 | main 将配置采集放在文件下载子级，命令参考嵌入日志中心 | 两个独立入口及旧 URL 兼容 | 本轮整合；旧 URL 保留 query/hash 后重定向 |
| Electron 主进程 | Console/SFTP IPC、生命周期及验收脚本 | `aa0a7c0a`、`9226b2c0` 已进入 main | 无 | 保留 main；不迁移旧验收脚本 |
| 其他改造 | Dashboard、系统维护、Syslog/MR 调查、SQL 审计、截图和工程报告 | 产品能力已在 main 或属于其他专项 | 89 个 main 不存在的证据文件需要保留 | 归档证据，不作为产品代码合并 |

## 4. 三项实际遗漏

### 4.1 配置采集中心独立导航

证据文件：

- `apps/desktop_renderer/src/navigation/registry.ts`
- `apps/desktop_renderer/src/navigation/registry.test.ts`
- `apps/desktop_renderer/src/router/routes.ts`
- `apps/desktop_renderer/src/views/DashboardView.test.ts`

处理：将 `files.config-collection` 提升为顶级导航项，保留既有 Route 和 Feature Gate，不改变配置采集业务实现。

### 4.2 命令参考独立路由

证据文件：

- `apps/desktop_renderer/src/router/index.ts`
- `apps/desktop_renderer/src/router/index.test.ts`
- `apps/desktop_renderer/src/router/routes.ts`
- `apps/desktop_renderer/src/navigation/registry.ts`
- `apps/desktop_renderer/src/views/system/SystemMaintenanceView.vue`
- `apps/desktop_renderer/src/i18n/runtime.ts`

处理：命令参考使用独立页面和导航；历史 `/logs?tab=command-reference` 由路由 Guard 转到独立页面，去除旧 `tab`，保留其他 query 和 hash。

### 4.3 设备级自动化写互斥

证据文件：

- `src/netconsole/application/ac/web_application_service.py`
- `src/netconsole/services/device_operation_service.py`
- `tests/test_ac_application_job_contract.py`
- `tests/test_device_sftp_operation.py`

处理：AC 配置写保留原专用资源键，同时增加 `device_write_resource_key(site_id, device_id)`；`device.sftp.enable` 使用同一设备级资源键。交互式 SSH/Telnet、SFTP 文件传输和 Netmiko 自动化连接仍保持独立生命周期。

## 5. 数据、版本和证据边界

```text
DATABASE_SCHEMA_CHANGED=0
DATABASE_MIGRATION_ADDED=0
PRODUCT_VERSION=v1.5.18
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

本轮不重新执行 Installer/Portable GUI 验收，不修改 DevStatus，不删除远端功能分支。现有正式制品仍由历史 Commit 构建，源码整合不等于已安装客户端自动获得新功能。

## 6. 审计状态

`BRANCH_AUDIT=PASS`：全部提交、已跟踪修改、未跟踪文件、Stash、历史文件和关联证据均已分类；来源 Worktree 的最终回收以归档清单和逐文件哈希复核为前置条件。
