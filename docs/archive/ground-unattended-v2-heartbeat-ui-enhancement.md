# Ground Unattended V2 心跳 UI 与 AP 综合动态监测

日期：2026-11-07。仓库：`D:\study\NetConsole-Workspace\NetConsole`。Branch：main；开始 HEAD：`9031d00017cecf8802f34a96f136bbf01007d862`。本专项保持工作树未提交；未修改真实业务数据，未连接设备。

## 实施结果

心跳页改为每车一行的 CT / CW 独立卡片，显示全局五项计数、当前实际 RTT、主备管理 IP、MR 自身 AP 身份和位置；服务端执行列车状态、站点、关键词、异常筛选及列车分页。`CT_ONLY` 始终表示仅 CT 可达。仅有历史 MR 快照而缺少整车快照时，以 UNKNOWN 列车壳保留真实 MR 事实，不推算整车在线。

MR 自身名称、站点和区间复用 AC 查询 API 的精确 UUID / physical MAC 身份契约；禁止用当前 Peer AP 名称或位置替代。AC data_status 与 Ping 在线状态独立。当前 RTT 只来自当前运行、活动目标的近期真实有效探测；历史运行不显示当前运行 RTT。

点击、右键或操作菜单进入同一个 MR 综合抽屉，默认 60 分钟、5 秒刷新，支持 1 / 10 / 30 / 60 分钟、自定义历史范围（正区间且最多 24 小时）、调整刷新、暂停、全屏和原始事件查看。RTT（ms）、单包丢包（0 / 100 %）及 Peer 证据区间共用时间轴；失采空白、失败 RTT 和未知 Peer 不填零、不连接补齐。累计与 1 / 10 / 30 / 60 分钟丢包率按实际有效包计数，剔除 warmup，独立于图表下采样；查询预算耗尽时明确提示统计可能不完整。

页面、运行、MR 或可见性切换会取消请求和定时器；generation 检查阻断迟到结果。图表单实例使用 ResizeObserver、主题订阅和销毁清理；刷新保留缩放、替换曲线，禁止 connectNulls 与 dirty rectangle。

## 数据来源、精度和边界

- Ping 沿用既有 raw query 的有界文件查询、样本预算和 diagnostics。为同时提供四个窗口计数，监测请求的读取范围至少向前扩展 60 分钟，显示图表仍使用用户选择的范围。
- Mesh / AC 直接读取既有 Ground 索引，`mode=ro`、`query_only`、同一只读事务、精确 site / run / MR 条件，不创建 schema、不迁移、不写入。两个查询各最多保留 500 行；第 501 行触发截断标记。为兼容持久化时间字符串的 UTC offset，SQL 接收时间候选范围扩大前后 14 小时，再按 UTC 精确过滤；高密度外围数据可能提前触发预算，界面保留警告。
- Mesh 使用 canonical event_time 并同时保留 device_time / receive_time / event_time_source / data_quality。仅相邻且 BSSID 连贯的真实切换证据闭合区间；冲突、缺失和末次证据之后为 UNKNOWN。没有插值持续连接。
- AC fallback 仅相邻 fresh / recent、同一 physical peer MAC、间隔不超过 30 秒的实际采样闭合；无末尾延伸，与 Syslog 重叠时优先 Syslog。physical peer MAC 不冒充 radio BSSID。AC 采样区间不能证明精确连接或断开时刻。
- 原始日志按点击事件的接收时间窄窗、同 MR / run 查询，必须同时匹配 raw_file_id 和 raw_line_number。找不到则提示，不用相邻日志代替；迟到日志的接收时间不在范围内时不会强行归入图表。
- 终端复用现有 UUID preflight 与 launcher 安全入口，仅支持该设备主 IP，界面明确标注“主 IP”。备用 IP 终端直连需要现有安全入口新增能力，本次没有 host override。

## L3 契约与消费者

| 契约 | 变化 | 消费者与兼容性 |
| --- | --- | --- |
| GET `/heartbeat` | 可选过滤、分页；追加 totals / stations / 自身身份 / current_rtt_ms | HeartbeatPage；旧调用参数与旧字段保留，TypeScript 追加字段可选 |
| GET `/mr/{mr_uuid}/monitoring` | 新增综合 DTO | MrMonitoringDrawer；精确 MR 查询，未知 MR 返回结构化错误 |
| GroundPingSeriesDTO | 追加 window_statistics | 综合抽屉；旧 Ping series 消费者保留原字段语义 |
| AC list_mrs | 复用自身身份字段，不读取 Peer 位置 | 心跳服务只读消费，AC 不改变心跳状态机 |
| fleet latest_mr_rtts | 当前 run、活动 target、近期样本只读 getter | 心跳服务；run 隔离、失效样本无 RTT |
| Ground 索引 | 无表和 schema 修改 | monitoring.py 已登记 storage registry 和 direct SQL 只读边界 |

未修改任一 IP 成功即在线、MR 10 秒、整车双端 120 秒、恢复确认 2 次的状态规则。

## 验证

```text
.venv\Scripts\python.exe -m pytest tests/test_ground_unattended_monitoring.py tests/test_ground_unattended_api.py -q --disable-warnings --maxfail=1
pnpm exec vitest run src/views/rail-transit/HeartbeatPage.test.ts src/components/ground-unattended/MrMonitoringDrawer.test.ts src/components/ground-unattended/mrMonitoringChartOptions.test.ts
pnpm exec vue-tsc -b --pretty false
pnpm exec playwright test tests/visual/e2e/heartbeat-monitor.visual.spec.ts --project='1920x1080@100%' --project='2560x1440@100%' --workers=1
```

Python 两模块 45 passed；原 heartbeat / fleet 27 passed。Vue 三文件 7 passed；vue-tsc PASS。Chrome HTTP Mock 两个分辨率 2 passed，覆盖 10 车紧凑列表、CT_ONLY 命名、右键菜单、统一抽屉、Mesh 原文和关闭；无 pageerror、无未 Mock API。截图人工查看后修复图例与缩放条重叠、RTT 过多小数以及缺失 ECharts 模块导入。

截图为合成数据真实 Vue 运行画面，位于仓库 `.local/tests/renderer-visual/heartbeat-monitor.visual-H-a7ef2--unified-MR-evidence-drawer-1920x1080-100-` 和相应 `2560x1440-100-` 目录，文件 `heartbeat-01-compact-trains.png`、`heartbeat-02-context-menu.png`、`heartbeat-03-monitoring-drawer.png`、`heartbeat-04-mesh-provenance.png`。不作为真实设备采集验收。

历史查询单测曾因 TestClient 启动恢复 worker 与测试手动改变 run 状态产生竞态；该只读契约测试固定禁用其 app 的 Supervisor.start，避免无关恢复逻辑覆盖测试状态，未改生产恢复代码。

## 尚待总体验收

全仓 FULL Gate、Electron 系统生命周期、连续一小时运行及统一交付结论由最终集成验收报告记录。真实设备、真实主备 IP 终端、跨机器和生产数据验收未执行。终端备用 IP、没有原始日志的历史记录、超出有界查询预算的事实，以及 AC 快照间连续性均保持可见限制。
