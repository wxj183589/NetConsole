# NetConsole v1.5.16 修复实施计划

## R4.0 无人值守与配置安全

1. 统一 Heartbeat、深度预算、AC 基础采集控制的模型、数据库和运行时默认关闭语义。
2. Heartbeat 用“排除列车 ID”持久化选择：初始与新增列车默认选中，用户取消选择不会被库存刷新冲掉。
3. 规范化旧 `ac_poll_interval_seconds` 到唯一 AC/Mesh-Link 周期；ARP VLAN 继续使用已存在的安全多值解析与参数化命令构造。
4. 置顶列车归入深度预算并与 Heartbeat 选择隔离。
5. 配置检查默认 `VERIFY_ONLY`；JOIN/EXIT 使用显式确认和精确命令白名单。
6. Syslog UDP Receiver 只跟随无人值守总开关，并使用同一 Syslog IP/端口。

## R4.1 Heartbeat、MR 与稳定性

7. Heartbeat 显示可信 AC/Mesh-Link 解析结果、更新时间和新鲜度；无可靠结果显示未知。
8. 主备 Ping 图表纵向布局，Peer AP 以持续时间宽度/RSSI 强度高度独立展示；只接受 `mesh_activelink_switch` 事件，最近事件限制为三条并本地化时间与状态。
9. 修复 Quick Ping 内部状态泄漏到严格 DTO，以及关闭阶段缺表导致的未处理异常；执行页面与并发回归。
10. 仅删除 Heartbeat 顶部当前丢包率，不删事件、历史或分析能力。

## R4.2 AC/Mesh-Link 与 V5

11. 复用 main 已有 V5 能力识别、V5 Mesh fallback、FIT-AP 快照保护和部分成功语义，运行相关 fixture 回归。
12. 退役连接关系图实现；车站/方向分组默认折叠，Peer Name 为空回退 Peer MAC/BSSID。

## R4.3 Windows、功能收口与局点

13. Storage Audit 返回明确的报告缺失、报告不完整、数据根不可访问和带错误可用状态，UI 不再把缺报告显示为容量 0。
14. 独立车内通信导航退役，旧路由安全跳转到无人值守；共享 API、服务和历史数据保留。
15. 关闭阶段缺表降级为可诊断状态；复用并回归 main 已有的局点 staged import、失败清理和幂等恢复。

## 发布原则

代码通过不等于现场发布通过。未完成 Windows 10 实机、真实 V5 只读采集和 8 小时长稳前，不生成或发布正式安装包。
