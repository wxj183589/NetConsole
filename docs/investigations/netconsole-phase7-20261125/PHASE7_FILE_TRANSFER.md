# Phase 7 文件管理与网络服务联动

日期为 2026-11-25。实施基线为 `7b8e82f1`，工作分支为 `codex-A/organization-task-network-services-phase6`。

## 交付范围

本项自动化验证为 PASS。真实 Electron 文件选择、另存及设备 SFTP 验收由阶段集成验收记录，当前文件联动整体状态为 PARTIAL。

原有双面板设备文件管理、SFTP 传输队列、同步预览和远程文本编辑继续由现有入口承载。文件管理增加“本地与服务目录”范围，两个面板可分别选择当前局点 Downloads、TFTP、FTP、HTTP 或 HTTPS 根目录。

| 能力 | 实现与验证 |
| --- | --- |
| 浏览 | 服务初始化状态校验，普通文件与目录、大小、权限、父目录导航，单目录上限 1000 项 |
| 复制 | 独占 `.part`、分块复制、SHA-256 复核、源大小及时间戳复核、同名保护 |
| 移动与重命名 | 普通文件复制校验后再删除源文件，目录使用受控 rename |
| 删除 | 普通文件必须先校验并二次确认，后台复核期望 SHA-256，目录仅允许 rmdir 删除空目录 |
| 上传 | 用户当次 File/FileList，服务专属 staging，任务完成或失败后清除 staging 文件及引用 |
| 下载 | 固定 opaque 文件引用端点，用户显式点击后通过 Native Bridge 当次 Save As |
| 覆盖 | 复制及移动遇同名目标先校验，再由用户确认，后台提交前重新复核目标 SHA-256 |
| 任务 | 两个文件操作线程，最多 20 个待执行或运行任务，页面最多保留 100 条内存记录 |
| 进度与取消 | 分块操作进度、失败原因、页面取消与 Task Center cancel 文件信号 |
| 历史 | Task Center external task 记录持久化，状态、结果 SHA-256、事件与任务 ID 关联 |

## 权限与路径边界

本地维护允许写入已初始化且停止的服务根目录。运行中的服务根目录可浏览与下载，写入操作要求先停止服务。执行期间持有对应服务 runtime lock，阻止服务在目录变更中途启动。Downloads 文件操作使用独立互斥锁。

每个 opaque 引用限定当前局点、固定根类型和安全相对路径。重复浏览保持引用稳定，以便校验完成后继续确认覆盖。引用上限为 20000，达到上限会明确报错。

路径逐级检查 Symlink、Junction 和其他 Reparse Point。禁止根目录自身的删除、移动及校验操作，拒绝越界名称，隐藏临时 `.part` 文件。复制目标提交前重新检查父目录与已有目标。后台仅接受现有根目录对应的 opaque 引用，Renderer 不提交任意本地绝对路径。

写操作 API 受 `capability.file_management.local_write` 控制。Electron 下载白名单精确接受 `/api/file-management/workspace/files/{32位小写十六进制引用}`，拒绝额外路径和 query 字段。用户文件交互契约和静态审计已补充该已有文件另存入口。

## 定向验证

Python 在仓库根运行，使用主仓库虚拟环境与 `PYTHONPATH=src`。

```powershell
& D:/study/NetConsole-Workspace/NetConsole/.venv/Scripts/python.exe -m pytest -q tests/test_file_workspace_operations.py tests/test_file_management_service.py tests/test_file_management_page.py --basetemp D:/study/NetConsole-Workspace/test-data/NetConsole/phase7-file-operations-task-history
```

结果为 **47 passed**，包含三条现有 Starlette 弃用警告。新增回归覆盖路径名称、跨局点引用、非空目录删除保护、同名覆盖、取消、上传清理、稳定引用、API 上传下载及功能门禁、真实 Task Center 重建后读取持久历史。

真实 HTTP 集成通过 `LocalNetworkServiceManager` 配置和启动独立 HTTP 服务进程。文件先经文件操作任务复制进入 HTTP 根，再通过 loopback HTTP 请求读取并核对内容。服务运行时重命名被拒绝，停止后可移动回 Downloads。测试结束关闭服务进程。

Renderer 在 `apps/desktop_renderer` 运行以下命令。

```powershell
pnpm exec vitest run src/views/file-management/FileWorkspacePanel.test.ts src/views/file-management/FileManagerWorkspaceView.test.ts src/views/file-management/FileManagementView.test.ts src/views/file-management/FileManagementView.delivery.test.ts src/platform/exportEntryAudit.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json
```

结果为 **22 passed**，typecheck 为 PASS。覆盖 opaque 引用复制、仅点击后另存、根目录切换、运行根禁写、取消文件选择无上传、组件卸载停止轮询及原有设备文件管理回归。

Electron 在 `apps/desktop_electron` 运行以下命令。

```powershell
pnpm exec vitest run tests/security.test.ts tests/backend-download.test.ts
pnpm run typecheck
```

结果为 **36 passed**，typecheck 为 PASS。涵盖固定下载端点、路径及 query 拒绝，与既有 Main 下载、取消和文件完整性验证回归。

修改范围 Ruff 为 PASS，Git diff 空白检查为 PASS。

## 待验收及限制

- 本文件记录的浏览器组件测试与 loopback 服务验证尚待真实 Electron 文件操作视觉和 Native Save As 验收补充。
- 本地服务根操作历史通过 Task Center 持久化。文件面板最近任务列表属于后端进程内存，重启后从 Task Center 查看持久历史。
- 普通文件复制支持分块校验。目录复制要求进入目录后选择文件，目录移动仅支持操作系统 rename 能完成的路径。
- 用户文件上传先接收至 staging，再由后台队列复制。页面展示后台复制进度，上传请求接收阶段尚无独立字节进度。
- 上传同名文件默认报错，UI 的校验后二次确认覆盖流程适用于面板间复制和移动。上传 API 支持传入期望 SHA-256 的确认覆盖。
- 服务运行期间的本地写入保持停止状态门禁。真实设备 SFTP、长时间大文件和离线安装态验收结果见阶段总报告。

## 数据影响

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
DEVICE_CONFIG_WRITES=0
```

所有测试数据位于 Workspace 指定隔离运行根。产品提交、Push 和 DevStatus 更新由阶段主任务统一执行。

## 128 MiB 真实大文件集成补验

在 Workspace 隔离根 `test-data/NetConsole/phase7-large-file-20261125` 创建 134217728 字节确定性 fixture，经正常文件复制任务提交至受管 HTTP 根。复制和 SHA-256 复核耗时 0.285 秒，校验值为 `a626d17da2e502f5b4b8e3ebd23f0bf9daef6255688d8e0bb482b3ae3794a682`。

随后启动真实受管 HTTP 子进程，四个并发客户端合计读取 536870912 字节，逐个复核长度与 SHA-256，耗时 0.394 秒，结果为 PASS。该耗时来自本机 loopback 与文件缓存环境。

取消用例在实际复制到 4194304 字节后，通过测试同步事件暂停至安全检查点，再调用正常 cancel 接口并继续 worker，最终状态为 CANCELLED，目标文件及 `.part` 残留均为零。服务完成受控停止后，精确删除本次生成的两个 128 MiB fixture。

机器可读结果位于 `D:/study/NetConsole-Workspace/reports/tests/phase7-large-file-20261125/result.json`。真实生产数据与真实开发数据修改计数均为零。
