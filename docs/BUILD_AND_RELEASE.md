# 构建与发布

当前仓库核对环境为 Python 3.13.9、PySide6 6.11.1、PySide6-Fluent-Widgets 1.11.2；依赖约束仍以 `requirements.txt` 为准，不应把本机已安装版本写成最低支持版本。

## 当前构建入口

构建脚本位于 `scripts/build/`：

```powershell
.\scripts\build\build_release.bat
.\scripts\build\build_nuitka_release.bat
```

核心脚本：

```text
scripts/build/build_release.py
scripts/build/build_nuitka_release.py
scripts/build/build_config.py
scripts/build/release.py
```

当前支持后端：

- PyInstaller
- Nuitka

上述仍是 Qt Legacy 正式发布链。`apps/desktop_electron/` 已提供源码开发与生产资源模式，但 Electron 安装包、冻结 Python backend bundle、签名和升级尚未进入正式发布链，不能用 `pnpm start` 产物替代 PyInstaller/Nuitka 发布包。

Electron 基础验证：

```powershell
cd apps/desktop_electron
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm smoke:dev
```

`pnpm build` 构建单文件 main/preload 和唯一 `apps/web/dist`。`pnpm start` 可在源码环境验证生产静态资源由本机 FastAPI 同源托管，但仍依赖项目 Python 虚拟环境；正式安装包必须另行定义 Python bundle、资源白名单、代码签名、升级和卸载策略。当前只采用 Electron + esbuild，不引入第二个安装/打包框架。

`BuildConfig` 从 `src/netconsole/core/version.py` 读取应用名、版本和作者；构建临时文件和发布包统一写入 `dist/`。

桌面发布包包含现有完整 Vue Web 控制台。构建脚本在 Python 打包前执行 `apps/web` 的 `pnpm build`，并将 `apps/web/dist` 打入内部 `netconsole/assets/web` 资源。构建前先准备前端依赖：

```powershell
cd apps/web
pnpm install --frozen-lockfile
cd ../..
```

构建机缺少 pnpm、`apps/web/node_modules`，或构建后缺少 `dist/index.html`/`dist/web-build-meta.json` 时会明确失败，避免发布只能显示占位页的桌面包。`apps/web/dist` 和 `node_modules` 仍不得提交仓库。

两个发布入口都必须在打包前重新执行 Vue build，不能因为已有 `dist/index.html` 而接受旧产物。构建脚本向 Vite 传入 `src/netconsole/core/version.py` 的发布提交身份，并校验 metadata 中的 `app_version`、`git_commit`、`build_id`、`build_time` 和 `navigation_schema_version`；任一字段缺失、损坏或与后端身份不一致均停止打包。源码开发者直接执行 `pnpm build` 时，metadata 使用当前 Git checkout，并在存在未提交修改时添加 `-dirty`。

## Windows Go Agent

独立 Agent 不进入上述 PyInstaller/Nuitka 发布链，使用 Go 1.26.5 单独构建：

```bat
apps\agent\scripts\build_windows.bat
```

输出为 `dist/agent/windows-x64/`，临时构建目录为 `dist/agent/.build-windows-x64/`。脚本先尝试构建 Python Netmiko MR Collector，再执行 `go mod tidy` 和 `go test ./...`，最后以 `CGO_ENABLED=0`、`GOOS=windows`、`GOARCH=amd64` 构建 console 版和 GUI 托盘版，并从 `resources/tools/windows-x64/{fping,iperf3}` 白名单复制工具到交付包内的 `tools/windows-x64/`。交付包的 `start_agent.bat` 与 `start_console.bat` 会在首次运行时，从包内示例仅初始化缺失的 `%LOCALAPPDATA%\NetConsole\Agent\config.json`、`targets.json`，不会覆盖真实配置。Agent 的示例配置位于 `apps/agent/resources/config/`，真实配置放在 `.local/agent/` 或 `%LOCALAPPDATA%\NetConsole\Agent`；运行数据默认写入 `%LOCALAPPDATA%\NetConsole\Agent`，Agent 不携带或检测 IPOP。

当前 Python 发布白名单不包含 Agent。正式联合发布前需要另行确定 Agent 版本注入、代码签名、Windows 服务形态和第三方工具许可证，不得把开发态 Agent 运行数据打入发布包。

正式对外分发前，release checklist 必须人工确认 fping/iPerf3 的来源、版本、许可证、NOTICE 和 Cygwin 运行依赖。当前构建脚本只做文件存在性和 IPOP 排除，不等同于法律授权确认；iPerf3/Cygwin 材料未齐全前不得新增或替换来源不明二进制。

## 外部工具要求

构建前会检查工具源文件。当前 `scripts/build/build_config.py` 要求：

```text
resources/tools/windows-x64/fping/fping.exe
resources/tools/windows-x64/fping/cygwin1.dll
resources/tools/windows-x64/iperf3/iperf3.exe
docs/IPOP_v4.1_notice.md
```

运行时工具路径由统一解析器处理，不依赖当前工作目录。IPOP 是用户自行提供的可选外部工具，配置保存在现有 `settings.json` 的 `external_tools/ipop_path` 键；有效配置优先，未配置时可检查 `<应用目录>/tools/windows-x64/ipop/IPOP.EXE`。启动使用 Qt `QProcess.startDetached`，不拼接 shell 命令，也不等待该外部程序退出。

仓库没有可核验的 IPOP 再分发许可。PyInstaller、Nuitka、内部版、客户版和工程师版均不得包含 `IPOP.EXE` 或 `tools/windows-x64/ipop` 目录。发布脚本只从 `resources/tools/windows-x64/fping` 和 `resources/tools/windows-x64/iperf3` 白名单复制到包内 `tools/windows-x64/`；最终目录或 ZIP 检测到 IPOP 时以“检测到未经确认可再分发的第三方工具 IPOP.EXE，已停止构建发布包。”中止，不删除开发机上的本地文件。详见 [IPOP_v4.1_notice.md](IPOP_v4.1_notice.md)。

## 发布目录约束

构建输出必须进入 `dist/` 下的版本目录，不污染项目根目录。

当前发布白名单：

```text
NetConsole.exe
_internal
data
runtime
tools
```

禁入目录：

```text
docs
tests
project
netconsole
```

说明：

- `docs/`、`tests/`、`scripts/` 不应进入用户发布包。
- `src/netconsole/` 源码目录不应以源码形式进入发布包。
- 发布 zip 使用白名单枚举。
- 打包后有发布目录和 zip 校验，防止开发目录进入包。

## PyInstaller 与 Nuitka

PyInstaller：

- 生成 onedir 应用目录。
- 需要完整保留应用目录结构。
- 复制工具、创建 `data/`、`runtime/logs/`。

Nuitka：

- 当前主线支持 onefile 输出。
- 最终目录也会准备 `data/`、`runtime/`、`tools/`。
- 发布目录和 zip 均需通过白名单校验。

## QFluentWidgets 打包要求

- 只打包 `PySide6-Fluent-Widgets==1.11.2` 对应的 `qfluentwidgets`，不要混入 PyQt / PyQt6 / PySide2 版本。
- 保留 `qfluentwidgets` 包内资源、图标和样式文件。
- Mica / Acrylic / 毛玻璃效果默认关闭；打包后即使特效不可用，也必须降级为普通背景并正常启动。

## 内部版和客户版

发布脚本支持：

```text
--build-editions internal
--build-editions customer
--build-editions engineer
--build-editions both
--build-editions all
```

功能 profile：

- internal 默认 full。
- customer 默认 customer。
- engineer 默认 full；客户 profile 中“工程师打包”开启时，`both` 构建会额外生成 engineer 包，但工程师包同样不携带 IPOP。
- 客户版可嵌入功能隐藏配置。
- 客户版内部调试解锁口令只作为构建期 PBKDF2 哈希写入，不写明文密码。
- 功能开关配置页只允许源码开发态显示，任何冻结/安装包运行态（包括 internal/engineer）都不注册该入口。

## 进程退出约定

- 主程序明确退出时，应等待或回收内置子任务/进程。
- 内置 fping / iperf 等工具需要随主程序明确收尾。
- 外部 WinSCP 属于用户启动的外部进程，主程序退出时不强制处理。
- 外部 IPOP 同样属于用户明确启动的独立程序，主程序退出时不强制结束。

## 验证

源码和冻结包均需验证统一启动参数：`--mode auto|qt|web|server`。`web/server` 入口必须在未导入 PySide6 的条件下完成分派；`web` 浏览器启动失败只记录诊断并保持 Core Runtime，`server` 不得主动打开浏览器且只允许回环地址。Qt probe 必须保持轻量导入，不得依赖 FastAPI/Core 成功导入。真实 Qt platform plugin 与 WebEngine 能力仍需在 Windows 图形环境单独验证，不能用 offscreen 单测替代。

常用验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_release_system.py tests\test_nuitka_release_script.py
```

实际发布前还应执行脚本自带 smoke test；非交互构建可按脚本参数显式跳过，但需要说明原因。

发布后还需确认 `_internal/netconsole/assets/web/` 中同时存在 `index.html` 和 `web-build-meta.json`，并通过启动日志核对 `frontend_source_type=packaged` 及前后端 build id 一致。

还需验证冻结态内部入口：普通任务使用 `--background-worker --job`，导出使用 `--export-worker --job`；源码态分别使用 `python -m netconsole.background_worker` 和 `python -m netconsole.export_worker`。

Windows Server 支持必须按 [Windows Server 测试清单](07-windows-server-test-checklist.md) 实机或虚机验证；构建成功本身不代表已覆盖所有 Server 版本、权限和图形环境。

## 禁止事项

- 禁止把项目根目录整体复制进 release。
- 禁止把 docs/tests/project 误打进用户包。
- 禁止构建后在项目根生成运行时数据目录。
- 禁止在文档中写真实解锁口令、账号或密码。
