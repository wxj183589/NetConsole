# 轨道交通页面

本目录承载轨旁 AP、车载 MR、Mesh 分析、基础资料、通信监控和综合看板页面。在线采集与离线分析由 Python Service/Job/导出进程提供。

各页面通过对应 API、Store 和 ViewModel 展示查询或受控操作；修改领域字段、图表或导入流程时运行本目录定向测试并同步专题文档。

`RailTransitBaseDataView.vue` 是基础资料唯一入口，默认锁定并通过 revision + Application Service 单事务维护站点、区间、轨旁 AP、车载 MR 和轨旁 AP 规划。规划组件位于 `components/rail-transit/base-data/`；旧独立规划路由只做兼容重定向，不得恢复重复页面或导航。

基础资料、Online MR、Mesh 原始回显和通信日志均消费共享面板、状态和代码 Token；图表配色只从 `theme/echarts.ts` 读取。轨旁 AP 业务页首次加载才使用整表遮罩，后续刷新保留上一次成功数据；接口简称和光衰中文展示只是 presentation，导出通过 Task/Artifact 和 Runtime Adapter 保存。
