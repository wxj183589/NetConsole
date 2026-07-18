# Online MR 工作进程

本目录封装在线 MR 的 iPerf3 与韧性 SSH Worker，负责受控采集执行、重试和停止边界。任意命令、凭据和会话目录均由上层服务白名单约束。

主要入口为 `iperf3_worker.py`、`ssh_resilient_worker.py`；长耗时执行通过 Job/Session 管理。修改重试、停止或日志行为时运行 Online MR/Traffic 定向测试。
