# NetConsole 运行时工具资源

`resources/tools/` 是随 NetConsole 版本化的第三方运行时工具唯一来源。构建脚本只能从这里白名单复制运行时工具，不得从 `tools/` 或 `apps/agent/tools/` 读取。

当前 Windows x64 白名单：

```text
resources/tools/windows-x64/
├─ fping/
└─ iperf3/
```

Agent 和桌面端正式包内的目标位置仍为 `tools/windows-x64/{fping,iperf3}`，这是交付包内部布局，不是源码来源目录。Agent 不打包 `ipop`；`IPOP.EXE` 是用户自备、不可再分发的桌面端可选外部工具。

Agent 的 Python MR sidecar 是 `apps/agent/mr_collector_py/` 的自建构建产物，交付包内目标位置为 `tools/windows-x64/mr_collector/`，不属于本目录的第三方工具白名单。

## 来源与许可证

- `fping`：固定为 schweikert/fping v5.5 加 `CYGWIN_ICMP_COMPAT.patch` 的本地 Cygwin 3.6.9-1 构建；`BUILD_RECIPE.md`、`CORRESPONDING_SOURCE.md` 和 `SOURCE_PROVENANCE.json` 固定实际补丁、参数、源码归档和二进制哈希，GNU GPLv3、LGPLv3 与 Cygwin Linking Exception 正文随目录保留。
- `iperf3`：固定为用户提供的 `ar51an/iperf3-win-builds` 3.21 `iperf-3.21-win64-dynamic-auth.zip`；目录内 `SOURCE_PROVENANCE.json` 记录发行资产和四个文件哈希，`CORRESPONDING_SOURCE.md` 固定 Cygwin 3.6.7-1 源码归档与发布责任，`licenses/` 保留 GPLv3、LGPLv3、iPerf3、Cygwin、OpenSSL、zlib 与构建仓库许可证。发行 ZIP 只作为离线来源核验证据，正式构建不下载或解压远程工具，只复制本目录已版本化并通过哈希校验的本地文件。

新增平台或工具前，必须记录来源、版本、许可证和同目录运行依赖，并同步构建白名单与测试。桌面端和 Agent 构建都会校验 fping/iPerf3 的来源、二进制与许可证哈希，并拒绝工具目录中的额外文件；缺失或漂移必须明确失败，不能联网补齐或静默回退到旧目录。
