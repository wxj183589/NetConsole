# AC Application Service

本目录提供 AC/FIT-AP Web 用例的应用编排，把查询、受控更新和任务调用连接到领域 Service/Repository。它不解析页面输入以外的协议细节，也不直接实现 Router。

主要入口为 `web_application_service.py`；数据与命令由相邻服务和 Repository 提供。修改后运行 AC Web API、Job 和权限边界测试。
