# 导出进程规范

本文定义 NetConsole 所有导出类任务的强制规范，是 [Renderer 响应性规范](../ui/RESPONSIVENESS.md) 的配套文档。用户选择文件、任务绑定和最终落盘的永久规则见 [用户文件导入导出交互契约](./USER_FILE_INTERACTION.md)。

> 2026-07-11 代码核对：当前通用 registry 有 27 个导出类型，另有 `trackside_ap_business` 和 `mesh_link_detail` 两个专用类型。兼容直接 exporter 仍可能存在，但正式 UI 路径必须使用 Export Process。

核心规则：

```text
所有导出按钮都必须使用独立进程。
页面动作只能提交 ExportJob，由永久 Export Application Service/Process 启动。
Renderer 禁止直接 Workbook.save、df.to_excel、matplotlib.savefig。
```

正式 Electron 的“导出任务”和“用户最终保存”是两个连续但独立的阶段：

```text
用户点击导出
  -> useUserSelectedExport 选择并持有 Main 授权目标
  -> 用户取消：结束，不创建 Export Task
  -> 用户确认：创建 Export Task
  -> Export Process 生成内部 Artifact
  -> Task Center 发布 Artifact 元数据
  -> useUserSelectedExport 携带 destinationPath + size + SHA-256
  -> Electron Main 流式写入同目录随机 .part
  -> 校验通过后安全替换用户目标
```

用户最终导出不得默认写到业务数据根、仓库、当前工作目录、测试/构建目录或系统下载目录。Artifact Store、Worker 临时输出和 Job 描述文件仍属于受管内部数据，不要求用户逐次选择路径。

## 一、适用范围

以下导出必须使用独立进程：

```text
轨旁 AP 业务导出
MR 原始 MESH 分析报告导出
车载 MR 收集分析报告导出
AC FIT-AP 资源导出
AP 扩展信息导出
设备管理 CSV / XLSX 导出
日志中心导出
配置采集中心导出
文件清单导出
图表图片批量导出
PDF / Word 报告导出
```

禁止在 UI 线程按钮回调中直接执行：

```python
Workbook()
workbook.save()
df.to_excel()
pandas.ExcelWriter()
matplotlib.savefig()
```

## 二、运行模式

推荐进程入口：

开发环境：

```text
python -m netconsole.export_worker --job <job_file.json>
```

打包环境：

```text
NetConsole.exe --export-worker --job <job_file.json>
```

Application Service 与导出进程通过 UTF-8 JSONL stdout 通信进度。导出进程不得依赖 Vue、DOM 或 Electron 对象。

## 三、ExportJob

Application Service 只创建内部 Artifact 的导出任务描述文件，例如：

```json
{
  "job_type": "trackside_ap_export",
  "site_name": "demo",
  "database_path": "<data_root>/sites/demo/db/site.sqlite",
  "filters": {},
  "output_path": "<output_dir>/report.xlsx",
  "created_at": "2026-07-09T12:00:00"
}
```

`output_path` 是 Export Worker 的内部 Artifact 输出位置，不是 Renderer 任意传入的用户最终保存路径。用户最终路径由 Electron Main 当次授权，只保存在 Renderer 当前 session 的共享协调器绑定中，不进入 Python `ExportJob` 或业务数据库。

job 参数只能包含可序列化数据：

```text
job_type
database_path
site_name
filters
output_path
locale
theme_or_export_style
```

禁止传入：

```text
Renderer / Electron 对象
sqlite connection
repository 实例
未序列化的 model 对象
```

导出进程必须自己打开数据库、读取数据、生成文件、关闭资源。

## 四、JSONL 进度协议

导出进程 stdout 推荐输出 JSONL：

```json
{"event":"started","stage":"prepare","message":"开始导出"}
{"event":"progress","stage":"query","current":100,"total":1000,"message":"正在读取数据"}
{"event":"progress","stage":"write","current":5,"total":10,"message":"正在写入工作表"}
{"event":"finished","output_path":"<output_dir>/report.xlsx","elapsed_ms":1234}
```

失败：

```json
{"event":"failed","error_message":"导出失败","traceback":"..."}
```

取消：

```json
{"event":"cancelled","message":"用户取消导出"}
```

UI 线程只解析进度事件并更新界面。

## 五、结构化文件契约与导入校验

可再次导入的正式结构化导出必须由 `netconsole.services.file_contract` 写入统一标识：

- XLSX：隐藏 sheet `_netconsole_meta`，记录 format、type、module、schema version、应用版本、导出时间、sheet 和字段。
- CSV：首行 `#NETCONSOLE_META`，其后为 JSON metadata，再写业务表头和数据。
- JSON：顶层 `_netconsole_meta`，列表输出统一包入 `data`。
- ZIP：根目录 `_netconsole_manifest.json`，记录模块、类型、schema 和内部文件清单。

业务导入函数必须在任何数据库、缓存或正式文件写入前调用统一 validator。校验至少覆盖扩展名、可读性、模块/类型/schema、必要 sheet/manifest/字段、列数量、业务结构和非空数据；ZIP 同时拒绝绝对路径、盘符和 `..` 路径穿越。无 metadata 的历史 XLSX/CSV 只能由明确声明 `allow_legacy=True` 且具备唯一表头/结构识别规则的入口兼容，无法识别的任意文件一律拒绝。

## 六、ExportProcessManager

推荐新增或复用统一导出进程管理器：

```python
ExportProcessManager
```

能力：

```text
创建 job 文件
启动导出进程
读取 JSONL stdout
解析进度
显示完成/失败/取消
防止重复启动同一导出
取消导出进程
记录日志
清理临时 job 文件
应用退出时终止子进程
```

所有页面应复用统一 Export Application Service，不要每个页面单独写一套 subprocess 或 JSONL 解析逻辑。

## 七、数据库和文件规则

轨旁 AP 业务导出是“Worker 内准备并冻结业务快照”的正式实现。Backend 只验证请求
契约并创建 Export Task，把页面 `expected_revision` 交给 Worker；Worker 在独立
Export Process 中以只读连接读取局点数据库，把基础业务行、工作簿输入、来源 revision 和 SHA-256 写入
`staging/trackside_ap_business/<site>/<task>/snapshot.json`，随后只读取该冻结快照
渲染工作簿，不再访问实时业务库。快照准备、渲染和清理都在 Worker 内完成；任务已
创建后若准备失败，Task/Artifact 进入失败终态并向 UI 返回结构化错误。详见
[轨旁 AP 业务只读快照](../rail-transit/trackside-ap/BUSINESS_SNAPSHOT.md)。

必须：

- 导出进程自己打开 SQLite 连接。
- 导出进程只读取 job 中指定的数据源和 filters，并在 Worker 内生成冻结快照。
- 输出文件先写临时文件，成功后再替换目标文件。
- 失败时保留清晰错误信息，必要时清理不完整临时文件。
- 本地 `.xlsx` 导出应优化列宽、筛选、冻结、文本格式，便于 WPS Office / Microsoft Office 打开。
- Electron 主动导出必须在创建任务前通过 Platform Adapter 选择最终路径；取消不创建任务。
- 任务型导出必须使用固定动作注册表校验建议扩展名、Artifact 扩展名和媒体类型，并把 `taskId` 与 Main 授权路径绑定。
- Artifact 本地提交必须携带后端给出的准确大小和 SHA-256；已有预选目标时不得再次弹出保存窗口。
- 本地保存失败时保留 Artifact，用户可在 Task Center 重新选择位置并复用同一 Artifact，不重新生成报告。
- 没有显式绑定的历史 Artifact 只在用户点击后打开一次“另存为”；页面加载和历史任务恢复不得自动弹窗。
- Browser 开发模式只能报告浏览器已开始下载，不能声称已验证本地文件或具体目录。

禁止：

- 复用 UI 线程数据库连接。
- 依赖 WPS 云服务、WPS API、KDocs 或在线同步能力。
- 在 UI 线程中预先读取全量数据或把全量业务行 inline 传给导出进程。
- 默认把大数据 inline rows 写入 Job JSON；兼容 inline 模式必须显式启用且不超过当前 5000 行上限。
- 导出失败静默，或只写控制台不反馈 UI。
- Electron Bridge 缺失时回退到 Browser anchor 下载。
- 把 Renderer 任意提供的绝对路径当成新的授权目标，或把目标路径长期写入业务数据库。

## 八、日志事件

导出类任务必须写日志中心事件：

```text
EXPORT_JOB_STARTED
EXPORT_JOB_PROGRESS
EXPORT_JOB_COMPLETED
EXPORT_JOB_FAILED
EXPORT_JOB_CANCELLED
```

日志详情必须包含：

```text
导出类型
输出路径
耗时
记录数量
失败数量
错误摘要
```

## 九、交付说明

涉及导出的改动，交付时必须说明：

1. 是否使用独立进程。
2. 是否通过 ExportJob 传参。
3. 是否通过 JSONL 或等价机制回传进度。
4. 是否支持失败提示、取消和日志。
5. 是否影响导出模板、列宽、筛选、冻结、文本格式。
6. 是否触碰数据库结构。
7. 开发环境和打包环境下如何启动导出 worker。

当前 worker 的 Job 描述位于 `.local/runtime/cache/export_jobs/`。输出先写目标旁 `.tmp`，成功时 `os.replace`；失败、取消或进程异常时 manager/worker 必须清理临时文件。页面显示的行数上限不得截断 repository、JSONL 或缓存文件中的完整导出数据。
