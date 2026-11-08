# 车辆段/停车场范围

Mesh 业务统计新增默认开启的 `exclude_depot` 与 `exclude_parking`。两个参数进入 API、统计缓存签名、AP 摘要/分页、单链路分页和链路明细导出任务。排除发生在 ACTIVE/STANDBY 质量判定和风险分段之前：被排除的 ACTIVE 结束当前风险段，被排除的 STANDBY 不作为备链候选。

筛选统一影响物理 AP 总数、各信号等级、AP 列表、单链路区段、涉及 AP 数量、摘要和对应 Excel 派生工作表。原始链路明细、解析库和身份映射保持不变。前端切换会取消旧摘要/明细请求并通过 generation 拒绝迟到响应。

状态：`DEPOT_FILTER_STATUS=PASS`，`PARKING_FILTER_STATUS=PASS`（合成数据）；真实样本未提供。
