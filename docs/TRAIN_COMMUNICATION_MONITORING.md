# 在线列车车地通信检测

## 定位

阶段 5C-7A 在 `/rail-transit/train-communication` 增加只读统一展示页，Feature key 为 `web.train_communication_monitoring`。页面按正式列车分别展示 MR-CT 与 MR-TC，并聚合轨旁 AP、Mesh-Link、Online MR、fping、iPerf、任务与采集包；车载 MR 不是普通 WLAN 客户端。

本页只用于现场轻量监控和数据定位，不启动、停止或强停 Online MR，不连接 AC 或 Agent，不修改基础资料、快照、Session metadata/raw，不创建 Task，也不生成正式分析报告。

## 数据来源和优先级

| 数据 | 首选来源 | 安全回退 | 缺失处理 |
| --- | --- | --- | --- |
| 列车、MR 静态身份 | 当前局点 `devices.db` 正式基础资料 | 无 | 不从临时包名推测 |
| Mesh-Link 与 Peer AP | 最新 AC Mesh-Link 快照 | 过期快照明确标记 `stale`；再用 Session 轻量预览 | 返回 `unknown` |
| 站点、区间、里程、方向 | 快照已精确关联的正式 AP 扩展资料 | Session `display_context` 仅作采集上下文 | 不按名称猜测 |
| 采集状态 | 活动 Online MR Session | 最近终态 Session、Agent 已导入 Session | `no_data` |
| fping/iPerf | 活动 Session 的受控 `view/*.json` | 已落盘最终摘要或包内已导入事实 | 显示“无数据” |
| 任务 | 当前局点 `tasks.db` 只读 Query Service | 无 | 空列表 |
| 原始片段 | 当前 Session 的受控 raw-tail 白名单 | 无 | 中文空状态，不返回 500 |

AC 快照与 Online MR 预览的 Peer 名称或 MAC 不一致时返回 `source_conflict` warning，继续展示优先级更高的 AC 事实，不静默覆盖。所有返回引用均为稳定 ID 或局点内相对引用，不返回密码、Token 或主机绝对路径。

## 状态

- `normal`：至少一条新鲜在线 Mesh-Link，且既有来源未报告告警；
- `warning`：单端 MR 离线、数据部分完整、光衰告警、已有指标告警或来源冲突；
- `critical`：全部已登记 MR 失联，当前关联 AP 离线、采集失败或已有来源报告严重状态；
- `stale`：只能取得过期数据；
- `unknown`：没有足够事实。

聚合层只使用已有状态与阈值，不新增 RSSI、丢包或带宽业务判定标准。CT/TC 连接不同 AP 时分别显示，不合并为单一虚假值。

## API

以下接口全部为 GET-only：

```text
GET /api/rail-transit/train-communication/summary
GET /api/rail-transit/train-communication/trains
GET /api/rail-transit/train-communication/trains/{train_id}
GET /api/rail-transit/train-communication/mrs/{mr_id}
GET /api/rail-transit/train-communication/mrs/{mr_id}/preview
GET /api/rail-transit/train-communication/mrs/{mr_id}/raw-sources
GET /api/rail-transit/train-communication/mrs/{mr_id}/tasks
GET /api/rail-transit/train-communication/mrs/{mr_id}/packages
```

受控 raw 内容继续调用 Online MR 的 `/api/online-mr/sessions/{session_id}/raw-tail`。逻辑名称固定为 Mesh-Link、空口、fping 样本/汇总/原始输出、iPerf Client、切换历史和 Collector 输出；前端不能提交文件路径。

## 动态刷新

- 有活动会话时总览/列表每 2 秒、选中 MR 约 1.5 秒刷新；无活动会话时均为 10 秒；
- 原始片段只在折叠面板展开时每秒读取当前 Tab 的 tail；
- 同类请求未完成时不重入；页面隐藏、抽屉关闭或组件卸载后停止相应定时器；
- 连续失败三次后保留最后一次成功数据，提示失败并降频至 15 秒。

后端一次批量读取正式 MR、列车、Mesh-Link、Session 和 Task 索引，再在内存精确关联。原始文件只读取尾部，不加载全量历史 raw。

## 当前边界

- LOCAL 启停仍由 Legacy Qt 入口负责；
- Agent 导入 Session 只读展示，`executor=AGENT` 远程执行仍未开放；
- Agent 包下载/导入仍在现有 Qt Agent 包入口或 Agent 控制中心完成；
- 本页不做正式 Mesh 离线分析、报告、Excel 导出、删除或写操作；已有正式分析结果通过独立的 [Mesh 分析 Web 页面](MESH_ANALYSIS_WEB.md) 查看。
- 本页的列表和摘要可被 [轨道交通无线综合看板](RAIL_TRANSIT_WIRELESS_DASHBOARD.md) 只读复用；综合看板继续保持 CT/TC 独立，不重新计算通信状态或阈值。
