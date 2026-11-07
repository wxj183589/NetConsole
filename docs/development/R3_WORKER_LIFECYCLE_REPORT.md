# R3 Worker 生命周期报告

Supervisor 已负责启动、停止、恢复和异常收口；Quick Ping 子线程、压缩线程和 Syslog 线程均有停止事件与 join/超时处理。Core 重启时会扫描运行记录、Raw 文件、Quick Ping manifest 和 reservation，标记不可安全继续的任务为 INTERRUPTED/FAILED，并保留原始证据。

Windows Service、Job Object、单实例 Mutex 和安装卸载行为仍需在目标安装环境验证，本轮没有修改现有安装方式。
