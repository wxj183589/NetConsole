# NetConsole MR Collector Sidecar

这是 Windows Agent 调用的 Python + Netmiko 车载 MR 在线采集器。Go Agent 负责 Web/API、任务生命周期、托盘和 ZIP；本程序负责 Netmiko、MR raw、fping/iPerf 跟随采集以及 `view/*.json` 轻量实时预览。

```bat
cd agent\mr_collector_py
pip install pyinstaller netmiko paramiko cryptography
build_windows.bat
```

产物：`agent/tools/windows-x64/mr_collector/netconsole-mr-collector.exe`。

命令、raw 文件名和 session 目录与 `netconsole/services/online_mr/` 保持一致；停止由 Agent 创建 `stop.request` 文件触发。sidecar stdout/stderr 使用 UTF-8，所有 JSON 状态写入均使用带锁的原子替换。
