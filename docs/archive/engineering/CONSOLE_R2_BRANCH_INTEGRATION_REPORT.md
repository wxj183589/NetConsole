# NetConsole v1.5.18 Console R2 分支遗漏功能整合报告

日期：2026-11-24

## 1. 集成基线

- 来源分支：`codex-A/console-r2-independent-terminal-netmiko@aa0a7c0a`
- 集成分支：`codex-A/console-r2-full-integration-20261124`
- 集成基线：`main@970677235801b66267f46395b4f3e8c2a57900ac`
- 目标版本：`v1.5.18`
- Change Impact：路径登记结果为 L2；因设备写锁跨越 AC 配置写和 SFTP 启用两个 Consumer，按语义提升为 L3 执行完整回归。

没有整体合并 dirty Worktree，也没有整体 Cherry-pick 混合提交。本轮只迁移完整审计确认的三项有效缺口，并保留 main 中更新的 Console、SFTP、Netmiko、设备管理和其他业务实现。

## 2. 实际整合内容

### 2.1 独立导航

- 配置采集中心从设备文件下载子菜单提升为独立顶级导航，Route、Feature Gate 和页面实现保持不变。
- 命令参考从日志中心 Tab 恢复为独立页面和导航入口。
- 历史 `/logs?tab=command-reference` 自动重定向到 `/command-reference`，移除旧 `tab` 参数并保留其他 query/hash。
- Dashboard、导航注册表、路由和国际化回归测试同步更新。

### 2.2 设备自动化写互斥

- AC 配置写任务继续使用原 `ac_config_write` 资源键，并追加设备级 `device_write_resource_key`。
- `device.sftp.enable` 任务使用相同设备级写资源键，防止与 AC 配置写在同一设备并发。
- 只约束自动化写任务；人工 SSH/Telnet 会话、SFTP 文件传输连接、Netmiko 采集/读取生命周期不重新耦合。

### 2.3 变更记录

- `docs/CHANGELOG.md` 与 `src/netconsole/docs/changelog.md` 同步补录 v1.5.18 分支遗漏收口。
- 产品版本保持 `1.5.18`，不新增 Schema、Migration、设备命令或凭据字段。

## 3. 修改范围

产品与测试初始集成为 12 个文件、86 行新增、20 行删除；另新增两份工程报告并同步两份 changelog。最终文件统计以产品 Commit 为准。

主要产品文件：

- `apps/desktop_renderer/src/navigation/registry.ts`
- `apps/desktop_renderer/src/router/index.ts`
- `apps/desktop_renderer/src/router/routes.ts`
- `apps/desktop_renderer/src/views/system/SystemMaintenanceView.vue`
- `src/netconsole/application/ac/web_application_service.py`
- `src/netconsole/services/device_operation_service.py`

主要测试文件：

- `apps/desktop_renderer/src/navigation/registry.test.ts`
- `apps/desktop_renderer/src/router/index.test.ts`
- `apps/desktop_renderer/src/views/DashboardView.test.ts`
- `tests/test_ac_application_job_contract.py`
- `tests/test_device_sftp_operation.py`

## 4. 自动化验证

| 范围 | 结果 |
| --- | --- |
| Python 定向：AC Job Contract / Device SFTP | PASS，18 passed |
| Python 全量 | PASS，5738 passed / 2 skipped / 35 warnings |
| Ruff 全量 | PASS，`All checks passed!` |
| Python `compileall -q src tests scripts` | PASS |
| Renderer 全量 | PASS，219 files / 1596 tests |
| Renderer TypeScript | PASS |
| Renderer Production Build | PASS；仅保留既有大 Chunk 警告 |
| Electron 全量 | PASS，41 files / 324 tests |
| Electron TypeScript / Main Build | PASS |
| Electron `smoke:dev` | PASS；隔离数据根启动并正常回收 Backend、Vite、Electron |
| Architecture Guard | PASS，12/12 |
| Main Contract Smoke | PASS，12 passed；3 个既有 Starlette deprecation warnings |
| Workspace Layout | PASS，`WORKSPACE_SCOPE=REPOSITORY_ONLY` |
| `git diff --check` | PASS |

自动化通过不代表真实设备、真实凭据、Windows 安装包、长时运行或现场业务验收通过。本轮未重新执行 Installer/Portable GUI、Authenticode 或 H3C 现场兼容验收。

## 5. 回归结论

| 业务域 | 结论 |
| --- | --- |
| 设备管理 CRUD、分类、筛选、Site Scope | 保留 `5b39c89b` 实现；全量测试覆盖，无本轮 Schema 变更 |
| SSH/Telnet、多会话、分屏、状态保持 | 保留 main 现有实现；Renderer/Electron 全量通过 |
| SFTP 上传下载与传输队列 | 产品实现未替换；仅 `device.sftp.enable` 增加写锁 |
| Netmiko 自动化 | 连接和采集职责不变；AC 写任务加入跨 Consumer 设备锁 |
| 设备文件下载 | 未修改；全量回归通过 |
| Syslog/MR、Heartbeat、任务中心 | 未修改；Python/Renderer/Electron/架构门禁覆盖 |

## 6. 数据与发布边界

```text
DATABASE_SCHEMA_CHANGED=0
DATABASE_MIGRATION_ADDED=0
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
INSTALLER_PORTABLE_REBUILT=0
```

正式安装包仍对应历史构建 Commit，不包含本轮尚未提交的源码整合；只有重新构建和完成相应验收后，才能声明客户端包含这些变化。

## 7. 集成状态

```text
DEVICE_MANAGEMENT=PASS
CONSOLE_INTEGRATION=PASS
SFTP_INTEGRATION=PASS
NETMIKO_INTEGRATION=PASS
```

`MAIN_MERGE` 和 `REMOTE_SYNC` 在产品 Commit、main 快进及远端安全推送后记录。
