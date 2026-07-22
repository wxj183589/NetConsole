# Qt 业务迁移说明

本功能的历史事实源来自 Git 历史中的 Qt 页面和 Worker。迁移目标是保留点表、节点映射、检测任务和结果语义，不恢复 Qt 页面、Qt 入口或第二套任务模型。

| 能力 | 当前 Electron/Python 归属 | 状态 |
| --- | --- | --- |
| 固定六节点拓扑 | `TrainCommunicationQueryService` + Vue `FixedTrainTopology` | 已接入 |
| 点表读取/校验/revision | `TrainCommunicationPointTableService` | 已接入 |
| 点表编辑/导入/导出 | `RailTransitWebApplicationService` + 现有点表弹窗 | 已接入，待真实桌面验收 |
| 检测任务 | `car_network_diagnostic` Task Center | 已复用 |
| VRRP 虚拟 IP 静态展示 | `TrainCommunicationQueryService` + Vue `FixedTrainTopology` | 已接入；无主备状态检测 |
| 跨 TC 聚合 | `TrainCommunicationQueryService` | 已接入 |
| 真实设备检测 | 现有诊断 Worker/设备连接基础设施 | 真实设备待验收 |

未验证的设备、命令和现场结果不得在文档或页面中标记为完成。SNMP Center、无线勘测和 Qt 运行时不属于本迁移范围。
