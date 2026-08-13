# AP Identity 服务

本目录提供 AP/Radio/BSSID/Peer 的归一化模型、局点统一索引、批量查询、适配器和 resolver。统一索引与部分消费者解析已经进入生产，shadow/diagnostics 仍作为失败隔离的旁路；部分接管不等于全系统接管。

主要入口为 `index_builder.py`、`query_service.py`、`models.py`、`normalizers.py`、`adapters.py` 和 `resolver.py`；解析不确定性通过 matched/unresolved/ambiguous、revision 和 confidence 表达。修改优先级时运行 AP Identity 与登记消费者测试。

## 用途与边界

本目录负责身份解析段，不负责采集、主备链、拓扑、光衰、页面或报告业务规则。MESH、Ground、Online/Vehicle MR、Wireless 和轨旁 AP 业务/导出的高频解析已使用统一入口；AC Mesh-Link、基础资料直接 JOIN、部分报告和设备/LLDP topology binding 仍保留显式兼容边界。

## 主要入口

`models.py` 定义兼容/诊断模型，`normalizers.py` 处理 MAC/名称归一化，`adapters.py` 适配来源，`resolver.py` 计算候选与置信度；`index_builder.py` 构建局点索引，`query_service.py` 提供精确单值/批量查询、revision 和索引健康状态。

## 依赖关系

身份服务被 AC、MESH、Ground、Online/Vehicle MR、Wireless、轨旁 AP 和导出调用，依赖局点 `devices.db` 与解析后的领域记录，不在普通查询中连接设备或重建索引。生产 Service 必须保留 raw 事实、revision、matched/unresolved/ambiguous 和显式兼容/shadow 边界。

## 数据与状态

查询输出带 matched/unresolved/ambiguous、identity revision、来源、规则、confidence 和 diagnostics。生产消费者只能写自己的可重算投影，不得回写 AC/Base 主身份；shadow/diagnostics 不写业务结果，也不得改变 Job/Export 终态。

## 测试与修改

修改来源优先级、MAC/BSSID 归一化、候选判定、revision 或诊断字段时先执行 L3 Consumer Audit，并运行 AP Identity、MESH、Ground、Online/Vehicle MR、Wireless、Trackside、AC/Base、shadow 和导出消费者测试。

## 生成与清理

身份计算不生成独立运行目录；诊断/报告由上层 Export/Repository 管理，测试样本使用脱敏 fixture 和临时目录。

## 相关文档

参见 [AP Identity](../../../../docs/AP_IDENTITY.md) 和 [重构地图](../../../../docs/architecture/REFACTOR_MAP.md)。模型、消费者、展示/脱敏、观测和导出边界以 `docs/AP_IDENTITY.md` 为唯一活动 SSOT。
