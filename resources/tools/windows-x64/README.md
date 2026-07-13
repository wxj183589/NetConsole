# Windows x64 工具资源目录

这是源码资源目录。Agent 构建脚本从这里白名单复制 `fping` 和 `iperf3` 到交付包内的 `tools/windows-x64/`；运行时不直接扫描仓库根 `tools/`，也不使用 `apps/agent/tools/`。

```text
windows-x64/
├─ iperf3/
│  ├─ iperf3.exe
│  ├─ cygwin1.dll
│  ├─ cygcrypto-3.dll
│  └─ cygz.dll
└─ fping/
   └─ fping.exe
```

Cygwin 版 iPerf3 的 exe 和 DLL 必须位于同一目录。fping 在 Windows Agent V1 中仅做状态检测，不接入 `ping_probe`。`mr_collector` 是 Agent 自建 sidecar，不属于本目录的第三方运行时工具。
