---
name: netconsole-user-file-interaction-skill
description: "NetConsole 用户可见导入、导出、模板下载、报告保存、Artifact 另存、Save As/Open/File/Folder 选择或 Task Center 保存失败重试任务时使用。报告字段/Excel 样式、Export Worker 内部生成、SFTP 受管下载实现、数据库业务或不落文件的数据分析不使用本 Skill。"
---

# 目标

统一用户文件选择、任务绑定和最终落盘行为，复用现有共享协调器与 Electron Main 授权路径，不在业务页面建立第二套状态机。

# 输入与输出

- 输入：用户动作类型、文件来源、目标格式、现有任务/Artifact、运行宿主和业务例外。
- 输出：最小接入修改、固定动作登记、用户取消/保存/重试行为及验证结果。
- 允许修改生产代码：允许，限现有 Renderer 协调器、注册表、Electron 白名单文件选择/保存入口及对应测试；不得借此修改报告字段、Worker 生成逻辑、SFTP 受管下载或数据库 schema。

# 开始前读取

- `docs/IMPORT_EXPORT_INTERACTION.md`
- `docs/development/import-export-dialog-audit.md`
- `apps/web/src/composables/useUserSelectedExport.ts`
- `apps/web/src/platform/exportActionRegistry.ts`
- `apps/web/src/platform/runtime.ts`
- `apps/web/src/platform/types.ts`
- `apps/desktop_electron/src/main/backend-download.ts`
- `apps/desktop_electron/src/main/ipc.ts`
- 目标导入/导出入口及其现有测试、`apps/web/src/platform/exportEntryAudit.test.ts` 和 `apps/web/src/composables/useUserSelectedExport.test.ts`

# 工作流程

1. 先分类为任务型导出、已有 Artifact、专用包流程、导入或受管下载；确认文件是用户最终副本还是内部/受管文件。
2. 任务型导出先在 `exportActionRegistry.ts` 登记稳定动作，再调用 `submitExportAfterDestinationSelected(...)`；用户取消时不得提交任务。
3. 复用 `useUserSelectedExport.ts` 完成任务与授权路径绑定、Artifact 校验、最终保存和失败换路径；不得在页面私建 session storage、轮询器、自动保存 watcher 或重试状态机。
4. 已有 Artifact/现成文件只在用户点击时调用 `downloadBackendResource(...)`，不传 `destinationPath`；页面加载、Tab 恢复和历史任务恢复不得自动弹窗。
5. Browser File/FileList 导入在取消时不预检，处理后清空 input；Electron 路径导入只使用 Main 返回的授权路径，且保留 Backend 文件契约校验。
6. OmniPeek、局点包和 SFTP 等专用流程只按已登记边界处理。新增例外必须同步永久规范、审计矩阵和静态审计测试，并说明技术原因。
7. 验证取消、成功保存、完整性参数、保存失败复用 Artifact、历史 Artifact 手工另存、同名文件重选及 Browser/Electron 边界。

# 项目约束

- 用户最终路径只由 Electron Main 当次授权，不进入 Python `ExportJob` 或业务数据库；Worker 的 `output_path` 是内部 Artifact 路径。
- 正式 Electron 缺少 Native Bridge 时直接失败，不得回退 `anchor.download`；Browser 只能报告 `started`。
- Renderer 不直接 `fs/writeFile/Workbook.save/to_excel/savefig`，不使用 Downloads、Documents、Desktop、数据根、`cwd` 或测试目录作为最终默认路径。
- 新任务型报告通常同时加载 `netconsole-export-report-skill`：本 Skill 负责用户选择和最终落盘，报告 Skill 负责 Export Process、格式和内部 Artifact。

# 验证与失败报告

- 运行目标页面行为测试、`exportEntryAudit`、`useUserSelectedExport` 和相关 Task Center Artifact 测试。
- 检查新增任务动作已登记，普通页面没有私有导出状态机、Renderer 下载回退或默认最终路径。
- 无法覆盖 Electron 原生对话框或真实文件落盘时，明确说明未验证边界，不把 Browser `started` 当作保存成功。
- 输出分类结论、复用入口、例外依据、修改文件、测试结果，以及是否影响 Worker、Backend 或数据库。

# 相关 Skills

- 报告字段、格式、内部 Artifact 与 Export Process：`netconsole-export-report-skill`。
- SFTP 受管下载实现：`netconsole-device-files-skill`。
- 局点包和数据目录安全：`netconsole-data-safety-skill`。
