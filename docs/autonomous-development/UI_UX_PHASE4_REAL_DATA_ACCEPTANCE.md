# Phase 4 真实线路数据

复用 `phase8-replay-hz9` 和 `phase8-replay-hz10`。Electron 明确关闭采集。SQLite 盘点使用 `mode=ro` 和 `query_only`。既有压缩包校验值见 [Phase 3](UI_UX_PHASE3_REAL_DATA_ACCEPTANCE.md)，压缩包未作为测试输入写入。

| 项目 | HZL9 | HZL10 |
| --- | --- | --- |
| 同一筛选下的时间轴与导出 | 真实 UI 筛选 `mesh_linkup`，前后翻页。产品导出器生成 2,308 条数据 | 真实 UI 筛选 `ap_transition`，前后翻页。产品导出器生成 5,161 条数据 |
| 数据范围 | 80,489 条事件，已解析 WMESH 6,818 条 | 616,103 条事件，已解析 WMESH 297,397 条。仅一个就绪归档可在当前 GUI 选择 |
| Quick Ping | 2 个专用历史 Run，Phase 3 保留入口证据 | NOT AVAILABLE，专用历史表为零 |
| LLDP | 真样本 38 条不足以建立确定对端，未关联 | 定向身份验证使用独立夹具，真实对端跳转未验 |
| 配置快照 | NOT AVAILABLE | NOT AVAILABLE |
| 轨旁 AP | 当前工作流未复验 | 当前快照可查，1,006 条。从轨旁表精确跳到档案的交换机端口，验证了 10 条带时间戳的历史变化。AP 侧独立历史光衰未验证 |

两次 CSV 导出前后，隔离索引大小与修改时刻一致。启动会生成隔离运行日志、锁等应用数据。真实历史 CSV 保存在本机 Workspace 报告目录，Git 只记录摘要与证据范围。
