# 包内工具进程入口

本目录提供可被受管 Backend/Worker 进程调用的 Python 工具入口，目前包括 Export Worker 主模块。它不是用户任意命令接口，也不保存运行数据。

主要入口为 `export_worker_main.py`；执行协议由 Export Process 定义，数据路径由 PathResolver 提供。修改启动参数或进程通信时运行导出进程和安全测试。
