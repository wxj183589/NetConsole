# NetConsole MR Collector Sidecar

这是 Windows Agent 调用的 Python + Netmiko 车载 MR 在线采集器。Go Agent 负责 Web/API、任务生命周期、托盘和 ZIP；本程序负责 Netmiko、MR raw、fping/iPerf 跟随采集以及 `view/*.json` 轻量实时预览。

```bat
\.venv\Scripts\python.exe -m pip install -r requirements-build.txt -c constraints.txt
apps\agent\scripts\build_windows.bat
```

总构建脚本优先复用仓库 `.venv` 中的 PyInstaller；构建临时产物为 `dist/agent/.build-windows-x64/mr_collector/dist/netconsole-mr-collector.exe`。脚本会将它复制到交付包内的 `tools/windows-x64/mr_collector/`，失败或缺失时整个 Agent 构建失败关闭；它是 Agent 自建 sidecar，不属于 `resources/tools/` 第三方运行时工具白名单。

命令、raw 文件名和 session 目录与 `src/netconsole/services/online_mr/` 保持一致；停止由 Agent 创建 `stop.request` 文件触发。sidecar stdout/stderr 使用 UTF-8，所有 JSON 状态写入均使用带锁的原子替换。
