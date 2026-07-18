# fping / Cygwin 对应源码说明

本目录中的 `fping.exe` 是 fping 5.5 加仓库归档兼容补丁后的 Cygwin x86_64 本机构建，`cygwin1.dll` 来自 Cygwin 3.6.9-1。NetConsole 的正式构建只校验并复制本目录中的版本化文件，不在构建时下载或替换工具。

固定源码位置：

- fping 5.5：`https://github.com/schweikert/fping/releases/tag/v5.5`，提交 `06f9481ef3cf79c2aa973718366fb13927777689`；实际派生改动见 `CYGWIN_ICMP_COMPAT.patch`，完整步骤和参数见 `BUILD_RECIPE.md`。
- Cygwin 3.6.9-1 source package：官方内容页 `https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.9-1-src`，归档路径 `src/release/cygwin/cygwin-3.6.9-1-src.tar.xz`，大小 `9312760` 字节，SHA-512 `771ab64fff17323a32b7cb56140c974d446899a5d4eb5b76115e14cd8fe2e4108be5f30112e441def0f86666d37ab35ba5fb31950910d91ffc12ba69e0934f6e`。
- newlib-cygwin tag `cygwin-3.6.9`：peeled commit `daabea98682f3f4bef0044829a8d24226135bb71`。

发布要求：向外部分发包含 `cygwin1.dll` 的 NetConsole/Agent 包时，发布负责人必须在同一发布渠道同时提供上述精确源码归档，或依照适用许可证提供有效的书面源码提供方案；不得只留下不固定版本的项目首页。产品打包不会联网获取源码。GNU GPLv3、LGPLv3 和 Cygwin 链接例外正文分别见 `GPL-3.0.txt`、`COPYING.LIB` 与 `CYGWIN_LICENSE`。
