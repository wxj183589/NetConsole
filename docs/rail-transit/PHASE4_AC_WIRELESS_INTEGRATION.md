# AC / Wireless 工程联动

AC overview与导出身份只读附加统一engineering_context：物理节点、服务站点及关系范围与FIT-AP Current数量/历史独立。不使用服务站点反推AP身份，不跨ac_device_uuid合并Current。

Wireless统一返回engineering_contexts和工程revision；TTL缓存命中前检查Site工程revision，关系变更即失效。站点/区间/项目稳定ID筛选只筛工程设备上下文和相关列车列表；原summary运行指标保持原算法/范围，不用工程资料重算历史指标。上下文失败明确unavailable，原运行分析独立保留。修复原默认构造误向MeshAnalysisQueryService传入不支持参数的既有缺陷（真实构造测试发现）。

AC/Wireless/MeshLink专项44 passed（12.24s）。页面筛选和实际Electron展示在Phase4.6验收。无组网/主备/身份合并规则变化。

站点筛选同时识别实际安装站点与明确的 AC 工程服务站点；使用现有站点 ID / node UID，不将服务站点转成 AP Current 所属。当前服务名称随工程目录改名刷新，历史查询仍使用关系事件名称。
