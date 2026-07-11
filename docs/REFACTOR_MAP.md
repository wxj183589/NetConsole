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
| AC 光衰刷新（第一阶段） | FIT-AP 全量和单 AP 光衰复用 `ac_fit_ap_optical_refresh` 进入 Worker；`AcOpticalService` 复用既有 H3C collector，并在 Domain 层完成 AP 离线和交换机光模块状态关联 |
| AC 命令动作（第一阶段） | 固化新上线 AP、开启 AP 远程登入等现有动作统一提交 `ac_command_action_execute`；Worker 内通过 `AcCommandService` 复用既有命令 profile、白名单、连接和 raw log 逻辑 |
| AP 统一模型评估（阶段 0） | 已完成数据来源、标识/字段矩阵、消费者、不可破坏规则和阶段 1～6 路线评估；本阶段只更新文档，未替换生产模型或修改 schema |
| AP identity 工具（阶段 1） | 已新增 frozen identity/observation/candidate/evidence 模型、MAC/名称/里程 normalizer、保守 resolver 和只读 adapters；36 个 characterization tests 通过，尚未接入生产流程 |
| AC AP identity 适配（阶段 2） | FIT-AP 资源与 AP 扩展 preview/commit/refresh/save 已增加 old/new shadow comparison；只附加诊断字段，旧 helper、Repository 写入、schema、UI 和导出保持不变 |
| AC 光衰 identity shadow（阶段 3） | `ac_fit_ap_optical_refresh` 的 load/collect、all/single 已附加 AP 关联诊断；仅接口记录不解析 AP，旧光衰关联、离线/无光/阈值规则和写入保持不变 |
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
| 已迁移（第三阶段） | `ui/pages/ac_management_page.py` | FIT-AP 资源、光衰和现有 AC 命令动作均已改为 Job + AC Domain；identity 阶段 2/3 仅在 Job result 附加 shadow，页面流程未改 | 下一步只做轨旁业务只读接入评估，不直接迁移轨旁业务 |
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
2. AC 资源、光衰和命令动作 Domain Service 第一阶段已完成；AP identity 阶段 0～3 见 [AP_MODEL_ASSESSMENT.md](AP_MODEL_ASSESSMENT.md) 与 [AP_IDENTITY.md](AP_IDENTITY.md)，下一阶段只评估轨旁只读接入。
3. 为每个领域增加 handler 注册完整性和业务回归测试。
4. 逐页替换重复 manager signal 绑定为 `submit_background_job`。
5. 完成领域迁出后删除 legacy 中已无引用的函数；`services/background_tasks.py` 兼容入口长期保留。

## AP 统一模型迁移边界

- 现有 `ap_entities` 是统一 identity 的基础，不新增第二张 AP 主表。
- `ap_uuid` 用于站点数据库内已落表对象；跨模块优先规范化 AP MAC；名称和 AC APID 只作带作用域降级匹配。
- Radio MAC、BSSID/BBSSID、Peer MAC、Peer Radio MAC 保持 radio/观测层语义，不折叠为 AP MAC。
- 推荐路线固定为：identity 工具（已完成）→ AC/extension shadow（已完成）→ 光衰 shadow（已完成）→ 轨旁只读评估 → MR/Mesh 匹配增强 → 导出去重。
- 每一阶段先做旧/新 shadow comparison，保持数据库、业务规则、页面字段和导出兼容；不得从 identity 工具直接跳到轨旁业务迁移。
