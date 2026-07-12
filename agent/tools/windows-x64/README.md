# Windows x64 工具目录

Agent 只使用配置中指定的新标准目录，不扫描旧目录：

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

Cygwin 版 iPerf3 的 exe 和 DLL 必须位于同一目录。fping 在 Windows Agent V1 中仅做状态检测，不接入 `ping_probe`。
