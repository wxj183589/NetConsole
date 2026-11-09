# R2.3.1 剩余问题

1. 8 小时长稳定性未执行，不能宣称长期资源、队列、SQLite 或最终一致性 PASS。
2. 当前环境未提供可见桌面截图采集，Electron 仅完成真实进程 smoke 和自动化读取/编译证据。
3. 没有真实现场 Syslog、车辆、AP、AC 控制器或网络故障注入；`FIELD_ACCEPTANCE=NOT_AVAILABLE`。
4. AC 60 秒周期的现场时序和控制器设备侧增量能力未实测；当前实现按完整快照本地 diff，过期/不完整快照不会安全删除。
5. 完整 Local Gate 仍受工作树已有 Mesh/数据根修改、架构 guard、目录 README、HEAD 绑定和安装器 clean-worktree 前置条件影响；这些不是本次 Ground R2.3.1 独立修复范围。
6. 生产安装包 smoke 未执行；Electron isolated smoke 已执行并通过。

下一步：在干净、已集成的候选提交上重跑完整 Gate；在隔离环境执行 8 小时三链路 soak 和真实可见 Electron 截图；之后再安排现场设备/网络验收。
