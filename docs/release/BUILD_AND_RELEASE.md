# 构建与发布

NetConsole v1.4.9 的正式桌面产品只有 Electron + Vue + Python Backend。Python Backend 使用 PyInstaller 生成受 Electron 管理的 `NetConsoleBackend.exe`；PyInstaller、测试工具和许可证/SBOM 工具只属于构建环境，不属于产品运行时依赖。

安装包升级和卸载不得删除 Electron `userData/bootstrap.json` 或用户选择的数据根。electron-builder 的既有 NSIS 安装器必须分别显示程序安装目录与数据存放目录；数据根在完成路径、磁盘、可写/重命名、SQLite 锁与空间校验后，由打包 Backend 在空根或含无冲突普通文件的目录中原子初始化标准结构与 `storage-manifest.json`，或验证已有 manifest 兼容性，最后才写入 `HKLM\Software\NetConsole\DataRoot`。初始化/兼容性校验失败不得发布指针，也不得覆盖已有 manifest 或普通文件。发布 smoke 在唯一 `D:\study\test-data\NetConsole\<run-id>` 中以 `RuntimeMode.TEST` 运行并自动清理，绝不读取机器级指针或真实数据根；同时确认仓库根没有生成 `data/` 或新的 `.local/` 运行数据。

NSIS 必须显式启用 Unicode 安装器，并先在零写入状态下识别候选目录和实际条目，再执行可写/重命名预检；探测成功后禁止重新使用普通目录非空规则。待创建路径的语法规范化必须调用 Win32 `GetFullPathNameW`，不得使用会要求路径存在的 NSIS 内置 `GetFullPathName`，且规范化阶段不得创建目录。NSIS 预检和安装后的 Backend 复验必须使用候选数据根内部的唯一临时文件，完成 flush/close、同目录文件重命名、内容回读和清理。禁止固定源/目标文件名、目录级 Rename、从安装器临时目录跨卷移动或使用现有业务文件作为探测对象。失败日志只记录步骤、错误来源和对应 Win32 或内部错误码，不写用户配置内容；测试修复包使用独立 artifact 名称，不能覆盖同版本既有正式安装包。

正式 NSIS 构建只能从已提交、工作区 clean 且 `HEAD` 已推送到当前 upstream 的状态开始。`pnpm package` 会清理白名单内的 `dist/electron/`、`dist/_build/` 和 `apps/desktop_electron/dist/`，为 electron-builder 分配本轮独立临时目录，并生成 `NetConsole-<version>-<git-short>-x64-setup.exe`；固定名称 `NetConsole-<version>-x64-setup.exe` 或同名唯一制品在构建前存在时直接失败，避免覆盖旧包后仅按修改时间误判。

构建开始时冻结完整 commit，最终 EXE Gate 前以及向 `D:\study\release\NetConsole\v<version>` 持久发布前都必须再次检查 tracked/untracked 工作区、HEAD 与 upstream；任一处变化立即失败，不生成或发布宣称 `dirty=false` 的正式制品。外层 PowerShell 还要显式复核 release manifest 中的 Backend/Frontend commit 均等于冻结 commit。

外层 NSIS 必须把 app 版本、完整/短 Git commit、UTC 构建时间、build ID、数据根策略版本及策略源码 SHA-256 写入 PE 版本资源，并在数据根页面显示可核对的短身份。最终 EXE 还必须内嵌本轮 installer manifest 和实际参与编译的数据根 include 源码。post-build Gate 使用支持 NSIS handler 的完整 7-Zip 直接打开最终 `setup.exe`，复核 `NSIS-3 Unicode`、PE 身份、内嵌 manifest/源码哈希、新文案存在、三段旧阻止文案不存在、EXE 晚于策略源码和本轮构建开始时间、两次 SHA-256 一致，以及内层 Backend/Frontend commit 均等于 Installer commit 且 `dirty=false`。构建机可安装完整版 7-Zip，或通过 `NETCONSOLE_7Z` 指向支持 `Nsis` format handler 的 `7z.exe`；electron-builder 缓存中的精简 `7za.exe` 不满足此门禁。

Full/Customer 正式安装器的 PE 版本资源还必须包含 `InstallerEdition` 与
`InstallerFeatureProfile`，并与 edition manifest、Backend `build_info.json` 和包内 Feature Profile
严格相等；不能只依赖文件名表达版本类型。

Gate 成功后在安装包旁生成同名 `.exe.release.json`，记录文件名、SHA-256、字节数、Installer/Backend/Frontend commit、build ID、策略源码哈希、新旧文案扫描结果和 `real_windows_install_status`。自动构建只能将真实安装状态写为 `PENDING`；只有在隔离的全新 Windows 机器或 VM 完成不存在目录、空目录、含普通文件目录和合法旧数据根四种 GUI 安装，并核对注册表指针及原文件哈希后，才能在交付记录中改为 `PASS`。

正式 Renderer 右上角固定显示 `v<version>+<8位短SHA>`，dirty 源码态明确追加 `-dirty`；不再只在开发模式显示 commit。`/api/health` 同时返回 `build_id`、Backend/Frontend 完整 commit、短 commit、edition、`packaged_dirty` 和 UTC build timestamp。Backend `app.log` 与 Electron `electron.log` 分别写入一条 `BUILD_IDENTITY` / `ELECTRON_BUILD_IDENTITY`，不记录令牌、凭据或物理业务路径。

## Windows Server 2012 兼容事实

| 范围 | 证据等级 | 说明 |
| --- | --- | --- |
| NetConsole 主程序（Electron + Backend） | `USER_FIELD_CONFIRMED` | Windows Server 2012 x64 已有用户现场运行确认；这不是本仓库自动化或正式安装包 GUI 结果。 |
| 独立 Windows Go Agent | `USER_FIELD_CONFIRMED` | 同一现场确认覆盖 Agent；Go 运行时、托盘、工具和 Python sidecar 的自动化 VM 记录仍缺失。 |
| Windows Server 2012 自动化 VM | `AUTOMATION_NOT_RECORDED` | 仓库没有可引用的隔离 VM 安装、启动、健康、退出和 Agent API 记录；不得伪造测试结论。 |
| 正式安装包 GUI 验收 | `PENDING` | 仍须按本文件安装/升级/卸载门禁执行；兼容事实不改变 `real_windows_install_status`。 |

上述是证据分层，不是 OS 支持阻断条件；启动路径不按 Server 版本拒绝主程序或 Agent。未知的具体能力仍以真实探测和现有能力 API 为准。

安装包人工验收至少覆盖：程序安装在 C 盘而数据在 D/E 盘、阻止 C 盘数据根、`GetDriveTypeW` 收到 `E:\` 等根路径、Windows 空目录直接作为数据根并生成有效 manifest、合法既有根复用、含无冲突普通文件的目录保留原文件并成功初始化、必需路径真实冲突时原样阻止、损坏 manifest 原样保留并阻止安装、旧固定探测残留不误判、不自动创建嵌套 `NetConsoleData`、安装失败不删除或修改用户所选目录、升级/修复保持旧根、更换根的 staging/SQLite 校验失败回滚，以及普通卸载保留数据和注册表指针。源码 `pnpm dev` 还必须读取同一指针；测试模式不得读取注册表或真实根。Backend 向 Electron 输出的监听、关闭和启动失败握手必须是代码页无关的 ASCII JSON；中文通过 JSON Unicode 转义逐字恢复。

## 依赖安装

目标环境是 Windows 11、CPython 3.13。Electron 构建环境还必须提供可用的 Go，用于生成 Windows x64 工具提升 helper；该 helper 以 `CGO_ENABLED=0` 构建，正式客户机运行不需要 Go。Python 依赖按职责拆分，并由单一 `constraints.txt` 精确锁定：

```powershell
python -m pip install -r requirements-runtime.txt -c constraints.txt
python -m pip install -r requirements-test.txt -c constraints.txt
python -m pip install -r requirements-build.txt -c constraints.txt
python -m pip install -r requirements-dev.txt -c constraints.txt
python -m pip check
```

产品运行环境只执行第一条和 `python -m pip install . -c constraints.txt`；不得安装 `requirements-test.txt`、`requirements-build.txt` 或 `requirements-dev.txt`。`tzdata==2026.3` 是 Windows 冻结 Backend 的正式直接运行依赖，PyInstaller 通过标准 `hook-tzdata.py` 收集完整 IANA 时区数据库，不能改用系统时区、固定 UTC 偏移或手工复制单个时区文件。`cryptography==49.0.0` 仍由 constraints 锁定为 Paramiko/SSH 依赖闭包的一部分，但 v4 完整迁移包不再直接使用 Scrypt/AES，也不得因此重新加入迁移密码或加密载荷。可用 `python -m scripts.build.check_runtime_deps --python-environment` 验证当前环境没有 Qt 包元数据或可导入 Qt 模块。干净环境的反向探针必须满足 `import PySide6` 抛出 `ModuleNotFoundError`。

## Backend 构建

正式发布的身份事实来自构建开始时的 Git，而不是 `src/netconsole/core/version.py` 中的手工提交号或时间。`scripts/build/build_metadata.py` 在一次发布调用中读取 `git rev-parse HEAD` 与 `git status --porcelain`，生成并复用 `app_version / git_commit_full / git_commit_short / build_time_utc / build_dirty / build_source / frontend_commit / backend_commit`；时间固定为 ISO 8601 UTC。Vite、PyInstaller、Backend 自检、Electron package smoke 共用这一快照，分阶段校验时还会重新确认快照对应当前 Git 来源。

正式候选必须按“修改与验证完成 → 中文提交 → 确认工作区 clean → 推送最终提交 → 读取最终 HEAD → 构建 Desktop Renderer/Backend/Electron/NSIS → package smoke 比较包内元数据与实际 HEAD”的顺序执行。`--release` 遇到 tracked 或 untracked 修改会直接失败；开发构建允许 `build_dirty=true`，但其 `build_source=git-development`，不能冒充正式包。最终包级输出必须包含 `SOURCE_GIT_HEAD / PACKAGED_BACKEND_COMMIT / PACKAGED_FRONTEND_COMMIT / SELF_CHECK_COMMIT / PACKAGED_BUILD_TIME / PACKAGED_DIRTY`，提交号不一致或 dirty 不为 false 都必须停止发布。

先在仓库根目录执行：

```powershell
python -m scripts.build.build_release --backend pyinstaller --release
```

该入口会重新构建 `apps/desktop_renderer`、生成干净 PyInstaller spec、只从入口 import graph 收集 Python 模块、复制白名单外部工具，并将临时 PyInstaller build/spec/dist 写入 `dist/_build/pyinstaller/`，正式 Backend 输出写入 `dist/v1.4.9/pyinstaller/NetConsoleBackend/`。`dist/build/` 不是当前构建目录，出现时属于旧残留。默认 `requirements.txt` 是构建兼容别名，实际指向 `requirements-build.txt`。

完成 Backend、Electron 和安装包验收后，可以通过固定白名单清理临时构建区：

```powershell
python -m scripts.maintenance.clean_generated_artifacts --target build-temporary
python -m scripts.maintenance.clean_generated_artifacts --target build-temporary --apply `
  --manifest "D:\NetConsoleData\migrations\generated-cleanup-build-temporary.json"
```

该目标只允许删除 `dist/_build/`，不会处理 `dist/v1.4.9/`、`dist/electron/`、`dist/agent/`、仓库数据或用户数据根。`setuptools-residue` 只能存在于临时构建期间，构建验收完成后应随 `_build` 一并清理。

默认安装会同时传入 `-c constraints.txt`。无论是否使用 `--skip-install`，构建 preflight 都会从 `requirements-build.txt` 遍历已安装 distribution 的完整依赖闭包，并逐项核对 constraints 的精确版本；缺包、版本漂移、传递依赖未锁定或无效 metadata 均直接失败。Electron `package.mjs` 在调用 `--skip-install` 前还会单独执行同一 Guard，不能把开发机 `.venv` 的偶然可用状态当成发布环境。

构建阶段的硬门包括：

- `scripts/build/check_runtime_deps.py`：Backend EXE、Python DLL、VC runtime、fping/iPerf 文件、可写目录、完整 Qt marker 和发布合规文件；
- `scripts/build/clean_build_spec.py`：项目/数据白名单、Web metadata、工具版本、运行时 Python 环境和干净 spec；
- `scripts/build/generate_sbom.py`：从锁定的已安装运行时闭包生成 CycloneDX 1.5 `sbom.cdx.json`，校验器再次要求所有直接与传递 Python 组件及精确版本，并严格校验唯一 `bom-ref`、PURL 生态、许可证和事实文件哈希；
- `src/netconsole/assets/open_source_notices.json` 与 `THIRD_PARTY_COMPONENTS.md`：随 Backend 进入 `netconsole/assets/`；
- 任一未知许可证、`status: blocked`、缺少 Electron/Chromium Notice/SBOM 或 Qt 残留都会停止构建。

构建依赖中的 `pip-licenses` 用于许可证解析；`generate_sbom.py` 还会真实执行 `python -m cyclonedx_py requirements - --sv 1.5 --output-reproducible --validate`，用独立生成的 CycloneDX 组件名/版本集合交叉检查锁定运行闭包。两项工具都不会被列入运行时 Notice，也不会复制进 Backend。Python distribution 使用 `pkg:pypi`，Electron 使用 `pkg:npm`；Python 解释器、Chromium、Node.js、fping、Cygwin 等非 Python distribution 使用 `pkg:generic`，不得伪装成 PyPI 包。

## Electron 安装包

在最终提交已经推送、工作区 clean 后，可在仓库根目录使用 Windows 一键入口：

```powershell
.\scripts\build\package_windows.ps1
```

也可双击 `scripts\build\package_windows.bat`。脚本会检查 Windows、Git/upstream、项目 `.venv`、pnpm 和 Python 依赖，按两个 `pnpm-lock.yaml` 安装锁定依赖，依次运行 Desktop Renderer/Electron 测试，再调用下方同一个 `pnpm package` 正式链路。构建成功后，脚本会定位当前 Git HEAD 对应的 `.exe.release.json`，复核安装包大小和 SHA-256 并输出绝对路径。只检查环境而不安装依赖、测试或打包时使用：

```powershell
.\scripts\build\package_windows.ps1 -PreflightOnly
```

一键入口不会替代真实 GUI 安装验收，也不会把 `real_windows_install_status` 从 `PENDING` 改为 `PASS`。

```powershell
cd apps/desktop_electron
pnpm install --frozen-lockfile
pnpm test
pnpm run typecheck
pnpm run build
pnpm package
```

上述 `pnpm package` 必须在最终提交推送后执行；它会依次完成 Electron main/preload、`dist/native/netconsole-elevated-launcher.exe`、Desktop Renderer、Backend 冻结、electron-builder NSIS、现有 package smoke 和最终 setup.exe Gate。electron-builder 把 helper 固定放入 `resources/native/`，package smoke 要求该文件存在。只需检查 unpacked 目录时仍可使用 `pnpm run package:dir` 后运行 `node scripts/package-smoke.mjs`，但该路径不会生成或验证可发布的 NSIS 安装包，不能作为正式打包结果。

`package.mjs` 只接受项目 `.venv` Python 来生成 Backend，安装包通过 `extraResources` 固定放在 `resources/backend/`，运行时不依赖客户机系统 Python。`package-smoke.mjs` 只按安装包相对路径和精确 basename/目录规则扫描 Qt 残留，阻断 PySide/PyQt、shiboken、QFluentWidgets、SIP、Qt5/6 库、Qt WebEngine 进程、Qt plugin DLL 和 `qt.conf`，不会因为构建机父目录名或普通 `plugins/imageformats` 目录误报。

Package smoke 还会在最终冻结的 `resources/backend/NetConsoleBackend.exe`
上运行 `scripts/build/smoke_frozen_device_database.py`：脚本在独立测试数据根创建旧
`devices` schema，启动冻结 Backend 请求 `/api/device-management/devices`，确认旧设备
仍可读取且默认分类为 `unspecified / included`，正常停止后再次启动并确认没有
重复迁移备份。该 smoke 不读取机器级数据根，也不修改真实局点数据库。若构建机没有可用
的最终冻结 Backend，只能报告 Python/应用层定向测试，不能声称正式 Backend smoke 已通过。

干净 PyInstaller 构建会在临时 build 目录生成并嵌入 `_internal/netconsole/assets/runtime/{build_info.json,feature_flags.json,build-metadata.json}`：edition 固定为 `customer`，profile 固定为 `production`，构建身份来自本次 Git 快照，不从源码硬编码或客户机外部配置取值。Backend dist 校验与 Electron package smoke 都会解析这些 JSON，校验设备管理/采集/导入导出、文件下载、网络工具、AC、列车在线、Online MR 和 MESH 等必要生产能力，并拒绝任何 `feature_flags.local.json`。冻结运行时即使缺少或损坏 `feature_flags.json`，也必须通过 Registry fallback 保留必要生产能力，同时继续隐藏 internal/development 功能。`client_package` 仅是构建/发布元数据，不能作为正式运行时通用拒绝条件。

系统设置的“正式包环境自检”验证 Backend、前后端构建标识、只读生产 Feature policy、当前局点、数据根、`tasks.db`、`devices.db`、非秘密凭据状态表、fping/iPerf3、Electron Bridge，以及 REST/WebSocket 中文探针。自检不返回本机绝对路径或凭据。完整功能与人工验收状态见[正式包功能矩阵](./PACKAGED_FEATURE_MATRIX.md)。

`build.electronDist` 固定为 `apps/desktop_electron/node_modules/electron/dist`。完成锁定依赖安装后，`electron-builder` 必须复用本机已安装的 Electron 43.1.1 分发目录，不再访问 GitHub 获取 Electron ZIP 或 `SHASUMS256.txt`；日志应出现 `using custom unpacked Electron distribution`。这项约束只消除重复下载，不绕过 `pnpm install --frozen-lockfile` 的依赖完整性，也不得通过关闭 `signAndEditExecutable` 丢弃 EXE 资源元数据。

安装包 smoke 在唯一 `D:\study\test-data\NetConsole\<run-id>` 中以 `RuntimeMode.TEST` 启动，结束后自动清理；它以 `ELECTRON_RUN_AS_NODE=1` 读取最终 `NetConsole.exe` 的 `process.versions`，逐项核对 Electron、Chromium 和 Node.js Notice/SBOM 版本；同时要求 electron-builder 输出中的 `LICENSE.electron.txt`、`LICENSES.chromium.html`、Backend 第三方说明、Notice 和 SBOM 都存在。包级门禁还会在 `PYTHONTZPATH=""` 下启动最终冻结 `NetConsoleBackend.exe`，连续两次请求真实 `/api/rail-transit/ground-unattended/status` 并要求 HTTP 200、`Asia/Shanghai` 与有效的下一次起止时间，随后在同一冻结进程创建隔离的“车载-MR”分组与 `列车34-MR-CT`/`列车34-MR-CW` 两条基础资料，实际请求 `/api/health`、MESH profiles 和两次 `POST /api/rail-transit/mesh-analysis/import-context/prepare`，验证 JSON 响应、Backend 存活、正式 Profile 自动创建及第二次 prepare 幂等；再用一个真实 `FormData` 上传四份不同正文但都名为 `meshlog.log` 的日志，检查四个唯一 `member_id`、原始名称保留及 `2026_07_27_1meshlog.log`、`2026_07_28_1meshlog.log`、`2026_07_28_2meshlog.log`、`2026_07_29_1meshlog.log`，完成冻结 Backend 的正式批量导入，重复上传其中同一正文并确认 `duplicate_same_mr`、原有归档和四个 session 不变，最后正常停止并复验端口释放；同时在未设置 `PYTHONUTF8/PYTHONIOENCODING` 的环境启动冻结 Worker，断言 stdout 是纯 ASCII JSON bytes 且中文逐字恢复。最后由最终 `NetConsole.exe` 启动受管 Backend、提交真实开源组件扫描任务，并从 REST/任务日志断言 `text_integrity=ok`、中文 progress/finished 完整且不存在 U+FFFD。包内 `device_command_profiles.json` 还必须保持 schema `2026.07.device-command-profiles.v1`，且只包含 `device.inventory.collect` 的受控只读 Profile，不得包含 `device.sftp.enable` 等写入型 Profile。

正式 Windows 用户入口固定为 `dist/electron/win-unpacked/NetConsole.exe`。`build.win.executableName` 必须保持为 `NetConsole`，并由 `package-smoke.mjs` 直接读取该构建配置，禁止在 smoke 脚本重复硬编码名称。`resources/backend/NetConsoleBackend.exe` 仅由 Electron Main 使用 `--electron-backend` 作为受管子进程启动；直接运行它会记录运行日志、显示提示并以非零状态退出，不能尝试启动源码 Electron 开发链。

正式安装包发布门还需要在 Windows 图形环境完成人工启动、签名、安装/卸载和升级验收；必须额外覆盖全新 Windows 用户、无 Python/Node/pnpm/Git/Go/源码、普通用户、中文用户名或中文数据路径、工具集真实 UAC 接受/取消、不同第三方工具、包内 helper 存在且无控制台闪现、跨电脑 v4 普通 ZIP 完整包无需密码恢复全部凭据、导入/导出敏感警告、脱敏包凭据重录、本机 Electron 眼睛按钮显式读取与关闭清理，以及真实/仿真 H3C SSH 中文任务日志。这些工具提升项当前为 `IMPLEMENTED_UNVERIFIED`；单元测试、PyInstaller smoke 或 unpacked Electron smoke 不能替代人工验收。卸载不得删除 `D:\NetConsoleData`，也不得创建 LocalAppData 数据回退。

## 外部工具与许可证阻塞

`resources/tools/windows-x64/fping/` 的版本化材料包含实际 Cygwin ICMP 兼容补丁、构建配方、GPLv3/LGPLv3/链接例外、精确对应源码说明和来源清单。fping 与其 Cygwin 3.6.9 runtime 在 Notice/SBOM 中作为独立组件登记，并以版本化二进制、补丁、配方和许可证文件哈希作为事实校验。iPerf3 固定为用户提供并经哈希核验的 `ar51an/iperf3-win-builds` 3.21 `win64-dynamic-auth`：构建会核对发行 ZIP 身份、四个文件 SHA-256、Cygwin 3.6.7-1 精确对应源码说明及完整 GPLv3/LGPLv3/链接例外，并分别登记 iPerf3、Cygwin、OpenSSL、zlib 与内嵌 cJSON。发行 ZIP 不进入构建输入，桌面端和 Agent 打包只从仓库内 `resources/tools/windows-x64/{fping,iperf3}` 白名单复制本地文件；不得在发布过程中联网下载或自动替换业务工具。任何同名替换、额外文件或材料缺失均停止发布。

IPOP v4.1 没有可核验的再分发许可，仅允许用户通过配置选择本机程序；任何 `IPOP.EXE` 或 `tools/windows-x64/ipop` 进入 Backend/Electron 输出都必须失败。

## Windows Go Agent

独立 Agent 不进入 Python Backend 或 Electron 安装包，仍使用自己的 Windows 构建入口：

```powershell
apps\agent\scripts\build_windows.bat
```

该脚本要求 Windows x64 与 Go 1.26.5，复制前先通过本地 PowerShell Guard 校验 `resources/tools/windows-x64/{fping,iperf3}`，再构建可用的 Python MR sidecar、执行 `go mod tidy`、`go test ./...` 并生成 console/托盘版本；复制后对交付目录再次执行同一 Guard。输出位于 `dist/agent/windows-x64/`，临时目录位于 `dist/agent/.build-windows-x64/`；两者都不得提交。Agent 构建、配置和运行细节见 [Agent README](../../apps/agent/README.md) 与 [独立 Agent](../agent/README.md)。正式工具打包全程只使用仓库本地文件，不下载业务工具。

## 不得进入仓库的产物

`dist/`、PyInstaller build/spec 临时目录、Electron unpacked/安装包、`apps/*/node_modules`、虚拟环境、SBOM 临时输出、日志、SQLite 和用户数据均不得提交。源码开发态、打包态和正式包统一使用 `D:\NetConsoleData`；自动测试使用显式 `D:\study\test-data\NetConsole\<run-id>`。仓库根 `data/` 只能作为旧迁移源，迁移核验后应移出仓库归档或删除。
