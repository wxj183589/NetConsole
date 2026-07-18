# iPerf3 Windows dynamic-auth 对应源码说明

本目录的运行文件来自用户提供并经 SHA-256 固定的 `iperf-3.21-win64-dynamic-auth.zip`。NetConsole 正式构建和 Agent 构建只校验并复制仓库中的本地文件，不下载、升级或替换任何业务运行工具。

固定发行与源码事实：

- 分发资产：`https://github.com/ar51an/iperf3-win-builds/releases/download/3.21/iperf-3.21-win64-dynamic-auth.zip`，SHA-256 `0d3ac723df5cc7b2ab1851fe9441c14291c6583b6acf8ef81dabee73c145c2eb`。
- ESnet iPerf3 3.21：`https://github.com/esnet/iperf/releases/tag/3.21`，peeled commit `d39cf41526626b4e5a130f115d931cd6cbdffc19`。
- Cygwin 3.6.7-1：官方内容页 `https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.7-1-src`，归档路径 `src/release/cygwin/cygwin-3.6.7-1-src.tar.xz`，大小 `9309160` 字节，SHA-512 `82a190c3516511af7d1305e1bcd4aa0177c1fb584b6468a887a9119565bccd88630b2a3b826d902983a83adefb11545346dcf27616186304d6c66879e1647335`。
- OpenSSL 3.0.19-1 与 zlib 1.3.2-1 的固定 Cygwin source package 索引和版本见 `SOURCE_PROVENANCE.json`。

发布要求：向外部分发该动态包时，发布负责人必须在同一发布渠道提供适用的精确对应源码归档，或依照适用许可证提供有效书面源码提供方案。产品构建不以联网下载替代该责任。GNU GPLv3、LGPLv3、Cygwin Linking Exception 及其他组件许可证正文均随 `licenses/` 目录交付。
