# 旧版 UI/UX Phase 2 进度

产品基线 `be6b74bf`，DevStatus 基线 `1a7513e`。沿用 [Phase 1 设计规范](UI_DESIGN_SYSTEM.md) 和 [固定源码参考矩阵](OPEN_SOURCE_REFERENCE_MATRIX.md)。实际页面 35 条，兼容跳转 13 条。上一阶段沿用原界面的 16 条均有本轮页内改动。设备台账、档案、五个任务入口和日志另有直接改动或共同结果组件改动。其余页面走定向回归。

本轮用 NetBox 系列档案与 Netdisco 端口组织方式检查同 UUID 跳转，用 Nautobot 任务实例关系核对结果和重试，用 Oxidized 核对配置版本独立于台账。Tabby 会话上下文与 WinSCP 双栏方向用于控制台及 SFTP 验收。阶段成果复用现有控件和服务。

| 路由 | 本轮改动 | Electron 页面状态 |
| --- | --- | --- |
| `/` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/network/devices` | 按已选 UUID 创建设备任务 | 双尺寸已打开 |
| `/devices/archive` | 搜索表缺逐行操作及失败区分 → 增加打开档案与读取错误，UUID 契约保留 | 双尺寸已打开 |
| `/console` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/devices/:deviceId` | 档案关联与设备操作使用原 UUID | 双尺寸已打开 |
| `/ac-management` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/ac-management/fit-aps` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/ac-management/extensions` | 扩展项与 AP 资料分离 → 增加 FIT-AP 详情入口，保留权限 | BLOCKED，当前隔离配置的功能开关拒绝访问 |
| `/rail-transit/wireless-dashboard` | 告警概览缺后续入口 → 增加轨旁 AP 与光衰入口 | 双尺寸已打开 |
| `/rail-transit/infrastructure` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/rail-transit/base-data` | 关联对象靠再次筛选 → 直达 FIT-AP 和指定 MR 归档 | 双尺寸已打开 |
| `/rail-transit/ground-unattended` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/rail-transit/ground-unattended-replay` | 归档浏览缺明显刷新反馈 → 增加刷新及状态显示 | 双尺寸已打开 |
| `/rail-transit/trackside-ap-business` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/rail-transit/mesh-analysis` | 技术错误占首层 → 业务提示与技术详情分层 | 双尺寸已打开 |
| `/rail-transit/online-mr` | 请求原文占首层 → 读失败显示可理解反馈和详情 | 双尺寸已打开 |
| `/rail-transit/online-mr-analysis` | 回放失败难定位 → 简短说明与技术详情分层 | 双尺寸已打开 |
| `/config-center` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/device-files` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/device-files/diagnostics` | 提交后需找任务 → 直接打开对应任务详情 | 双尺寸已打开 |
| `/file-manager` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/tools/traffic` | 未开始无操作提示 → 补空态和启动入口 | 双尺寸已打开 |
| `/tools/connectivity` | 沿用 Phase 1，纳入界面回归 | 双尺寸已打开 |
| `/tools/wireless-scan` | 结果为空时难判断 → 提供开始与重试反馈 | 双尺寸已打开 |
| `/tools/network-components` | 缺工具时无后续操作 → 增加状态与刷新入口 | 双尺寸已打开 |
| `/tools/network-services` | 未初始化、不可用反馈不清楚 → 补空态及当前操作 | 双尺寸已打开 |
| `/tools` | 搜索无结果难恢复 → 清除筛选回到工具列表 | 双尺寸已打开 |
| `/tasks/diagnostic` | 复用任务结果到设备档案的联动 | 双尺寸已打开 |
| `/tasks/backup` | 复用任务结果到设备档案的联动 | 双尺寸已打开 |
| `/tasks/upgrade_lab` | 复用任务结果到设备档案的联动 | 双尺寸已打开 |
| `/tasks/config_generate` | 复用任务结果到设备档案的联动 | 双尺寸已打开 |
| `/tasks` | 逐设备结果返回原档案，共用结果组件 | 双尺寸已打开 |
| `/settings` | 低频维护动作和常用设置混排 → 收到次级操作入口 | 双尺寸已打开 |
| `/feature-flags` | 退役入口到达后缺后续操作 → 导向版本信息 | 双尺寸已打开 |
| `/logs` | 搜索结果防乱序覆盖，先读可读日志再展开技术原文 | 双尺寸已打开 |

故障与操作验证见 [工作流矩阵](UI_UX_PHASE2_WORKFLOW_MATRIX.md)，逐页证据见 [截图索引](UI_UX_PHASE2_SCREENSHOT_INDEX.md)。
