# 构建与发布脚本

本目录负责 PyInstaller/前端元数据、依赖与许可证检查、SBOM、运行工具校验和 Windows 发布编排。它只生成构建产物，不把产物当源码提交。

主要入口为 `build_release.py`、`release.py`、`check_packaged_runtime.py` 和清单脚本。验证使用 Python 虚拟环境及 `docs/BUILD_AND_RELEASE.md` 规定的命令，构建临时目录完成后清理。

## 用途与边界

本目录负责编译、依赖/许可证检查、SBOM、PyInstaller 制品和 Windows 发布编排；不实现产品业务，不把构建输出作为源码或运行数据。

## 主要入口

`package_windows.ps1` 是 Windows 正式安装包的一键入口，`package_windows.bat` 可用于双击或从传统终端启动。它先检查工作区 clean、`HEAD` 已推送至 upstream、项目 `.venv` 和 pnpm，再按锁文件安装 Web/Electron 依赖、运行两端测试并复用 Electron 的 `pnpm package` 正式链路；构建完成后会再次核对 release manifest、文件大小和 SHA-256。`-PreflightOnly` 只执行环境与 Git 预检。该 `.ps1` 保持 UTF-8 BOM，以便 Windows PowerShell 5.1 在执行编码初始化语句前正确解析中文。

`build_release.py`/`release.py` 编排底层发布，`check_packaged_runtime.py`、`check_runtime_deps.py`、`pyinstaller_artifact_inventory.py` 和工具校验脚本提供门禁。

## 依赖关系

脚本依赖项目虚拟环境、`pyproject.toml`、requirements/constraints、`resources/tools` 和版本/资源 helper；前端构建由 `apps/web` 的 pnpm 脚本负责。

## 数据与状态

输入为源码、锁定依赖、版本和审计清单；构建状态、spec、日志和制品只进入 `dist/` 下的受控临时路径，不写入 `src/`。

## 测试与修改

修改构建参数、来源或制品清单时运行 build/release、PyInstaller inventory、license/SBOM 和 runtime Guard 测试，并检查 Windows smoke。

## 生成与清理

允许生成 `dist/agent`、PyInstaller 临时 build/spec、安装包和 SBOM；失败或验收后使用已有清理脚本清除临时输出，不删除用户数据。

## 相关文档

参见 [构建与发布](../../docs/BUILD_AND_RELEASE.md)、[第三方依赖](../../docs/THIRD_PARTY_DEPENDENCIES.md) 和 [仓库目录规范](../../docs/development/repository-layout.md)。
