---
name: netconsole-export-report-skill
description: "NetConsole Export Center、ExportJob、XLSX/CSV/PDF/ZIP/Markdown 报告、Excel 列宽样式、WPS/Excel 文件占用、临时文件、原子替换、导出进度或取消任务时使用。实时采集、普通表格 UI 样式或不生成文件的数据分析不使用本 Skill。"
---

# 目标

新增或修复独立 Export Process 报告链，保证 UI 不阻塞、文件可恢复、中文和 WPS/Excel 本地打开体验稳定。

# 触发与反例

触发示例：

- “导出 Excel 时 UI 卡死，取消后还留下 tmp。”
- “新增一个带阶段进度的后台报告。”
- “导出的中文列宽、冻结和 WPS 文件占用提示不正确。”

不应触发：

- “修改实时 MR 采集。”
- “只调整 Vue 表格的列宽或做不落文件的数据分析。”

# 输入与输出

- 输入：数据源、筛选/ID、目标格式/路径、字段和样式、规模、进度与取消要求。
- 输出：ExportJob/spec/handler/report 修改、原子文件策略、格式验证和 UI 终态反馈。
- 允许修改生产代码：允许，限 Export Process、报告服务、UI 提交 helper 和测试；不得在 UI 线程新增直接导出。

# 开始前读取

- `docs/export_process_policy.md`、`docs/IMPORT_EXPORT_INTERACTION.md`、`docs/JOB_CENTER.md`、`docs/DEVELOPMENT_RULES.md`。
- `apps/web/src/platform/exportActionRegistry.ts`、`apps/web/src/composables/useUserSelectedExport.ts`。
- `src/netconsole/export_worker.py`、`src/netconsole/services/export/`、`src/netconsole/services/export_task_models.py`。
- `src/netconsole/services/excel_autosize.py`、`src/netconsole/services/excel_report_utils.py`、`src/netconsole/services/excel_stream_exporter.py`。
- 目标报告 Service、对应 FastAPI Router/Vue 下载入口、`src/netconsole/utils/excel_workbook.py`。
- `tests/test_export_process_framework.py` 和目标报告测试。

# 工作流程

1. 涉及用户可见任务型导出时，组合 `netconsole-user-file-interaction-skill`：先登记固定动作并复用 `submitExportAfterDestinationSelected(...)`，不得在目标页面自行调用 `chooseSavePath` 后复制保存状态机。
2. Vue 只提交受控导出 DTO；Application Service 构造 `ExportTaskSpec`/`ExportJob` 并调用 `submit_export_task()`。Renderer/Router 不得直接 `Workbook.save()`、`to_excel()` 或 `savefig()`，也不得把用户最终路径作为任意 Renderer 参数写入 Python `ExportJob`。
3. Worker 的 `output_path` 是内部 Artifact 路径；最终用户副本由共享协调器携带 Main 授权路径、大小和 SHA-256，交给 Electron Main 保存。
4. 优先传数据库/结果文件/筛选/ID等数据源；不得遍历全量 UI 表格传入 Worker。仅符合现有 builder 限制的小型静态 inline rows 可例外并说明原因。
5. Worker 写内部目标旁临时文件；成功后 `os.replace` 原子替换，失败/取消/启动异常清理 tmp、Job 和 cancel 文件。
6. handler 分阶段报告查询、生成、样式、落盘；UI 显示进度、失败原因和取消结果，最终保存状态由共享协调器和 Task Center 管理。
7. XLSX 统一表头、冻结、筛选、文本/数值/时间/百分比/状态格式和采样列宽上限；不产生用户未要求的重复列。
8. 文件被 WPS/Excel 占用时提示关闭文件后重试，不覆盖已有可用文件。

# 项目约束

- 本 Skill 只覆盖本地文件导出；默认不引入 WPS 云服务、WPS API、KDocs 或在线同步。
- 自动列宽不得全量扫描到 UI 或 Worker 不可控；大数据使用采样、流式或现有 autosize helper。
- 诊断和错误不得泄露 community、密码、私有地址或完整 Identity 样本。
- 报告字段从结构化数据/Repository 获取，不以当前可见表格为真源。

# 验证与失败报告

- 验证空数据、中文、列宽、冻结、筛选、关键行值、多个 Sheet、文件占用、取消、异常和 tmp 清理。
- XLSX golden 比较结构/字段/样式，不依赖二进制哈希；无法实际用 WPS/Excel 打开时明确说明只做 openpyxl 结构验证。
- 输出修改文件、job_type、数据源、临时/原子策略、UI 线程影响和兼容性风险。

# 相关 Skills

- 用户文件选择、任务绑定和最终落盘：`netconsole-user-file-interaction-skill`。
- Job 协议：`netconsole-job-center-skill`。
- 数据目录安全：`netconsole-data-safety-skill`。
- MESH 报告：`netconsole-mesh-analysis-skill`。
