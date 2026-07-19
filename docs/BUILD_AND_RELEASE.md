# 构建与发布

NetConsole v1.3.9 的正式桌面产品只有 Electron + Vue + Python Backend。Python Backend 使用 PyInstaller 生成受 Electron 管理的 `NetConsoleBackend.exe`；PyInstaller、测试工具和许可证/SBOM 工具只属于构建环境，不属于产品运行时依赖。

安装包升级和卸载不得删除 Electron `userData/bootstrap.json` 或用户选择的数据根。发布 smoke 必须确认 Backend 从 bootstrap 指定的数据根启动，且仓库根没有生成 `data/` 或新的 `.local/` 运行数据。

## 依赖安装

目标环境是 Windows 11、CPython 3.13。依赖按职责拆分，并由单一 `constraints.txt` 精确锁定：

```powershell
python -m pip install -r requirements-runtime.txt -c constraints.txt
python -m pip install -r requirements-test.txt -c constraints.txt
python -m pip install -r requirements-build.txt -c constraints.txt
python -m pip install -r requirements-dev.txt -c constraints.txt
python -m pip check
```

产品运行环境只执行第一条和 `python -m pip install . -c constraints.txt`；不得安装 `requirements-test.txt`、`requirements-build.txt` 或 `requirements-dev.txt`。可用 `python -m scripts.build.check_runtime_deps --python-environment` 验证当前环境没有 Qt 包元数据或可导入 Qt 模块。干净环境的反向探针必须满足 `import PySide6` 抛出 `ModuleNotFoundError`。

## Backend 构建

先在仓库根目录执行：

```powershell
python -m scripts.build.build_release --backend pyinstaller
```

该入口会重新构建 `apps/web`、生成干净 PyInstaller spec、只从入口 import graph 收集 Python 模块、复制白名单外部工具，并将输出写入 `dist/v1.3.9/pyinstaller/NetConsoleBackend/`。默认 `requirements.txt` 是构建兼容别名，实际指向 `requirements-build.txt`。

默认安装会同时传入 `-c constraints.txt`。无论是否使用 `--skip-install`，构建 preflight 都会从 `requirements-build.txt` 遍历已安装 distribution 的完整依赖闭包，并逐项核对 constraints 的精确版本；缺包、版本漂移、传递依赖未锁定或无效 metadata 均直接失败。Electron `package.mjs` 在调用 `--skip-install` 前还会单独执行同一 Guard，不能把开发机 `.venv` 的偶然可用状态当成发布环境。

构建阶段的硬门包括：

- `scripts/build/check_runtime_deps.py`：Backend EXE、Python DLL、VC runtime、fping/iPerf 文件、可写目录、完整 Qt marker 和发布合规文件；
- `scripts/build/clean_build_spec.py`：项目/数据白名单、Web metadata、工具版本、运行时 Python 环境和干净 spec；
- `scripts/build/generate_sbom.py`：从锁定的已安装运行时闭包生成 CycloneDX 1.5 `sbom.cdx.json`，校验器再次要求所有直接与传递 Python 组件及精确版本，并严格校验唯一 `bom-ref`、PURL 生态、许可证和事实文件哈希；
- `src/netconsole/assets/open_source_notices.json` 与 `THIRD_PARTY_COMPONENTS.md`：随 Backend 进入 `netconsole/assets/`；
- 任一未知许可证、`status: blocked`、缺少 Electron/Chromium Notice/SBOM 或 Qt 残留都会停止构建。

构建依赖中的 `pip-licenses` 用于许可证解析；`generate_sbom.py` 还会真实执行 `python -m cyclonedx_py requirements - --sv 1.5 --output-reproducible --validate`，用独立生成的 CycloneDX 组件名/版本集合交叉检查锁定运行闭包。两项工具都不会被列入运行时 Notice，也不会复制进 Backend。Python distribution 使用 `pkg:pypi`，Electron 使用 `pkg:npm`；Python 解释器、Chromium、Node.js、fping、Cygwin 等非 Python distribution 使用 `pkg:generic`，不得伪装成 PyPI 包。

## Electron 安装包

```powershell
cd apps/desktop_electron
pnpm install --frozen-lockfile
pnpm test
pnpm run typecheck
pnpm run build
pnpm run package:dir
node scripts/package-smoke.mjs
```

`package.mjs` 只接受项目 `.venv` Python 来生成 Backend，安装包通过 `extraResources` 固定放在 `resources/backend/`，运行时不依赖客户机系统 Python。`package-smoke.mjs` 只按安装包相对路径和精确 basename/目录规则扫描 Qt 残留，阻断 PySide/PyQt、shiboken、QFluentWidgets、SIP、Qt5/6 库、Qt WebEngine 进程、Qt plugin DLL 和 `qt.conf`，不会因为构建机父目录名或普通 `plugins/imageformats` 目录误报。

`build.electronDist` 固定为 `apps/desktop_electron/node_modules/electron/dist`。完成锁定依赖安装后，`electron-builder` 必须复用本机已安装的 Electron 43.1.1 分发目录，不再访问 GitHub 获取 Electron ZIP 或 `SHASUMS256.txt`；日志应出现 `using custom unpacked Electron distribution`。这项约束只消除重复下载，不绕过 `pnpm install --frozen-lockfile` 的依赖完整性，也不得通过关闭 `signAndEditExecutable` 丢弃 EXE 资源元数据。

安装包 smoke 以 `ELECTRON_RUN_AS_NODE=1` 读取最终 `NetConsole.exe` 的 `process.versions`，逐项核对 Electron、Chromium 和 Node.js Notice/SBOM 版本；同时要求 electron-builder 输出中的 `LICENSE.electron.txt`、`LICENSES.chromium.html`、Backend 第三方说明、Notice 和 SBOM 都存在。包内 `device_command_profiles.json` 还必须保持 schema `2026.07.device-command-profiles.v1`，且只包含 `device.inventory.collect` 当前受控命令序列。

正式安装包发布门还需要在 Windows 图形环境完成人工启动、签名、安装/卸载和升级验收；单元测试或源码 smoke 不能替代这些验收。`nsis.deleteAppDataOnUninstall=false` 是当前数据保护约束。

## 外部工具与许可证阻塞

`resources/tools/windows-x64/fping/` 的版本化材料包含实际 Cygwin ICMP 兼容补丁、构建配方、GPLv3/LGPLv3/链接例外、精确对应源码说明和来源清单。fping 与其 Cygwin 3.6.9 runtime 在 Notice/SBOM 中作为独立组件登记，并以版本化二进制、补丁、配方和许可证文件哈希作为事实校验。iPerf3 固定为用户提供并经哈希核验的 `ar51an/iperf3-win-builds` 3.21 `win64-dynamic-auth`：构建会核对发行 ZIP 身份、四个文件 SHA-256、Cygwin 3.6.7-1 精确对应源码说明及完整 GPLv3/LGPLv3/链接例外，并分别登记 iPerf3、Cygwin、OpenSSL、zlib 与内嵌 cJSON。发行 ZIP 不进入构建输入，桌面端和 Agent 打包只从仓库内 `resources/tools/windows-x64/{fping,iperf3}` 白名单复制本地文件；不得在发布过程中联网下载或自动替换业务工具。任何同名替换、额外文件或材料缺失均停止发布。

IPOP v4.1 没有可核验的再分发许可，仅允许用户通过配置选择本机程序；任何 `IPOP.EXE` 或 `tools/windows-x64/ipop` 进入 Backend/Electron 输出都必须失败。

## Windows Go Agent

独立 Agent 不进入 Python Backend 或 Electron 安装包，仍使用自己的 Windows 构建入口：

```powershell
apps\agent\scripts\build_windows.bat
```

该脚本要求 Windows x64 与 Go 1.26.5，复制前先通过本地 PowerShell Guard 校验 `resources/tools/windows-x64/{fping,iperf3}`，再构建可用的 Python MR sidecar、执行 `go mod tidy`、`go test ./...` 并生成 console/托盘版本；复制后对交付目录再次执行同一 Guard。输出位于 `dist/agent/windows-x64/`，临时目录位于 `dist/agent/.build-windows-x64/`；两者都不得提交。Agent 构建、配置和运行细节见 [Agent README](../apps/agent/README.md) 与 [独立 Agent](AGENT.md)。正式工具打包全程只使用仓库本地文件，不下载业务工具。

## 不得进入仓库的产物

`dist/`、PyInstaller build/spec 临时目录、Electron unpacked/安装包、`apps/*/node_modules`、虚拟环境、SBOM 临时输出、日志、SQLite 和用户数据均不得提交。开发态运行数据使用 `.local/`；发布态数据由系统应用数据目录管理。
