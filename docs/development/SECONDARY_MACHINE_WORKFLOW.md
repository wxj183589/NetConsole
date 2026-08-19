# 副机开发与验证流程

本文定义 NetConsole 在“副机”上的开发边界。副机是代码修复、新功能开发和定向验证环境；“主机”是执行正式 Full/Customer 构建、安装包 smoke 和发布制品验收的环境。两者使用同一仓库代码和锁定依赖，但职责不同。

## 结论

副机环境可用于日常开发，不要求每次修改都重新生成安装包。副机不作为 v1.5.1 正式安装包的发布构建机；正式构建和安装包验收以主机为准。

## 副机允许执行

- Python、Vue Renderer、Electron Main/Preload 和 Go Agent 的代码修复与新增功能；
- 与改动直接相关的 pytest、Vitest、Electron test、Go test；
- Ruff、Python 类型/语法检查、Renderer typecheck/build、Electron typecheck/build:main；
- `scripts.quality.local_gate` 的 FAST/CONSUMER 定向门，以及普通开发调试和本地回环 smoke；
- 文档、测试、解析器、Service、Repository 和 UI 的迭代验证；
- 将已验证的代码提交并推送到远端，供主机继续执行最终集成门禁。

副机验证必须使用隔离测试根 `D:\study\test-data\NetConsole\<run-id>`，不得读取或修改 `D:\NetConsoleData`、机器级 DataRoot、真实局点数据库、真实会话或正式报告。

## 副机默认不执行

除非本轮任务明确需要排查构建问题，副机默认不执行以下耗时或发布专属流程：

- PyInstaller Backend 冻结构建；
- Electron `pnpm package`、electron-builder、NSIS 安装包生成；
- Full/Customer edition staging、正式安装包 package smoke；
- 正式 release manifest、SHA-256 发布清单和 `D:\study\release\NetConsole\<version>` 制品发布；
- 真实 Windows GUI 安装、升级、修复、卸载和跨机器验收。

副机可以运行 Renderer build 或 Electron `build:main` 来验证源码，但这不等同于正式安装包构建，也不能把该结果记为 release/package gate 通过。不要为了日常代码修改在副机反复生成安装包或维护正式制品目录。

## 必须转到主机的情况

代码推送后，以下变化应在主机重新执行对应 Full/Customer 发布门禁：

| 变化范围 | 主机复验 |
| --- | --- |
| PyInstaller、NSIS、electron-builder、安装脚本或 package smoke | 完整 Backend/Electron/NSIS/package smoke |
| Python/Node/Go 依赖、锁文件、构建工具或第三方工具 | 依赖闭包检查、完整构建和许可证/SBOM 门 |
| DataRoot、安装目录、Feature/edition、版本身份或发布元数据 | 安装器契约、包元数据和版本一致性门 |
| `apps/agent` 的正式打包、sidecar 或随包工具 | Agent 构建、工具 Guard 和受影响 package smoke |
| 发布候选提交或 `main` baseline | 完整测试基线、正式制品生成和人工 Windows 验收 |

主机只从已提交、已推送且工作区 clean 的提交生成正式制品。副机上的本地构建结果、`dist` 中间文件和测试日志不能直接作为发布制品，也不能替代主机的最终验证。

## 推荐工作流

1. 副机从最新远端同步代码，确认工作区和分支状态。
2. 在副机完成代码修改、定向测试、静态检查和必要的 Renderer/Electron 源码构建。
3. 检查 `git diff --check`、测试数据目录和未跟踪文件；提交并推送中文提交信息。
4. 主机拉取该提交，按变更风险运行 `local_gate`；涉及发布边界时再运行完整 Full/Customer 构建和 package smoke。
5. 只有主机生成的 release manifest、SHA-256 和安装包，才可进入正式发布目录或人工安装验收记录。

## 状态记录

“副机定向验证通过”只表示代码适合继续开发或交给主机集成，不表示安装包已发布。正式包的 `real_windows_install_status`、真实设备、跨机器和长时运行状态仍按[测试基线](../testing/BASELINE.md)单独记录；自动化 package gate 与真实 GUI 验收不可互相替代。
