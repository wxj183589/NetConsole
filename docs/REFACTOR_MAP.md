# Job Center 架构迁移地图

本文记录本轮已完成、兼容保留和后续优先级。它不代表所有存量页面已经完成迁移。

## 已完成

| 能力 | 当前状态 |
| --- | --- |
| 统一模型 | 已建立 `JobSpec / JobResult / JobProgress / JobError`，`BackgroundJob` 保持兼容 |
| 统一事件 | 已建立 progress/log/finished/error/cancelled 事件 |
| JSONL | 普通 worker 与 export worker 共用 `worker_protocol.py` |
| 注册表 | 77 个兼容 task_type、3 个在线 MR 实时采集 task_type 与 2 个 SNMP task_type 已按领域注册，正式分发不再使用 if/elif |
| 领域分区 | 已建立 AC、配置、设备、文件、Mesh、网络、在线 MR、轨道交通、SNMP、无线勘测 handler 模块 |
| Runner | background worker 统一通过 JobRunner 捕获取消、异常和 traceback |
| Task Manager | 新实现位于 `job_center/task_manager.py`，支持 start/cancel/is_running 和四类终态 signal |
| Export | ExportProcessManager 复用统一 JSONL 解析，保留 frozen、临时文件、取消和 WPS/Excel 占用提示 |
| Mesh 链路明细导出 | 已移除页面内重导出 QThread/subprocess，改为 ExportJob + submit_export_task |
| 在线 MR 实时采集 | SSH 采集、命令序列、原始日志、停止清理和打包已迁入长运行 Job / Worker Process；解析与报告也通过 Job / ExportJob 执行 |
| SNMP 查询执行 | GET / GETNEXT / GETBULK / WALK / SET 统一提交 `snmp_query_execute`，Worker 内创建 Domain Service、Repository 与 Client，并回传进度、结果、异常和取消事件 |
| SNMP 批量采集 | 多设备、多 OID 的只读采集统一提交 `snmp_collection_execute`；Worker 内按设备并发、独立 Client、部分失败汇总，并写入去敏结果缓存 |
| AC 资源刷新（第一阶段） | 页面“刷新资源”复用 `ac_fit_ap_resources_refresh` 进入 Worker；`services/ac` facade 统一选择已验证的 H3C CLI 或显式 SNMP 策略，AP/Radio/LLDP parser 和 repository 保持原规则 |
| UI helper | 已新增 `ui/job_action_helper.py`，普通任务可复用非模态进度、取消和回调 |

## 兼容保留

- `services/background_job.py`：重导出新模型。
- `services/background_process_manager.py`：重导出新 Task Manager。
- `services/background_tasks.py`：只保留 `BackgroundTaskCancelled` 与 registry dispatch。
- `services/job_center/handlers/legacy_tasks.py`：原 77 个任务的业务实现暂时原样保留，领域 handler 以薄适配调用，防止本轮结构调整改变业务规则；新增的在线 MR 实时采集与 SNMP 查询任务不进入该文件。
- `services/export/export_job.py`、`ExportProcessManager` 和旧 `export_type` 兼容名称继续有效。
- 未在本轮完全迁移的页面可继续调用旧 manager API，但新增任务不得进入 legacy 文件。

legacy_tasks 是只迁出、不迁入的兼容区。后续维护某一领域时，将对应实现和辅助函数移动到正式 Domain Service/handler，并保持 task_type 不变。

## 新增功能强制路径

```text
UI page
  -> ui/job_action_helper.py 或 ui/export_action_helper.py
  -> Job Center registry / ExportProcessManager
  -> Worker Process
  -> Domain Service
  -> Repository / Parser / Adapter
```

禁止新增页面内 SSH/SNMP/Excel/大日志解析/大查询；禁止向兼容 dispatcher 或 legacy_tasks 增加任务。

## 重点页面优先级

| 优先级 | 页面 | 当前情况 | 目标状态 |
| --- | --- | --- | --- |
| P0 | `ui/pages/mesh_log_analysis_page.py` | 链路明细导出已迁；仍有导入、派生分析和报告等存量 worker | 所有重任务只提交 Job/ExportJob，页面只消费事件 |
| 已迁移 | `ui/pages/online_mr_collection_page.py` | SSH 实时采集已改为长运行 Job，解析和报告分别使用 Job / ExportJob；页面只轻量跟踪已落盘日志 | 保留现有 fping/iperf 专用运行时和实时显示策略，不改业务规则；后续仅按明确需求收敛 |
| 已迁移（第一阶段） | `ui/pages/snmp_center_page.py` | 查询执行链路已迁入 Job Center；页面仅收集参数、提交任务并绑定结构化结果 | MIB 浏览/搜索、全局 MIB 仓库、H3C 映射、Trap 与 Poll 保持原状；后续单独迁移批量采集 |
| 已迁移（第一阶段） | `ui/pages/ac_management_page.py` | FIT-AP/AP状态/Radio/LLDP 资源采集已改为 Job + AC Domain；AC 信息、命令动作、光衰仍保留原专用 worker | 后续按光衰服务、AP 模型分阶段迁移，不整体重写页面 |
| P1 | `ui/pages/network_toolbox_page.py` | 多种外部工具和结果导出 | 工具进程归 Job Center，服务端/客户端状态保持隔离 |
| P1 | `ui/pages/file_management_page.py` | 导航已后台化，传输有专用 worker | 扫描、传输、批量操作统一任务事件和退出治理 |
| P2 | `ui/pages/config_collection_center_page.py` | 已使用 BackgroundProcessManager 和 export helper | 采集、diff、快照、导出全部只通过 Job |

每个页面的最终验收一致：

- 页面不直接执行长任务。
- 页面只提交 Job / ExportJob。
- 页面只消费 progress/log/result/error/cancelled 并刷新 UI。
- 页面关闭、局点切换、应用退出有明确任务治理。

## 后续拆分建议

1. 以页面实际维护需求为触发点，从 `legacy_tasks.py` 逐领域迁出，不做一次性大爆炸重写。
2. AC 资源刷新第一阶段已完成；下一阶段迁移光衰 Domain Service，保持 AP 离线关联、异常判断和轨旁业务规则不变。
3. 为每个领域增加 handler 注册完整性和业务回归测试。
4. 逐页替换重复 manager signal 绑定为 `submit_background_job`。
5. 完成领域迁出后删除 legacy 中已无引用的函数；`services/background_tasks.py` 兼容入口长期保留。
