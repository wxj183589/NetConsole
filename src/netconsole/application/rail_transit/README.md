# 轨道交通 Application Service

本目录编排轨道交通 Web 用例，把基础资料、车载通信、列车 Mesh-Link 和相关只读聚合连接到领域查询服务。`VehicleMrOnlineQueryService` 复用 `AcMeshLinkQueryService` 形成每列车 CT/TC 单一公开 DTO，不复制 AP/MR 匹配规则；采集、分析和导出仍由各自 Service/Job/Export 负责。

主要入口为 `web_application_service.py`、`base_data_application_service.py` 和 `mesh_bundle_application_service.py`。MESH 导入应用服务通过显式 POST 从正式 VehicleMr 幂等准备内部 Profile，并统一 ZIP/LOG/GZ/文件夹预览；普通 GET 不写 catalog。基础资料应用服务负责编辑会话、字段/引用校验、revision 冲突和统一事务，Router 不编排 SQL。轨旁 AP 业务导出在此保留 Artifact 后提交既有 `trackside_ap_business` ExportJob，Renderer 不传入当前表格行也不生成工作簿。
