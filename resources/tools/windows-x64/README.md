# Windows x64 工具资源目录

这是源码资源目录。Agent 构建脚本从这里白名单复制 `fping` 和 `iperf3` 到交付包内的 `tools/windows-x64/`；运行时不直接扫描仓库根 `tools/`，也不使用 `apps/agent/tools/`。

```text
windows-x64/
├─ iperf3/
│  ├─ iperf3.exe
│  ├─ cygwin1.dll
│  ├─ cygcrypto-3.dll
│  ├─ cygz.dll
│  ├─ SOURCE_PROVENANCE.json
│  ├─ CORRESPONDING_SOURCE.md
│  └─ licenses/
└─ fping/
   ├─ fping.exe
   ├─ cygwin1.dll
   ├─ SOURCE_PROVENANCE.json
   ├─ BUILD_RECIPE.md
   ├─ CYGWIN_ICMP_COMPAT.patch
   ├─ CORRESPONDING_SOURCE.md
   └─ COPYING / GPL-3.0 / COPYING.LIB / CYGWIN_LICENSE
```

Cygwin 版 iPerf3 的 exe 和 DLL 必须位于同一目录；当前固定为用户提供的 3.21 dynamic-auth 资产并按 SHA-256 验证。fping 5.5 是带已归档 Cygwin ICMP 兼容补丁的独立高频 Ping 能力，`ping_probe` 仍是 TCP Connect 探测，两者不能混同。两套 Cygwin 运行时均随附 GPLv3、LGPLv3、链接例外和精确对应源码说明。所有正式包只复制本目录本地文件，构建阶段不下载或替换业务工具。`mr_collector` 是 Agent 自建 sidecar，不属于本目录的第三方运行时工具。
