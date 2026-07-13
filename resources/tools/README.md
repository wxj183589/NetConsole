# NetConsole 运行时工具资源

`resources/tools/` 是随 NetConsole 版本化的第三方运行时工具唯一来源。构建脚本只能从这里白名单复制运行时工具，不得从 `tools/` 或 `apps/agent/tools/` 读取。

当前 Windows x64 白名单：

```text
resources/tools/windows-x64/
├─ fping/
└─ iperf3/
```

Agent 和桌面端正式包内的目标位置仍为 `tools/windows-x64/{fping,iperf3}`，这是交付包内部布局，不是源码来源目录。Agent 不打包 `ipop`；`IPOP.EXE` 是用户自备、不可再分发的桌面端可选外部工具。

## 来源与许可证

- `fping`：`VERSION.txt` 记录为 schweikert/fping v5.5；目录内保留 `COPYING`、`CYGWIN_LICENSE` 和说明文件。
- `iperf3`：当前仓库保留 Windows x64 Cygwin 版 3.20 运行文件及其 DLL；本目录目前没有随包携带的上游许可证文件，补齐来源和许可证/NOTICE 前不得新增或替换来源不明的二进制。

新增平台或工具前，必须记录来源、版本、许可证和同目录运行依赖，并同步构建白名单与测试。缺失工具必须在构建或启动时明确报错，不能静默回退到旧目录。
