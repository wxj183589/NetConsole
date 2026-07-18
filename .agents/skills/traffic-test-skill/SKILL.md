---
name: traffic-test-skill
description: "iperf3、iPerf、TCP/UDP 打流、fping v5 高频 Ping、CBTC/PIS 模板、带宽/吞吐、抖动、丢包、阈值、重试或在线 MR 流量测试联动时使用。普通 SSH 连通测试、无 Ping/iPerf 的日志解析或路由配置不使用本 Skill。"
---

# 目标

维护 NetConsole 的 fping/iPerf 执行、解析、模板、阈值、日志、停止重试和在线 MR 生命周期联动。

# 触发与反例

触发示例：

- “修复 fping 高频 Ping 丢包统计和 Ping 2 自动填充。”
- “增加 PIS TCP 上/下行与 UDP 固定速率模板。”
- “iPerf 服务端检查失败时阻止启动，并显示重试状态。”

不应触发：

- “普通设备 SSH 连接失败。”
- “只解析 MR mesh-link 或配置 Windows 路由。”

# 输入与输出

- 输入：测试方向、目标、协议、时长/整体采集时长、速率、并发、阈值和日志要求。
- 输出：runner/parser/preset/UI 接入修改、进程生命周期说明、结构化指标和验证结果。
- 允许修改生产代码：允许，限 fping/iPerf 服务、在线 MR 联动、相关 UI 和测试；不得硬编码现场地址或改变无关采集命令。

# 开始前读取

- `src/netconsole/core/ping/`、`src/netconsole/services/fping_v5.py`、`src/netconsole/services/fping_legacy_parser.py`。
- `src/netconsole/services/network_tools/`、`src/netconsole/backend/api/network_tools_router.py`、`apps/web/src/views/network-tools/TrafficTestView.vue`。
- `src/netconsole/services/online_mr/ping_presets.py`、`src/netconsole/services/online_mr/traffic_presets.py`。
- `src/netconsole/services/online_mr/workers/`、`src/netconsole/services/online_mr/traffic_coordinator.py`、`apps/web/src/views/rail-transit/OnlineMrRealtimeView.vue`。
- `tests/test_fping_v5.py`、`tests/test_iperf_network_tools.py`、`tests/test_online_mr_collection.py`。

# 工作流程与规则

1. TCP 用于当前移动场景的最大有效吞吐，也支持平均带宽低于 300/600 Mbps 等可配置阈值判定。
2. UDP 用于验证指定速率下的丢包、抖动和稳定性；不得把 TCP/UDP 指标混用。
3. 模板优先覆盖 CBTC 高频 Ping、PIS TCP 上行、PIS TCP 下行、PIS UDP 固定速率和长时间稳定性。
4. fping 使用项目工具发现逻辑；日志带时间戳。Ping 1/Ping 2 独立，单设备只自动填 Ping 1，不把同一地址自动填入 Ping 2。
5. iPerf 启动前检查服务端地址和端口；在线 MR 中跟随整体采集启停，不单独延长测试时长。
6. 中断、重试、停止和失败状态对用户可见；客户端/服务端进程与日志分离并正确回收。
7. 结果考虑平均/最小/最大带宽、抖动、丢包率、中断次数和低于阈值时长。
8. 不需要微调按钮的参数使用无按钮输入；参数不得遮挡，窗口变小时可滚动。

# 验证与失败报告

- 本地 `127.0.0.1` 仅验证功能，不代表真实车地无线链路。
- 验证 TCP 阈值、UDP 丢包/抖动、fping 样本、服务端不可达、停止/取消和进程回收。
- 真实链路结论必须报告方向、速率、时长、阈值和移动场景限制；缺少真实链路时明确未验证。
- 输出修改文件、UI 参数、日志/数据库影响和手工步骤。

# 相关 Skills

- 在线 MR 生命周期：`netconsole-online-mr-skill`。
- 后台任务：`netconsole-job-center-skill`。
- UI 遮挡：按 `docs/UI_DESIGN_SYSTEM.md` 和 Vue/Element Plus 组件测试处理。
