# 轨道交通基础设施架构

Phase 1 把基础设施加入现有轨道交通导航，设备管理继续承担通用资产维护。沿用局点与线路一对一的运行模型。

```mermaid
flowchart LR
    UI["基础设施工作台"] --> Base["基础资料应用与查询服务"]
    UI --> Detail["DeviceDetailPanel"]
    Base --> Infra["基础设施关系 Repository"]
    Base --> Legacy["既有基础资料 Repository"]
    Infra --> DB["局点 devices.db"]
    Legacy --> DB
    Detail --> Device["设备详情查询"]
    Device --> DB
    Trackside["轨旁 AP 与 LLDP"] --> DB
    AC["AC 管理"] --> Current["按 AC UUID 隔离的 FIT-AP Current"]
    Ground["Ground、无线看板、MESH、Online MR"] --> Legacy
```

线路下按控制中心（COCC、BOCC）、正线车站、车辆段与停车场、车载设备组织。站点下显示正式绑定的设备，交换机下只展示有明确物理连接证据的 AP。区间属于线路拓扑，在站点详情按稳定端点引用展示。列车下显示明确建立的 CT/CW 设备关系。缺少关系时显示待配置。

设备分组保留资产管理语义。建设阶段、工程归属、调试状态、采集与统计资格属于工程上下文。旧 `project_phase`、`work_scope_status` 的现有读写继续服务各模块，变更入口前逐个验证消费者及旧数据。

车内通信检测 RETIRED。地面无人值守和无线看板保留共享列车与 MR 事实，历史任务处理器为旧记录保留兼容。
