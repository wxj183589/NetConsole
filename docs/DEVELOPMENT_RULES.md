# NetConsole 开发规则

本文是新增功能和维护存量代码的强制检查表。

## 先判断任务类型

开发前先回答：

1. 是否访问网络、设备、外部命令、数据库、磁盘或大文件？
2. 是否可能执行超过 300ms？
3. 是否包含大循环、批量操作、解析、压缩、图表或报告生成？
4. 用户是否需要进度、取消、日志和失败原因？

超过 300ms 的 IO、CPU 或网络任务不得在 UI 线程执行。重 CPU、重 IO、重网络和批量任务进入 Worker Process；所有导出进入独立 Export Process。

## Job 必备字段和能力

所有普通任务和导出任务必须具备：

- `job_id`
- `task_type` 或 `job_type`
- 可 JSON 序列化的 `params`
- `progress`
- `cancellation`
- 用户可理解的 `error message`
- structured result

Worker 必须支持 `progress / log / finished / error / cancelled`。失败不得只写控制台，UI 必须收到友好消息，traceback 进入诊断日志或事件字段。

## Worker JSONL 协议

- stdout 只能输出一行一个 JSON 对象的 UTF-8 JSONL。
- stderr 只用于 traceback 和诊断输出。
- 原始设备日志、外部命令回显不得直接打印到 stdout。
- 公共编码、解析和输出复用 `services/job_center/worker_protocol.py`。
- handler 中遗留的普通 `print` 会由 worker 重定向到 stderr；新增代码仍应使用结构化 log event。

## 编码边界

- Worker 内部协议和 Job JSON 固定 UTF-8。
- Python 文本读写显式指定 `encoding="utf-8"`。
- SSH/Telnet/SNMP、H3C 回显、MIB、CSV 和历史日志在 Adapter 边界做编码兜底。
- 外部文本按 `utf-8-sig → utf-8 → gb18030 → gbk` 尝试，不能因终端乱码删除中文。

## 导出统一规则

- UI 只创建 `ExportJob`，不得直接写 Excel。
- 输出先写临时文件，成功后替换目标文件。
- 取消、失败和进程异常必须清理临时文件、Job 文件和取消文件。
- Excel 列宽按表头和采样内容自适应，长字段有上限，保留横向滚动/查看能力。
- XLSX 保持 WPS/Excel 兼容、冻结表头、筛选、文本格式和中文字段。
- 目标文件被 WPS/Excel 占用时提供明确关闭文件后重试提示。

## 页面瘦身

页面只保留：

- 布局和控件创建。
- 信号绑定。
- 输入收集和轻量校验。
- loading / empty / success / error / cancelled 状态刷新。
- 结构化结果到 ViewModel 的绑定。

业务判断下沉 Domain Service；展示转换下沉 ViewModel / Presenter；数据读写下沉 Repository；解析下沉 Parser；设备通信下沉 Adapter。

不允许新增巨型 page 文件。触碰现有巨型页面时，以当前用例为边界逐段迁移，不做破坏性全量重命名。

## Dispatcher 和 Handler

- 新任务必须注册到 `services/job_center/handlers/<domain>_jobs.py`。
- 不得向 `services/background_tasks.py` 或 `handlers/legacy_tasks.py` 追加任务。
- `services/background_tasks.py` 只作为兼容入口。
- 跨领域公共能力放 `handlers/common.py` 或正式公共 service，不复制路径和取消解析代码。

## UI 与任务状态

- 推荐使用 `ui/job_action_helper.py::submit_background_job`。
- 导出使用 `ui/export_action_helper.py::submit_export_task`。
- 对话框非模态，任务运行时防重复提交。
- 超过 1 秒显示阶段或进度；可取消任务提供取消入口。
- 页面切换、主题切换不得清空任务状态和日志。
- Worker 不访问 QWidget；数据库连接在 Worker 内创建。

## SNMP 查询边界

- GET、GETNEXT、GETBULK、WALK、SET 从 UI 统一提交 `snmp_query_execute`，页面不得直接创建 `SnmpClient` 或查询 QThread。
- SNMP profile、operation、OID、超时、重试、bulk 参数和 SET 类型必须通过可序列化请求模型传递，禁止跨进程传 client、repository 或 Qt 对象。
- MIB 名称/OID 展示上下文可随请求传入，但 MIB 搜索、全局仓库、H3C 映射、Trap 和 Poll 不进入查询 Job。
- WALK/GETBULK 在批次边界报告进度并检查取消；结果较大时由 Worker 写缓存或分页，页面只绑定结构化行。

## SNMP 批量采集边界

- 多设备采集统一使用 `snmp_collection_execute`，不得为具体设备、OID 或 AC/AP 用例增加零散 task_type。
- 并发按设备限制为 5～50；每设备独立 Client，单设备内 OID 顺序执行，禁止跨线程共享 Client、repository 或 SQLite connection。
- 默认失败策略是记录单设备错误并继续；`stop_on_failure` 仅停止投递新设备，不强制中断正在执行的网络调用。
- 取消必须停止新任务、等待当前请求收敛并只产生 cancelled 终态，不得同时返回 failed/finished。
- 批量缓存必须去敏并原子写入；认证字段只能存在于临时 Job 参数，不能写入结果缓存或日志。
- Batch Collection 是一次性任务，不得在该服务中加入 interval、常驻 Poll、Trap 或 AC 业务字段映射。

## AC Domain 边界

- FIT-AP 资源采集统一通过 `ac_fit_ap_resources_refresh`；页面只传 device_uuid、site_name、source 和路径，不传 Device、连接或 repository 对象。
- AC Domain 决定 CLI/SNMP 来源。H3C CLI 信息更完整时保留 CLI；只有明确 OID 与已验证 mapper 同时存在时才允许 SNMP 结果写入 AC repository。
- `display wlan ap all`、address、radio、LLDP 等命令及其 parser 合并规则保持在现有 Adapter/Service/Parser，不复制到页面或通用 SNMP 层。
- Domain/Worker 内创建 DeviceRepository、AcRepository 和采集 Client；页面不得创建 AC 资源采集 QThread。
- 光衰异常、AP 离线关联、里程/区间归属、轨旁 AP 业务规则不得下沉到通用 SNMP Collection。
- FIT-AP 是主应用数据，迁移 facade 和任务入口不得修改 schema 或破坏旧资源、历史和扩展信息兼容。

## Qt 测试生命周期

- 需要创建顶层 QWidget/QDialog 的测试模块可通过 `pytestmark = pytest.mark.usefixtures("qt_page_lifecycle")` 显式启用 `tests/conftest.py` 中的生命周期隔离。
- fixture 在 pytest 进程内强引用唯一 `QApplication`，每条用例后先排空当前事件，再关闭顶层窗口并处理 `DeferredDelete`，避免对象累计到 pytest 最终 GC 时触发 native abort。
- 不得把页面清理 fixture 全局 autouse；带延迟回调、QThread 或 QProcess 的页面必须先确保任务已完成或已取消，再按模块接入。
- 如果某个 Qt 模块仍无法安全共享 `QApplication`，应使用独立 pytest 子进程隔离该模块，不在业务代码中加入测试专用延迟或异常吞噬。

## 提交前检查

- 新增/修改 Python 文件通过 `python -m py_compile`。
- 对应 pytest 覆盖成功、失败、空数据、取消。
- 搜索 UI 页面是否出现网络连接、Excel 保存、大文件解析和长查询。
- 搜索 Worker 是否导入 UI page。
- 检查旧 `BackgroundJob / BackgroundProcessManager / run_background_task / ExportJob / ExportProcessManager` 导入仍可用。
- 说明是否影响数据库结构、导出模板、编码策略、日志和中文显示。
