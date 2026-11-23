# NetConsole v1.5.18 设备管理遗漏整合报告

日期：2026-11-23

## 1. 调查结论

设备管理改造没有进入 v1.5.18 的原因不是合并冲突或发布分支回退，而是改造始终停留在旧分支工作树的未提交状态：

- 来源分支：`codex-A/console-r2-independent-terminal-netmiko`
- 来源 Worktree：`D:\study\NetConsole-Workspace\NetConsole`
- 来源分支 HEAD：`aa0a7c0a146432f6786149afb816488c62463d15`
- v1.5.18 审计基线：`9e463778f0ece54fb16cb31c877da86ff8bce438`
- 本轮集成基线：`main@b486b83fb3a90788caae0657efb6b4784b0b8584`
- 产品整合 Commit：`5b39c89b`

来源 Worktree 同时包含 Console、SFTP、导航、系统设置、Syslog 调查证据等其他未提交内容。审计发现 49 个 dirty 状态文件已与当前 main 字节一致，另有 37 个跟踪文件确有差异、92 个文件在 main 不存在。因此没有整体提交、整体 Cherry-pick 或整体合并该工作树，而是从最新 main 新建干净 Worktree 后仅迁移设备管理纵向链。

来源 Worktree 与 `artifacts/device-management-refactor/` 证据保持原状，没有移动、删除或混入本次产品提交。

## 2. 功能差异矩阵

| 功能 | 整合前 v1.5.18 | 来源 Worktree | 最终处理 |
| --- | --- | --- | --- |
| 设备分类 | 只有厂商和历史业务角色 | SmartHub 厂商/大类/子类中央目录与角色投影 | 已整合，无 schema 变更 |
| 设备新增/编辑 | 既有 CRUD 与凭据边界 | 厂商 -> 大类 -> 子类级联、角色一致性校验和编辑回显 | 已整合，既有 CRUD 保留 |
| 设备删除 | 已有确认令牌和批量删除 | 无必要新契约 | 保留 main 实现 |
| 连接测试 | 已有 SSH/Telnet 测试与结构化状态 | 新增只读健康检查，复用 inventory Profile | 已整合；连接测试语义不变 |
| Site/分组关联 | 已有 Site 隔离、分组和移动 | 分组设备数、全站与未分组总数 | 已整合，计数不受当前分页影响 |
| 凭据管理 | 已有引用、保存与 DPAPI 边界 | 分类改造不改变秘密字段 | 保留 main 实现，无秘密进入 DTO/日志 |
| 设备筛选分页 | 已有服务端分页及多条件筛选 | 分类筛选、导出/SecureCRT 同范围传播 | 已整合，分类投影在分页前应用 |
| 设备详情 | 已有详情、接口、光模块和 LLDP | 列表显示已保存型号事实、健康检查结果 | 已整合，不从名称或地址推断型号 |

## 3. 实际整合范围

产品提交共修改 25 个文件，新增 2 个生产文件和 1 个测试文件，净变化为 2340 行新增、85 行删除。

主要能力：

1. `device_classification.py` 成为厂商、产品大类、设备子类、业务角色投影和写入校验的中央事实源。
2. FastAPI DTO、Router、Application Service、Repository、Renderer API/Store/类型和设备页面形成完整分类闭环。
3. 分类筛选进入设备列表、CSV、SecureCRT 和连接状态范围；旧 CSV 模板继续兼容。
4. 分组树增加当前 Site 的组内、全部和未分组计数；设备型号只读取已保存事实快照。
5. 健康检查通过 Job Center 调用既有 `device.inventory.collect` 只读 Profile，未知能力返回 `NOT_SUPPORTED`，不新增命令。
6. canonical 与 runtime changelog 同步补录 v1.5.18 设备管理变化。

明确排除：

- AC 配置写与 SFTP 启用的 `device_write_resource_key` 串行化修改；该改动无设备分类/健康检查依赖，属于另一业务改造。
- Electron Main/Preload、Console/SFTP、命令参考导航、配置采集导航、Dashboard、系统维护和系统设置修改。
- Syslog、MR、SQL 调查截图、Console/SFTP 证据和其他任务报告。

## 4. 数据与兼容性

```text
DATABASE_SCHEMA_CHANGED=0
DATABASE_MIGRATION_ADDED=0
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

分类字段是从既有 `device_vendor` 与 `device_type` 得到的只读投影；可写分类最终仍保存为既有业务角色。设备 UUID、Site、分组、凭据、DPAPI、连接参数、Profile 和历史设备数据格式不变。

## 5. 验证结果

| 范围 | 结果 |
| --- | --- |
| 设备分类/API/导入导出/工作范围定向 Python | PASS，166 passed |
| Ruff / `py_compile` | PASS |
| Renderer 设备页与导出协调器定向测试 | PASS，4 files / 65 tests |
| Renderer 全量 | PASS，219 files / 1593 tests |
| Renderer TypeScript / Production Build | PASS |
| Electron 全量 | PASS，41 files / 324 tests |
| Electron typecheck / Main+Preload build | PASS |
| Electron 隔离 `smoke:dev` | PASS，真实 Electron、Renderer、Backend 启停与回收 |
| Python 全量 | PASS，5738 passed / 2 skipped / 35 warnings |
| 架构 Guard | PASS，12/12 |
| 主线 contract smoke | PASS，12 passed |
| changelog 与项目文档路径 | PASS，17 passed |
| `git diff --check` | PASS |

自动化验证不替代真实设备、真实凭据、正式安装包或现场数据验收。本轮未执行 Installer/Portable GUI 验收、Authenticode 或真实设备命令验证。

## 6. 发布与制品边界

源码版本仍为 `v1.5.18`，没有升级版本号。现有正式 Installer/Portable 由 `f842d7ed1601158b4cc783ad4a0e526d02d0462c` 构建，不包含本次 `5b39c89b` 设备管理整合；本轮按任务边界不重新打包，因此不能声称已安装客户端自动获得新功能。

本报告记录源码整合和自动化验证。最终 main 快进、远端同步、本地分支/Worktree 回收及空间释放结果以任务最终交付记录为准。
