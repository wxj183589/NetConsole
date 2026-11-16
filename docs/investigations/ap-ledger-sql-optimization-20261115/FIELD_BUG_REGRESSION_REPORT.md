# 现场故障回归报告

## 已覆盖的代码级故障

- LLDP 邻居侧 `Port ID` 不再误写为交换机接入端口；正式端口取 `Local Interface`。
- 不再从 AP 名称、IP、MAC 尾号推断站点；站点必须来自显式资料范围。
- 非 AP LLDP 邻居不进入正式台账。
- AC 运行态缺失时，Mesh-Link 可使用当前 Site 的正式静态 AP MAC 资料；不依赖在线 AC。
- 读查询不再因为 GET 触发 WAL 初始化或创建缺失数据库。
- AP 台账来源、阶段、设备、时间和邻居侧端口进入可审计 payload。
- 台账页面支持交换机、端口、建设阶段、来源筛选，并按站点/交换机/端口自然排序。

## 当前状态

代码级回归：`PASS`。
现场设备登录、真实 AC V5、真实交换机 LLDP 重新采集、无人值守长跑、Electron GUI 和安装包：`NOT RUN`。
任务状态：`LOCAL_PASS / FIELD_VALIDATION_PENDING`。

未提供的指定二期资料和真实现场复测不被本报告标记为通过。
