# 构建与发布

当前仓库核对环境为 Python 3.13.9、PySide6 6.11.1、PySide6-Fluent-Widgets 1.11.2；依赖约束仍以 `requirements.txt` 为准，不应把本机已安装版本写成最低支持版本。

## 当前构建入口

根目录批处理：

```powershell
.\build_release.bat
.\build_nuitka_release.bat
```

核心脚本：

```text
project/build_release.py
project/build_nuitka_release.py
project/build_config.py
project/release.py
```

当前支持后端：

- PyInstaller
- Nuitka

`BuildConfig` 从 `netconsole/core/version.py` 读取应用名、版本和作者。

## Windows Go Agent

独立 Agent 不进入上述 PyInstaller/Nuitka 发布链，使用 Go 1.26.5 单独构建：

```bat
agent\scripts\build_windows.bat
```

输出为 `agent/bin/windows-x64/netconsole-agent.exe`。脚本先执行 Go 模块下载和 `go test ./...`，再以 `CGO_ENABLED=0`、`GOOS=windows`、`GOARCH=amd64` 构建。Agent 的 `config.json`、`targets.json`、Web 静态资源和运行目录契约见 [独立 Agent](AGENT.md)；主程序与 Agent 都采用 `tools/windows-x64/{fping,iperf3,ipop}` 命名，但各自工具由各自的构建或部署流程管理，不隐式互相复制。

当前 Python 发布白名单不包含 Agent。正式联合发布前需要另行确定 Agent 版本注入、代码签名、Windows 服务形态和第三方工具许可证，不得把开发态 `agent/data`、`agent/logs` 或 `agent/packages` 打入发布包。

## 外部工具要求

构建前会检查工具源文件。当前 `project/build_config.py` 要求：

```text
tools/windows-x64/fping/fping.exe
tools/windows-x64/fping/cygwin1.dll
tools/windows-x64/iperf3/iperf3.exe
docs/IPOP_v4.1_notice.md
```

运行时工具路径由统一解析器处理，不依赖当前工作目录。IPOP 是用户自行提供的可选外部工具，配置保存在现有 `settings.json` 的 `external_tools/ipop_path` 键；有效配置优先，未配置时可检查 `<应用目录>/tools/windows-x64/ipop/IPOP.EXE`。启动使用 Qt `QProcess.startDetached`，不拼接 shell 命令，也不等待该外部程序退出。

仓库没有可核验的 IPOP 再分发许可。PyInstaller、Nuitka、内部版、客户版和工程师版均不得包含 `IPOP.EXE` 或 `tools/windows-x64/ipop` 目录。发布脚本只白名单复制 `tools/windows-x64/fping` 和 `tools/windows-x64/iperf3`；最终目录或 ZIP 检测到 IPOP 时以“检测到未经确认可再分发的第三方工具 IPOP.EXE，已停止构建发布包。”中止，不删除开发机上的本地文件。详见 [IPOP_v4.1_notice.md](IPOP_v4.1_notice.md)。

## 发布目录约束

构建输出必须进入 `release/` 下的版本目录，不污染项目根目录。

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

- `docs/`、`tests/`、`project/` 不应进入用户发布包。
- `netconsole/` 源码目录不应以源码形式进入发布包。
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

常用验证：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_release_system.py tests\test_nuitka_release_script.py
```

实际发布前还应执行脚本自带 smoke test；非交互构建可按脚本参数显式跳过，但需要说明原因。

还需验证冻结态内部入口：普通任务使用 `--background-worker --job`，导出使用 `--export-worker --job`；源码态分别使用 `python -m netconsole.background_worker` 和 `python -m netconsole.export_worker`。

Windows Server 支持必须按 [Windows Server 测试清单](07-windows-server-test-checklist.md) 实机或虚机验证；构建成功本身不代表已覆盖所有 Server 版本、权限和图形环境。

## 禁止事项

- 禁止把项目根目录整体复制进 release。
- 禁止把 docs/tests/project 误打进用户包。
- 禁止构建后在项目根生成运行时数据目录。
- 禁止在文档中写真实解锁口令、账号或密码。
