# 本地网络服务

Manager 管理各服务配置、受管目录、生命周期、Windows Job Object、健康及资源快照。Worker 为 HTTP、HTTPS、FTP/FTPS、TFTP、Syslog 提供独立进程入口，iPerf 使用仓库已有受管工具进程。

- `manager.py` 提供统一管理接口。
- `worker.py` 处理受管进程启动握手和控制管道退出。
- `protocols.py` 提供文件分发与 Syslog 接收。
- `ftp.py` 适配 pyftpdlib 权限、TLS 和被动端口范围。
- `paths.py` 限制服务根内路径。
- `log_query.py` 查询各服务轮转日志。

入口为 `backend/api/local_network_services_router.py`，开发约定见 `docs/development/local-network-services.md`。服务运行事实与一次性设备任务分别维护。变更后运行 `tests/test_local_network_services.py`、`tests/test_network_service_resilience.py` 与 `tests/test_service_log_query.py`。
