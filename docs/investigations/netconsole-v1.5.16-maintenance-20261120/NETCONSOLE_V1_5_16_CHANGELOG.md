# NetConsole v1.5.16 维护变更记录

## 无人值守

- 三个采集能力默认关闭；保存配置时再次规范化兼容字段。
- Heartbeat 增加独立列车选择、全选、全不选和折叠；无有效列车时拒绝启动。
- AC/Mesh-Link 周期统一到规范字段，保留旧字段兼容读取。
- 深度采集置顶列车归入预算区域，不再与 Heartbeat 选择混用。

## Syslog 安全

- Syslog 服务器 IP/端口成为监听、检查、JOIN、EXIT 和预览的唯一来源。
- 配置检查默认只读；移除 source rule 写命令。
- JOIN 精确限制为 `system-view`、`info-center enable`、单条 loghost、`return`、`quit`。
- EXIT 只撤销 NetConsole 记录的历史目标，不关闭全局 Info-center。
- 页面在 JOIN/EXIT 前展示目标和命令并要求显式确认。

## 监控与稳定性

- Heartbeat 展示接入 AP/站点、MAC、更新时间和新鲜度；顶部不再展示当前丢包率。
- MR 主备 Ping 监控改为上下布局；Peer AP 独立区间图以柱宽表示主用持续时间、柱高表示 RSSI 强度；事件只取 ActiveLink Switch 最近三条。
- Quick Ping 严格 DTO 写入前剥离内部 `_close_confirmed` 状态。
- Backend 关闭时缺少 `task_snapshots` 表不再抛出未处理异常。

## AC、存储与路由

- 连接关系图实现和入口退役；车站/方向分组默认折叠，Peer 显示具有 MAC/BSSID 回退。
- Storage Audit 明确区分未生成、不完整、不可访问和带错误结果。
- 独立车内通信入口退役；旧链接跳转至无人值守，保留共享能力和历史数据。
- 版本身份对齐为 v1.5.16。
