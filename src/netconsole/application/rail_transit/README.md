# 轨道交通 Application Service

本目录编排轨道交通 Web 用例，把基础资料、车载通信、Mesh-Link 和相关只读聚合连接到领域查询服务。采集、分析和导出仍由各自 Service/Job/Export 负责。

主要入口为 `web_application_service.py`；修改聚合字段或权限时运行对应 API、ViewModel 和页面测试。
