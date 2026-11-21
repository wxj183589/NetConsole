# v1.5.17 包清单

目录：`D:\study\NetConsole-Workspace\release\v1.5.17\build-0-d687ba57`

| 文件 | 大小（bytes） | SHA-256 |
| --- | ---: | --- |
| `NetConsole-v1.5.17-Setup.exe` | 158150475 | `2c17fb1c0b0c36e80f78ccf2db7602f986d441c4228933eb51d184b74cc540c1` |
| `NetConsole-v1.5.17-Portable.zip` | 215592864 | `575cebf6f5f6544b64af6dbd058643f2c5c183d41272d635a167529ed8a6650c` |

Portable ZIP 解压检查：7-Zip `1928` files / `18` folders，压缩测试 PASS；解压目录包含 `NetConsole.exe` 与 `portable.mode`，未发现 `.git`、node_modules、venv、生产数据或原始 RAR。Installer 为 NSIS-3 Unicode，包级 smoke PASS；真实安装/升级/卸载仍 PENDING。

最终分发包：`D:\study\NetConsole-Workspace\release\v1.5.17\NetConsole-v1.5.17-Full-Distribution.zip`；大小 `372907940` bytes；SHA-256 `88471377c42740ec2d65633104b05cc8b4abaf39ce988b6fbaf5195f3e87ab9a`。重新解压后包含 7 个顶层文件，Installer/Portable hash 与清单一致。
