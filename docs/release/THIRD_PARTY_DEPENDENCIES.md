# 第三方依赖与许可证边界

NetConsole v1.5.4 的正式桌面产品是 Electron + Vue + Python Backend；产品版本唯一来源为 `src/netconsole/core/version.py`。产品运行时不安装或打包 Qt/PySide/PyQt、shiboken、QFluentWidgets、SIP 或 Qt plugins；这些名称也是 Backend 与 Electron 安装包 Guard 的阻断标记。

## Python 依赖分层

| 文件 | 用途 | 是否进入产品 Backend |
| --- | --- | --- |
| `requirements-runtime.txt` | FastAPI、设备连接、Excel、图表等运行时依赖 | 是 |
| `requirements-test.txt` | 运行时依赖 + pytest | 否 |
| `requirements-build.txt` | 运行时依赖 + PyInstaller、pip-licenses、cyclonedx-bom | 否 |
| `requirements-dev.txt` | 测试、构建和 Ruff/mypy 的完整开发环境 | 否 |
| `constraints.txt` | CPython 3.13 / Windows x64 的精确版本约束 | 不单独安装 |

安装命令必须显式选择职责，并同时使用约束文件：

```powershell
python -m pip install -r requirements-runtime.txt -c constraints.txt
python -m pip install -r requirements-test.txt -c constraints.txt
python -m pip install -r requirements-build.txt -c constraints.txt
python -m pip install -r requirements-dev.txt -c constraints.txt
python -m pip check
```

`requirements.txt` 仅保留给 `scripts.build.build_release` 默认入口的构建兼容别名；新环境不要把它当成产品运行时清单。`pyproject.toml` 同步声明运行时直接依赖，包括生产代码直接使用的 Paramiko，因此 `python -m pip install . -c constraints.txt` 不依赖 Netmiko 偶然传递安装 SSH/SFTP 运行时。构建和 Electron `--skip-install` 路径都会检查完整已安装闭包与 constraints 一致，不能只通过 `pip check` 判断发布环境可用。

## 产品运行时组件

Python 直接运行时组件及用途见 `src/netconsole/assets/open_source_notices.json`。`tzdata` 是 Windows 冻结 Backend 的直接运行依赖，由 PyInstaller 标准 hook 收集完整 IANA 时区资源，确保 `Asia/Shanghai` 等 Profile 时区不依赖系统 TZPATH。Backend 构建会从 `requirements-runtime.txt` 出发遍历当前环境的传递依赖，逐项核对 `constraints.txt` 的精确版本，再生成 CycloneDX `sbom.cdx.json`；SBOM 校验会重新要求这份完整锁定闭包，删除 FastAPI 等任一直接或传递组件都会失败。许可证缺失或被标记为 `UNKNOWN` 时同样停止构建。

Electron 版本固定为 `43.1.1`，许可证为 MIT；内嵌 Chromium `150.0.7871.114` 与 Node.js `24.18.0` 分别登记。安装包 smoke 直接读取最终 Electron executable 的 `process.versions`，并要求 Electron/Chromium 实际许可证文本存在，不能只相信手工版本字符串或把 Electron 运行时统称为“桌面框架”。

## 版本化外部工具

- `fping` v5.5 与 Cygwin Runtime v3.6.9：分别登记组件、许可证、PURL 和二进制 SHA-256；交付包必须保留实际 `CYGWIN_ICMP_COMPAT.patch`、`BUILD_RECIPE.md`、GPLv3/LGPLv3/链接例外、精确对应源码说明、来源清单和同目录 DLL。
- iPerf3 Windows x64 Cygwin dynamic-auth v3.21：采用用户提供并经哈希核验的 `ar51an/iperf3-win-builds` tag 3.21 精确发行资产。发行 ZIP SHA-256、asset ID、四个文件哈希和上游源包索引记录在 `resources/tools/windows-x64/iperf3/SOURCE_PROVENANCE.json`；Cygwin 3.6.7-1 的精确源码归档与提供方案记录在 `CORRESPONDING_SOURCE.md`；iPerf3、Cygwin、OpenSSL、zlib 与内嵌 cJSON 分别登记许可证，GPLv3/LGPLv3 等完整文本位于同目录 `licenses/`。
- IPOP v4.1 是用户自备、不可再分发的外部工具，不能进入 Backend 或 Electron 安装包。

## 审计与发布检查

构建依赖包含 `pip-licenses` 与 `cyclonedx-bom`。`scripts/build/generate_sbom.py` 实际调用 `pip-licenses` 补充许可证事实，并把锁定运行闭包转换成精确 requirements 输入，执行 `python -m cyclonedx_py requirements - --sv 1.5 --output-reproducible --validate`；独立工具生成的组件名/版本集合必须与产品 SBOM 完全一致。产品 SBOM 仍由仓库脚本生成，并继续严格检查 PURL、`bom-ref`、许可证、事实版本和工具哈希，不把构建工具列为运行组件。包内机器可读 Notice 的唯一发布来源是 `src/netconsole/assets/open_source_notices.json`，`docs/open_source_notices.json` 只是必须保持字节一致的文档镜像。Backend 检查入口为：

```powershell
python -m scripts.build.check_runtime_deps --python-environment
python -m scripts.build.check_runtime_deps --locked-environment --requirements requirements-build.txt --constraints constraints.txt
python -m scripts.build.generate_sbom dist/netconsole-runtime.cdx.json
python -m scripts.build.check_runtime_deps --require-compliance dist/_build/pyinstaller/dist/NetConsoleBackend
```

最后一个命令和 `apps/desktop_electron/scripts/package-smoke.mjs` 都会检查完整 Qt marker、运行时 Notice、Electron/Chromium、SBOM、工具来源清单、许可证哈希和工具目录白名单。当前 iPerf3/fping 自动化合规材料门禁已闭环；对外分发 Cygwin runtime 时，发布负责人仍须按 `CORRESPONDING_SOURCE.md` 同时提供对应源码或有效书面方案，这属于每次正式发布的合规责任，而不是构建期联网动作。
