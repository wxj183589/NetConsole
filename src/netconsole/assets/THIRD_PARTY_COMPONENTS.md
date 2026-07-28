# NetConsole 第三方组件说明

本产品由 Electron 43.1.1、Chromium 150.0.7871.114、Node.js 24.18.0、Python Backend 运行时和版本化网络工具组成。机器可读组件、版本、用途、PURL、许可证和工具哈希见同目录 `open_source_notices.json`；Backend 构建会在同目录生成 CycloneDX 1.5 `sbom.cdx.json`。

Windows 冻结 Backend 随包包含 `tzdata` 2026.3 的完整 IANA 时区数据库，由 PyInstaller 标准 `hook-tzdata.py` 收集；调度继续使用 Profile 中的 IANA 时区名称，不依赖 Windows 系统时区库或固定 UTC 偏移。

正式运行时不包含 Qt/PySide/PyQt、shiboken、QFluentWidgets、SIP 或 Qt plugins。Electron 安装包 smoke 会再次扫描这些 marker，并确认 Electron/Chromium Notice 与 SBOM 均存在且没有未知许可证。

fping 与 Cygwin Runtime 分别登记；实际 v5.5 派生补丁、构建配方、GPLv3/LGPLv3/链接例外、对应源码说明和来源清单随工具目录保留。iPerf3 固定为用户提供并经哈希核验的 `ar51an/iperf3-win-builds` 3.21 `win64-dynamic-auth` 发行资产，iPerf3、Cygwin 3.6.7、OpenSSL 3.0.19、zlib 1.3.2 和内嵌 cJSON 分别进入 Notice/SBOM；Cygwin 精确源码归档、四个运行文件 SHA-256 和完整许可证文本随工具目录保留。正式构建只复制本地版本化工具并拒绝额外文件。IPOP v4.1 是用户自备外部程序，不属于 NetConsole 依赖且不得打包。
