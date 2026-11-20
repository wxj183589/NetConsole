# NetConsole v1.5.16 十五项验收矩阵

状态定义仅使用 `PASS`、`PARTIAL`、`BLOCKED`、`NOT_STARTED`。`PASS` 表示代码与当前可执行自动化已完成，不代表未列出的现场发布 Gate。

| # | 原始问题与根因 | 修改文件与内容 | 自动化结果 | 界面/现场证据 | 状态与遗留 |
| --- | --- | --- | --- | --- | --- |
| 1 | 三功能默认关闭；模型、数据库和运行时 fallback 原先不一致 | `ground_unattended.py`、Repository、Supervisor：Heartbeat、深度预算、AC 基础采集统一默认关闭，旧显式配置保留 | 默认值、迁移、启动条件回归 PASS | 设置页构建与 Renderer 回归通过；未做现场截图 | `PASS`；默认启动边界已闭合 |
| 2 | Heartbeat 缺少独立、可持久化的启动列车选择 | Heartbeat DTO/Repository/Supervisor、`HeartbeatSettings.vue`：持久 exclusions、全选/全不选、折叠、空选择拒绝；与深度置顶隔离 | resident/inventory/API/Renderer PASS | 组件回归通过；未做真实 Electron 截图 | `PASS`；新增列车默认选中 |
| 3 | AC 与 Mesh-Link 周期重复；ARP 多 VLAN 必须避免字符串注入与重复计数 | Profile/Repository/Settings：周期规范化到 `ac_mesh_link_poll_interval_seconds`，兼容旧字段；复用既有参数化多 VLAN 实现 | schedule/usability/ARP 回归 PASS | 设置页只显示一个周期；真实 AC 只读验证未做 | `PASS`；现场设备证据仍属发布验收 |
| 4 | 深度置顶和 Heartbeat 选择语义混用 | `SettingsPage.vue`：深度预算与置顶子区独立折叠，总开关关闭时禁用置顶操作 | Renderer 设置页与 build PASS | 组件回归通过；默认无置顶 | `PASS` |
| 5 | 检查入口默认可能触发修复，写命令范围过宽 | DTO、Application Service、`boot_config.py`、Heartbeat 页：强制 `VERIFY_ONLY`、精确 JOIN/EXIT 白名单、显式确认、历史 owned target 退出 | Mock SSH/Syslog 安全契约 PASS，检查写调用为 0 | 预览/确认组件回归通过；未连接真实 MR | `PASS`；真实 V5/V7/V9 回显待授权单机验证 |
| 6 | 独立 Receiver 开关可绕过无人值守总开关并形成第二地址源 | Profile、Supervisor、Settings：Receiver 仅跟随 `profile.enabled`，绑定统一 Syslog IP/port，停止释放与幂等路径沿用既有实现 | Supervisor/Syslog 契约 PASS | 状态页与设置页构建通过；未做真实端口占用演练 | `PASS` |
| 7 | Heartbeat 未完整呈现可信 AP/站点关联及新鲜度 | `HeartbeatPage.vue`：展示 AP/站点/MAC、更新时间和 AC 数据状态，不新增名称/IP猜测 | Renderer 页面回归 PASS | 自动化 DOM 证据通过；现场 AC 切换实时回放未完成 | `PARTIAL`；真实关联及时性待验收 |
| 8 | MR 监控布局、事件范围和中文时间不符合要求 | `MrMonitoringDrawer.vue`：主备纵向、图表在事件前、丢包事件默认折叠且最近三条、本地时间/中文状态、仅 ActiveLink Switch | Renderer 全量与 build PASS | jsdom/build 通过；未做 1920×1080/2K 实机交互 | `PARTIAL`；RSSI 高度区间柱和同步交互仍需完整实机验收 |
| 9 | 现场日志含 Renderer 崩溃、Quick Ping strict DTO 和关闭缺表三类线索 | Application Service、Task Service、关系图页面：净化 `_close_confirmed`、关闭阶段捕获数据库缺表、退役关系图资源监听 | Python/Renderer/Electron/build 回归 PASS | 日志证据已复核；8 小时长稳未执行 | `PARTIAL`；不能宣称 `exit_code=-36861` 完全根治 |
| 10 | Heartbeat 顶部“当前丢包率”冗余 | `HeartbeatPage.vue`：仅删除顶部指标，保留样本、事件、历史和监控图 | Renderer 页面回归 PASS | DOM 回归通过 | `PASS` |
| 11 | V5 AC/FIT-AP 更新存在版本能力差异 | 审计 main 既有 V5 fallback、解析 fixture、Current 快照保护和部分成功语义；未整体合并旧分支 | V5/FIT-AP fixture 与全量 Python 回归 | 无真实 V5 只读采集 | `PARTIAL`；需真实脱敏回显确认命令/解析 |
| 12 | AC/Mesh-Link 独立关系图及车站展示不符合需求 | `AcMeshLinkPage.vue`：退役关系图实现/监听，车站与方向默认折叠，保持服务端顺序并保留 Peer MAC 回退 | 页面回归、Renderer 全量、build PASS | 自动化页面证据通过 | `PARTIAL`；canonical 站序、车辆段/停车场置底和端口逻辑排序尚无完整真实数据验收 |
| 13 | Win10 缺报告时被显示为零容量，无法区分错误状态 | Storage Audit API/UI：新增未生成、不完整、不可访问、带错误和 READY 状态 | Storage Audit、Renderer 全量/build PASS | 当前 Windows 开发机自动化通过；不是 Win10 20H2 实机 | `PARTIAL`；ACL、中文路径、安装版仍待实机 |
| 14 | 独立车内通信入口能力已被 Heartbeat/Quick Ping/MR 监控覆盖 | navigation/routes：隐藏入口，旧路由保留 query/hash 跳转无人值守；共享后端和历史数据不删 | Router/registry/architecture PASS | 路由组件回归通过 | `PASS` |
| 15 | 现场导入首次失败后恢复，关闭阶段查询缺表未捕获 | Task Service：关闭快照捕获 `sqlite3.DatabaseError` 并记录警告；复核 main staged import/失败清理/幂等恢复 | Site 导入/恢复/关闭与全量 Python 回归 | 只读分析现场日志，未操作 `.trash` | `PASS`；现场回收站保持不变 |

## 汇总

- `PASS`：9 项（1、2、3、4、5、6、10、14、15）。
- `PARTIAL`：6 项（7、8、9、11、12、13）。
- `BLOCKED`：0 项。
- `NOT_STARTED`：0 项。
- 安装包：未生成。
- Win10 实机：未完成。
- 8 小时长稳：未完成。
- 未授权设备操作：0。
- 自动化总门禁：Python 5620 passed / 2 skipped；Renderer 1544 passed；Electron 315 passed；Architecture 12/12；Main contract 12 passed。
