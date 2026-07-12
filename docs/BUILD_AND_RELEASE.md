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

## 外部工具要求

构建前会检查工具源文件。当前 `project/build_config.py` 要求：

```text
tools/fping_v5/fping.exe
tools/fping_v5/cygwin1.dll
tools/iperf/iperf3.exe
tools/IPOP_v4.1/README.md
docs/IPOP_v4.1_notice.md
```

运行时工具路径由代码解析，不允许写死用户本机路径。IPOP 由用户从网络工具箱明确点击后通过 Windows `runas` 请求管理员权限启动，NetConsole 不等待该外部程序退出；缺文件、非 Windows 平台、UAC 拒绝或系统启动失败必须给出明确提示。

IPOP 二进制不属于普通构建的必需输入。仓库没有可核验的 IPOP 再分发许可，因此普通开源包、内部包和客户包均排除 `IPOP.EXE`。只有显式构建工程师包时，打包前检查才要求构建机本地存在 `tools/IPOP_v4.1/IPOP.EXE`，并将其复制到工程师包；此行为不代表授权已确认。对外分发前必须补齐 LICENSE/NOTICE 或移除二进制，详见 [IPOP_v4.1_notice.md](IPOP_v4.1_notice.md)。

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
- engineer 默认 full；客户 profile 中“工程师打包”开启时，`both` 构建会额外生成 engineer 包。
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
