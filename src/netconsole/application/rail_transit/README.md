# 轨道交通 Application Service

本目录编排轨道交通 Web 用例，把基础资料、车载通信、Mesh-Link 和相关只读聚合连接到领域查询服务。采集、分析和导出仍由各自 Service/Job/Export 负责。

主要入口为 `web_application_service.py` 和 `base_data_application_service.py`。后者负责基础资料编辑会话、字段/引用校验、revision 冲突和统一事务，Router 不编排 SQL。轨旁 AP 业务导出在此保留 Artifact 后提交既有 `trackside_ap_business` ExportJob，Renderer 不传入当前表格行也不生成工作簿。修改聚合字段或权限时运行对应 API、ViewModel 和页面测试。
