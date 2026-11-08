# 物理 AP 信号质量

日期：2026-11-08
分支：`codex-A/mesh-analysis-performance-optimization`
对照基线：`37b0df95a3208d0d03380e76ccfe5419af1422f1`

统计入口为 `mesh_business_statistics.build_mesh_business_statistics()`，API/UI、综合报告和明细导出复用。只取每个来源/采样身份/Radio 中唯一 ACTIVE 的 MR RSSI；STANDBY、空值、0、非数字、NaN/Infinity 不进入 RSSI 分布。

按规范物理 AP MAC 唯一归并，同 AP 多 Radio、重复切入切出合并。复用当前 MeshApLocationSnapshot/Identity projection，不按名称、Peer 前缀或站点模糊推断。Peer Alias 冲突、历史物理投影与当前精确映射冲突归入未识别；原始 Peer 证据继续保留。AP 总数只含可识别物理设备；未识别数是 Peer 观察组数，不是已确认物理 AP 数。

输出平均/最低/最高/P10、有效样本数、弱样本数/比例、首次/最后时间、名称/MAC/站点/区间。P10 使用与已有分位统计一致的线性插值，histogram 精确计算，不使用图表 LOD。

阈值：任务覆盖 > 当前局点默认 > 原有规则资源；未配置的 nullable 阈值继承资源，资源文件与原有全局阈值未修改。P10 >= good 为 GOOD，>= warning 为 WARNING，其余 BAD。弱样本指 RSSI < good。低于有效 minimum_samples 为 INSUFFICIENT；身份未知为 UNRECOGNIZED。默认置信样本量10可由局点/任务修改；不把样本不足判成良好。参数组合 warning > good 返回校验错误，创建导出 Artifact 前冻结。

页面初始只请求业务摘要；卡片点击后请求 `/ap-signal-statistics`。支持等级、精确站点、名称/MAC/Peer 搜索、RSSI 排序、服务端分页。AP 总数点击 RECOGNIZED，与总数口径一致。筛选分页作用于完整聚合结果，不作用于屏幕曲线或当前分页。

可追溯字段包含有效阈值、minimum、grade_metric=ACTIVE_MR_RSSI_P10、rule_version=mesh_business_v1。新分级是新增物理 AP 视角，原 sample/Peer 全局质量分和旧 API 保留。fixture 测试不代表所有现场设备日志已验收。
