# FastAPI API

本目录实现 HTTP/WebSocket Router、DTO 适配和依赖注入边界。Router 不得直接连接设备、SQLite、导出进程或实现业务状态机。

主要入口为各领域路由模块和 `main.py`；用例由 Application/Query Service 提供。修改接口后运行对应 API、未认证边界、架构分层测试。
