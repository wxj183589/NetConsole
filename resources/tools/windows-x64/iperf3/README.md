# iPerf3 3.21 Windows x64 dynamic-auth

本目录固定使用 `ar51an/iperf3-win-builds` 的 `iperf-3.21-win64-dynamic-auth.zip`。运行文件为 `iperf3.exe`、`cygwin1.dll`、`cygcrypto-3.dll` 和 `cygz.dll`，四个文件必须位于同一目录；Agent 和桌面端构建只从这里复制到交付包内的 `tools/windows-x64/iperf3/`。

`SOURCE_PROVENANCE.json` 记录 GitHub Release、asset ID、ZIP SHA-256、四个文件 SHA-256 和对应上游源包。`CORRESPONDING_SOURCE.md` 固定 Cygwin 3.6.7-1 源码归档及对外发布方案；`licenses/` 同时保留 GPLv3、LGPLv3、Cygwin Linking Exception、构建仓库、iPerf3、OpenSSL 与 zlib 的许可证材料。构建和安装包 smoke 必须核对这些本地文件，任何替换、缺失或哈希漂移都会阻止发布。
