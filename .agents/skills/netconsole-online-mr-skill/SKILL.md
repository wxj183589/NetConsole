---
name: netconsole-online-mr-skill
description: "车载 MR 实时采集、Online MR、SSH 会话、实时解析、Channel Busy、备注、高频 Ping、iPerf、启动确认、停止清理、会话目录或自动打包任务时使用。离线 MR 原始 MESH 日志分析使用 netconsole-mesh-analysis-skill；通用 iPerf 页面或普通设备采集不使用本 Skill。"
---

# 目标

维护车载 MR 实时采集的 UI、长运行 Job、命令序列、原始日志、实时状态、Ping/iPerf 联动、停止和会话打包，保护既有现场采集链路。

# 触发与反例

触发示例：

- “单设备选择时 Ping 2 被错误自动填充。”
- “采集开始后参数区未收起，1080p 状态被遮挡。”
- “Channel Busy 没解析、停止困难或会话未打包。”

不应触发：

- “修复离线 MESH 主备链分析。”
- “只修改通用 iPerf 页面或普通 AC 资源采集。”

# 输入与输出

- 输入：设备选择、周期、Ping/iPerf 参数、命令/日志问题、会话目录和复现步骤。
- 输出：在线 MR UI/Job/service/parser 修改、原始文件保护说明、生命周期测试和验证步骤。
- 允许修改生产代码：允许，限在线 MR、相关 Ping/iPerf/解析/UI/Job 和测试；不得凭经验改命令顺序或删除 raw log。

# 开始前读取

- `src/netconsole/ui/pages/online_mr_collection_page.py`、`src/netconsole/ui/pages/online_mr_collection_analysis_page.py`。
- `src/netconsole/services/online_mr/`、`src/netconsole/services/online_mr_collector.py`、`src/netconsole/services/online_mr_parser.py`。
- `src/netconsole/services/online_mr_session_store.py`、`src/netconsole/services/online_mr_terminal_log_parser.py`。
- `src/netconsole/services/rail_transit/online_mr_diagnosis_parser.py`、`src/netconsole/models/online_mr_models.py`。
- `src/netconsole/services/job_center/handlers/online_mr_jobs.py`、`src/netconsole/core/mr_collect/`、`src/netconsole/core/ping/`。
- `tests/test_online_mr_collection.py`、`tests/test_online_mr_collection_job.py`。

# 业务与生命周期规则

1. 最多同时选择/运行两台 MR。单选只自动填 Ping 1，Ping 2 保持独立；双选时分别映射两台，用户手工值不得被无条件覆盖。
2. 开始前显示可滚动确认，包含设备、周期、高频 Ping 和 iPerf；启用 iPerf 时正式启动前检查服务端地址和端口。
3. 正式开始后自动收起设备列表和参数区，但用户可重新展开；1080p 实时状态不得遮挡，状态同时用文字和颜色。
4. 采集中允许记录带时间戳备注；iPerf 跟随整体采集启停，不独立延长测试时长。
5. 设备命令以 `src/netconsole/services/online_mr/collection_commands.py` 为唯一事实源，不改变顺序或文本。
6. 会话路径以 `src/netconsole/services/online_mr/collection_paths.py` 为事实源；停止后协作取消、关闭 SSH/文件、保存 raw、更新状态并原子打包。
7. UI 只提交长运行 Job 和绑定事件；大解析走 `online_mr_parse` Job，报告走 Export Process。

# 必须保护的会话文件

- `init_raw.log`、`config_collect_raw.log`、`terminal_monitor_raw.log`、`mesh_link_raw.log`。
- `ap_radio_statistics_raw.log`、`channel_busy_raw.log`、`switch_history_latest.log`。
- `wireless_status_raw.log`、`interface_rate_raw.log`、`collector_output_raw.log`。
- `fping_v5_raw.log`、`fping_v5_samples.jsonl`、`fping_v5_final_summary.json`。
- `iperf_client_raw.log`、`session_meta.json`、`outputs/<session>.zip`。

# 验证与失败报告

- 验证单选/双选 Ping 映射、手工值保留、启动取消/确认、折叠恢复、iPerf preflight、运行中备注和最多两任务。
- 验证正常停止、取消、强制停止、SSH 清理、raw 文件完整、解析、会话状态和 ZIP 临时文件清理。
- 缺少真实 MR/服务端时说明只完成 fake connection/本地功能测试，不声称现场稳定。
- 输出修改文件、命令是否变化、保护的 raw/会话文件、UI/数据库影响和手工步骤。

# 相关 Skills

- Ping/iPerf：`traffic-test-skill`。
- CLI parser：`network-command-parser-skill`。
- 长运行 Job：`netconsole-job-center-skill`。
- 报告：`netconsole-export-report-skill`。
