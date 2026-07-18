# Electron-only E2：依赖、发布 Guard 与许可证基线

日期：2026-07-18

## 本切片完成

- Python 依赖拆分为 runtime/test/build/dev 四层，`pyproject.toml` 声明运行时依赖，`constraints.txt` 固定 CPython 3.13 / Windows x64 解析结果。
- Backend Python 环境 Guard 与安装包 smoke 均覆盖 PySide2/6、PyQt5/6、shiboken、QFluentWidgets、Qt5/6 DLL、Qt plugins、SIP 和 distribution metadata。
- 产品 Notice 仅保留 Python runtime、Electron/Chromium/Node.js 和版本化外部工具；fping 与两个 Cygwin runtime 分别登记，pytest、PyInstaller、许可证工具和 SBOM 工具不再伪装成产品运行组件。
- 构建阶段从 `requirements-runtime.txt` 遍历并核对 `constraints.txt` 的完整 Python 运行闭包，生成严格校验 PURL、`bom-ref`、版本和工具哈希的 CycloneDX 1.5 `sbom.cdx.json`；删除任一直接或传递组件都会失败。相同冻结清单还会由 `cyclonedx-bom` CLI 独立生成并按组件名/版本交叉核对，随后要求 Notice、第三方组件说明、Electron/Chromium 实际许可证文本和 SBOM 同时存在。
- 默认构建安装与 Electron `--skip-install` 都会遍历 requirements-build 的已安装依赖闭包并对照 constraints；当前开发 `.venv` 已重新锁定并通过闭包与 `pip check` 校验，后续漂移会在打包前失败关闭。

## iPerf3 阻塞解除

经用户确认，运行包统一替换为 `ar51an/iperf3-win-builds` 3.21 的 `iperf-3.21-win64-dynamic-auth.zip`。GitHub Release asset digest、用户提供的离线 ZIP 与仓库内四个运行文件逐项校验一致；iPerf3、Cygwin 3.6.7、OpenSSL 3.0.19、zlib 1.3.2 与内嵌 cJSON 的许可证和源包索引已归档，Cygwin 3.6.7-1 对应源码归档路径、大小、SHA-512 与发布提供方案已固定。旧 3.20 三个无法与发行资产匹配的文件不再保留。发行 ZIP 仅作离线核验证据，正式构建只复制仓库内版本化文件，不联网获取业务工具。

发布 Guard 现在同时验证来源清单、发行 ZIP 身份、四个文件哈希、GPLv3/LGPLv3/链接例外、对应源码材料和 Notice/SBOM 组件；fping 实际 v5.5-dirty 构建已收敛为“上游 v5.5 + 仓库归档补丁 + 固定配方”，不再错误声明为纯上游二进制。iPerf3/Cygwin 的 `UNKNOWN`/`blocked` 状态已删除。

## 验证边界

当前项目 `.venv` 已包含许可证/SBOM 构建工具，依赖闭包与 `constraints.txt` 一致，`pip check` 和 Qt-free 环境检查通过；PyInstaller Backend、Electron `win-unpacked` Package Smoke、NSIS 1.3.9 安装器生成、系统临时目录静默安装/受管 Backend 冒烟/卸载均已通过。Electron 目录包固定复用 `node_modules/electron/dist`，避免缓存命中后仍联网获取校验文件；最终当前源码组合的 Vue、Backend、Electron 目录构建和 Package Smoke 已再次通过。

Agent Windows x64 总构建现在优先调用仓库 `.venv` 的 `python -m PyInstaller`，不再因调用终端缺少全局 `pyinstaller` 而静默漏打 MR sidecar；sidecar 失败或缺失会使整个构建失败关闭。最终构建实际生成并验证了 sidecar、console/tray、fping 5.5 和 iPerf 3.21，Go 全量测试与工具复制前后离线 Guard 通过。项目最终组合的 Python 全量为 `2052 passed, 1 skipped`，Vue 为 191 项，Electron 为 89 项；改动范围 Ruff、文档 Guard 和 `git diff --check` 在提交前重新执行。正式分发仍须按 `CORRESPONDING_SOURCE.md` 履行 Cygwin 对应源码分发责任；临时 venv、wheel/cache 和构建产物不得写入仓库。
