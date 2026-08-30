# 构建与发布脚本

本目录负责 PyInstaller/前端元数据、依赖与许可证检查、SBOM、运行工具校验和 Windows 发布编排。它只生成构建产物，不把产物当源码提交。

主要入口为 `build_release.py`、`release.py`、`check_packaged_runtime.py` 和清单脚本。验证使用 Python 虚拟环境及 `docs/release/BUILD_AND_RELEASE.md` 规定的命令，构建临时目录完成后清理。

## 用途与边界

本目录负责编译、依赖/许可证检查、SBOM、PyInstaller 制品和 Windows 发布编排；不实现产品业务，不把构建输出作为源码或运行数据。普通打包不会修改正式版本；版本、Build Number、FileVersion、Git Hash 和 published 状态由统一构建元数据记录。

## 主要入口

`package_windows.ps1` 是 Windows 安装包链路，`package_windows.bat` 可用于从传统终端启动。项目根目录的 `一键打包安装包.cmd` 调用 `package_local.ps1`，负责单实例、日志，并在全部 Gate 通过后以 `D:\study\NetConsole-Workspace\release\<version>\build-<number>-<short-sha>` 保存构建制品；Customer 密码由 Core 统一解析器提供环境变量覆盖或内置默认值。它不会自动升级版本或将构建标记为正式发布。只有显式 release 命令才允许发布新版本并更新自动更新清单。

`build_release.py`/`release.py` 编排底层发布，`check_packaged_runtime.py`、`check_runtime_deps.py`、`pyinstaller_artifact_inventory.py` 和工具校验脚本提供门禁。

## 依赖关系

脚本依赖项目虚拟环境、`pyproject.toml`、requirements/constraints、`resources/tools` 和版本/资源 helper；前端构建由 `apps/desktop_renderer` 的 pnpm 脚本负责。

## 数据与状态

输入为源码、锁定依赖、版本和审计清单；构建状态、spec、日志和中间制品只进入 `dist/` 下的受控临时路径，不写入 `src/`。PyInstaller Backend 中间输出固定在 `dist/_build/backend-release/`，正式安装包及其元数据只持久化到 `D:\study\NetConsole-Workspace\release\<version>`。

## 测试与修改

修改构建参数、来源或制品清单时运行 build/release、PyInstaller inventory、license/SBOM 和 runtime Guard 测试，并检查 Windows smoke。

## 生成与清理

允许生成 `dist/agent`、PyInstaller 临时 build/spec、安装包和 SBOM；失败或验收后使用已有清理脚本清除临时输出。`all-build-output` 可以清理整个仓库 `dist/`，但不得删除 `D:\study\NetConsole-Workspace\release` 或用户数据。

## 相关文档

参见 [构建与发布](../../docs/release/BUILD_AND_RELEASE.md)、[第三方依赖](../../docs/release/THIRD_PARTY_DEPENDENCIES.md) 和 [仓库目录规范](../../docs/development/repository-layout.md)。
