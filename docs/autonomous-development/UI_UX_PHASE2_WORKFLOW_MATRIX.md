# Phase 2 业务工作流矩阵

| 工作流 | 状态 | 隔离验证与缺口 |
| --- | --- | --- |
| 台账新增、编辑与搜索 | PASS | 从界面新增并编辑测试设备，按名称定位。同一 UUID 进入设备档案 |
| 台账到诊断、失败、结果、重试、日志和档案 | PASS | 本机拒绝连接夹具产生真实失败。查看逐设备结果、重试父 ID、日志深链与原设备档案 |
| 档案与控制台 | PASS | 已打开同设备控制台目标。从档案打开接口页 |
| LLDP、光模块、配置历史 | PARTIAL | Phase 1 的非空配置及差异证据保留。本轮未重新点击全部现有历史记录及对端条目 |
| 无线与轨交组织 | PASS | 实际打开 FIT-AP、光衰台账、组织设备详情 |
| 轨旁关联光衰与归档 | PARTIAL | 可打开查询入口，隔离局点缺少关联光衰明细及可选归档 |
| 本地到远端文件 | PASS | 通过实际 Electron 上传至回环 SFTP，29 字节源文件与远端文件 SHA-256 相同，刷新后列表出现文件 |
| 日志搜索和详情 | PASS | 按现有事件查询，打开可读详情并确认技术原文默认折叠 |
| 删除设备 | BLOCKED | 隔离操作收到 `ASSET_DELETION_NOT_AUTHORIZED`，测试设备保留 |
| 配置下发、实机固件与全部高级操作 | NOT VERIFIED | 未执行未经授权的设备写入；正式安装与发布不在本阶段范围 |

[设备工作流](../../../reports/tests/legacy-ui-ux-phase2/DEVICE-WORKFLOW.md) · [无线轨交工作流](../../../reports/tests/legacy-ui-ux-phase2/rail-workflow-verification.md) · [文件上传](../../../reports/tests/legacy-ui-ux-phase2/sftp-loopback.png) · [日志详情](../../../reports/tests/legacy-ui-ux-phase2/log-workflow.png)
