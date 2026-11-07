# Ground Unattended V2 心跳检测界面 R3 收尾

日期：2026-11-07
Branch：`codex-A/ground-unattended-v2-20261107`
基线：`7063d85d`

## 本轮范围

- 仅调整心跳检测的 DTO 投影、页面展示和详情抽屉；未修改心跳调度、Ping 状态机、并发容量或任务生命周期。
- 设备管理库存与动态采样继续分离。首次进入页面和监测未启动时，已同步 MR 仍从 Ground inventory 投影；停用监测选择时也保留设备清单，不启动采样。

## 字段和数据关联

- 心跳页面、车辆卡片、AP 列表和 MR 抽屉不再展示管理 IP；底层 `ip_states`、Ping、终端和快速 Ping 契约保持不变。
- `AP 名称`统一替换为`接入区间 AP`。后端从 `AcMeshLinkQueryService.list_mrs()` 返回的 `peer_aps` 聚合真实关联，输出 AP 名称、BSSID、AP MAC、RSSI、连接状态、最近观测时间、站点和区间；没有证据时返回空数组，页面显示`暂无关联 AP`。
- `接入站点`来自 AP 关联中的站点集合；不按 IP、MR 名称或列车编号推断。没有关联时显示`未关联站点`。
- 保留 `resolved_ap_name/station/section` 旧字段以兼容已有 API 消费者，新字段为 `associated_aps/associated_stations`。

## UI 优化

- 车辆列表固定为“列车 / CT 端 / CW 端 / 整车状态”四列，CT/CW 均分剩余宽度；详情操作集中在最右侧，点击卡片仍打开对应 MR 抽屉。
- AP 标签最多先显示 3 个，其余显示 `+N`；卡片或展开标签进入抽屉后可查看完整 AP 关系。
- 统计区域增加待检测 MR，并保留累计 Ping、成功次数、丢包次数、平均 RTT、当前丢包率和最近更新时间。数据加载期间不渲染统计数字，避免出现虚假 Total 0。
- 未启动、无采样、暂停和停用分别显示待检测、已暂停或已停止语义，不把未采样设备计为离线或 Ping 失败。
- 心跳页面移除“清空监测设备”入口，只保留重新同步设备与清空心跳数据；清空心跳数据不删除常驻设备。

## 测试结果

- Python 编译：`py_compile` 通过。
- Renderer：`pnpm exec vue-tsc -b` 通过。
- Ground 定向：库存常驻、停用后保留设备、多 AP/站点聚合、21 辆车/42 MR 首次加载及丢包事件共 `21 passed`；Ground API 回归 `38 passed`。统计样本已改为动态 UTC 时间，避免固定日期误判过期。
- Renderer 心跳单测：`7 passed`；Renderer 全量 `198` 个测试文件 / `1388` 个测试中 `197 passed, 1 failed`，唯一失败为既有 `CommandReferenceView` 动态 locale 测试超时，与本轮心跳改动无关。
- Renderer 心跳视觉用例：1920×1080 运行态、多 AP 折叠、MR 抽屉、同步预览、未启动状态及 2048×1091、1672×941 视口共 `4 passed`。
- Electron 隔离开发启动：`dev:codex --isolated-test-data ...` 完成 Backend ready、Renderer warmup 和 Electron startup；未读取或写入真实数据根。启动日志出现既有 workspace route 拒绝提示，不影响 Backend ready。
- 未执行真实设备、AC 认证、生产数据或网络 Ping；未执行 24 小时长稳和原生 DPI 专项。

## 截图证据

截图由真实 Vue Renderer 运行态（Playwright Chromium，非静态 HTML）生成，保存在仓库 `.local` 临时证据目录：

- `heartbeat-01-compact-trains.png`：车辆列表、CT/CW 双卡片和多 AP `+1`。
- `heartbeat-03-monitoring-drawer.png`：MR 详情抽屉、完整 AP/站点字段。
- `heartbeat-05-sync-preview.png`：设备重新同步预览。
- `heartbeat-06-not-started.png`：隔离视觉 Fixture 中监测未启动，10 辆车/20 MR 保留且显示待检测；后端定向 Fixture 另验证 21 辆车/42 MR。
- `heartbeat-08-2048x1091.png`：2048×1091 运行态。
- `heartbeat-09-1672x941.png`：1672×941 运行态。

## 剩余问题

- Electron 本轮完成隔离启动和 Backend ready 检查，截图证据仍来自 Renderer 视觉运行态；真实设备和现场 AC/AP 归属关系尚未验收。
- 本轮不提交、不推送、不合并，保留 R3 第一批所有 dirty 修改。


## 2026-11-08 R3.1 最终集成验收补充

本节只追加后续结果，以上 R3 原始记录保留。完整验收见 [R3.1 最终集成验收](ground-unattended-v2-r3.1-final-integration-audit.md)。

- 使用正式 `dev:codex --isolated-test-data` 启动真实 Electron，原生窗口截图覆盖 1920×1080、2048×1091、1672×941；已补齐主界面、CT/CW、多 AP/站点、MR 抽屉、未启动/运行/停止与 Backend 重启截图。
- 隔离库存验证 21 车/42 MR：启停、暂停/恢复、清空、历史日期/归档、页面刷新、Electron/Backend 正常及异常重启均保留身份；新增/资格移除/删除/重复同步及 AP 站点更新已验证。
- 修复停止快照、同日清空后计数及旧丢包恢复、事件队列并发确认、Quick Ping DTO、父级运行上下文请求取消和 Syslog 去重扫描退化；没有重写通用调度器或 AP Identity。
- 最终 Ground 398 passed/1 skipped；Renderer 全量 198 files/1392 passed（原 locale 超时已最小修复）；Electron 全量 38 files/306 passed；类型/构建、Ruff、编译及 Feature/edition 88 项通过。完整 Python 原始结果、修复复验及最终 guards 见 R3.1 报告，不以专项数量累加冒充全量结果。
- 修复后回环短压 600 秒，59840 条 UDP 全量落库，7 个 SQLite 完整性通过，停止后 Ping/UDP/队列清零，自有进程退出。首轮锁竞争/退出超时失败记录完整保留。
- 限制：现有“暂停”仅暂停深采调度，心跳/AC/Syslog继续；短压有一次 Proactor WinError10054 及空 payload 日志，不能宣称零异常或长期无泄漏；真实设备/现场 AP、安装包及 main 合并后门禁仍未验收。
- Branch/HEAD 保持 `codex-A/ground-unattended-v2-20261107` / `7063d85d`，所有已有 dirty 增量保留；不 commit/push/merge。
