# 完整版与客户版打包

NetConsole 使用同一套 Electron、Vue 和 Python Backend 源码生成两个独立安装包，不复制客户版工程。

## 功能配置职责

| 配置目标 | 文件或作用域 | 保存后影响 | 用途 |
| --- | --- | --- | --- |
| 完整版默认配置 | `config/profiles/features/full.json` | 不改变当前运行状态 | 下次构建 Full 安装包 |
| 客户版交付配置 | `config/profiles/features/customer.json` | 不改变当前运行状态 | 下次构建 Customer 安装包 |
| 当前会话预览 | Backend 当前进程内存 | 立即刷新导航、路由和 Backend Gate | 验证尚未保存的模板草稿 |

源码开发态的“版本与功能交付”是 Full/Customer 模板的唯一矩阵编辑入口。系统设置不再提供第二套运行时矩阵，只显示当前版本状态，并可退出会话预览、清除历史运行时覆盖或重新加载 Feature Gate。会话预览不写模板或 `runtime/feature_flags.local.json`，退出预览或重启 Backend 后恢复。旧覆盖文件仅作为升级兼容状态展示，必须由用户显式确认后写回空覆盖集合；正式包继续忽略该文件。

客户版每项功能使用单一三态，避免“纳入客户版”和运行状态相互冲突：

| 客户版状态 | `client_package` | `enabled` | `visible` |
| --- | ---: | ---: | ---: |
| 不交付 | `false` | `false` | `false` |
| 交付并显示 | `true` | `true` | `true` |
| 交付但隐藏 | `true` | `true` | `false` |

完整版仍使用“显示并启用 / 隐藏入口但保留能力 / 关闭”。业务分类默认只展示模块，展开后显示页面与操作；`cap.*` 技术能力单独折叠并只读，由依赖检查和自动修复带出。

Feature Registry 明确区分三种关系：

- `parent_id` 只表达界面树和交付父级闭包，不参与运行时 Gate 依赖计算；
- `requires` 表达运行时技术依赖；
- `delivery_requires` 表达客户版交付依赖。

Backend 的检查接口返回结构化依赖问题，页面按缺失依赖聚合展示。自动修复只修改当前草稿：运行依赖会启用并隐藏，客户交付依赖还会纳入客户版；内部、开发中、隐藏或已停用能力不能通过自动修复进入客户版。用户确认保存后才写 Full/Customer 模板。

当前客户模板已将 `web.rail_train_online` 和 `web.rail_task_control` 作为“交付但隐藏”的必要能力，并明确排除未交付的 Online MR 会话定位和删除动作。

## 模板门禁

`scripts/build/prepare_electron_edition.py` 在写入 Electron Backend 内嵌资源前校验目标 Profile；`scripts/build/build_release.py` 的各版本载荷准备复用同一入口。校验覆盖 Registry 中的功能状态、运行依赖、客户交付父级、`delivery_requires`、内部功能和非正式状态泄漏。Full 或 Customer 模板存在问题时构建立即失败，并以 `FULL PROFILE INVALID` 或 `CUSTOMER PROFILE INVALID` 列出具体依赖链。

## 构建命令

正式构建仍要求 Windows、干净工作区、最终提交已推送到 upstream，以及完整的既有发布门禁。

构建两个版本前，在当前 PowerShell 会话设置客户版维护密码：

```powershell
$env:NETCONSOLE_CUSTOMER_UNLOCK_PASSWORD = "使用独立的维护密码"
.\scripts\build\package_windows.ps1
```

也可在 `apps/desktop_electron` 中按版本执行：

```powershell
pnpm package:all
pnpm package:full
pnpm package:customer
```

## 一键本地打包

项目根目录的 `一键打包安装包.cmd` 是面向 Windows 用户的双击入口。它只负责定位仓库、初始化 UTF-8 控制台并调用 `scripts/build/package_local.ps1`；正式构建、版本注入和安装包 Gate 仍由 `scripts/build/package_windows.ps1` 及现有 `package:full`、`package:customer`、`package:all` 完成。

机器需要安装 Git、包含 Corepack 的 Node.js 24 和项目 `.venv`，无需另外全局安装 pnpm。脚本优先使用当前 `PATH` 中的 `pnpm.cmd`；未找到时通过 Node 同目录的 Corepack 调用固定 `pnpm@11.16.0`，并在不会被正式构建清理的 `dist/_package_tool_shims` 中创建仅供本轮子进程继承的临时代理，同时把代理绝对路径显式传给嵌套安装器构建进程。构建结束或失败后会恢复进程原始 `PATH` 和相关进程环境，并删除代理及空容器目录，不执行 `corepack enable`、全局 npm 安装或系统环境变量修改。如果 Node 不含 Corepack，环境预检会在测试和构建前明确停止。

普通使用时直接双击脚本，默认生成 Full 和 Customer 两个版本。也可以从命令行选择单个版本或只做预检：

```text
一键打包安装包.cmd full
一键打包安装包.cmd customer
一键打包安装包.cmd both
一键打包安装包.cmd preflight
```

Customer 或 `both` 构建如果当前进程没有有效的 `NETCONSOLE_CUSTOMER_UNLOCK_PASSWORD`，脚本会使用 SecureString 安全读取并要求确认，密码只在当前 PowerShell 进程及其构建子进程中存在。构建结束或失败后都会恢复原环境变量；密码不会写入命令行、日志、JSON、摘要、脚本或 Git 配置。Full-only 构建不要求客户版密码。

每次运行会在 `dist/package-logs/` 生成独立的 `package-YYYYMMDD-HHmmss.log`。验证通过的制品先写入 `dist/release/.staging-<唯一 ID>`，全部校验完成后再原子重命名为 `dist/release/v<版本>-<Git 短 SHA>-<时间戳>`，目录内包含本次选择对应的安装包、`.exe.release.json`、`SHA256SUMS.txt`、`BUILD_SUMMARY.json` 和 `BUILD_SUMMARY.md`。成功后自动打开该目录；Explorer 打开失败不会改变构建结果。失败只清理本次 staging，不删除已有发布目录或业务数据。

脚本会阻止脏工作树、HEAD 未与 upstream 对齐、Git/Node/Corepack/pnpm/`.venv` 不可用、依赖或磁盘预检失败以及并行打包。`preflight` 只执行环境与 Git 检查，不安装依赖、不运行测试、不生成安装包。摘要明确记录“自动构建和包内校验已通过；真实 Windows GUI 安装验收仍为 PENDING。”，自动成功不等同于真实安装验收通过。

输出名称包含版本类型：

```text
NetConsole-Full-<version>-<git-short>-x64-setup.exe
NetConsole-Customer-<version>-<git-short>-x64-setup.exe
```

每个安装包都有独立的 `.exe.release.json`。最终 Gate 会直接打开 NSIS 内层载荷，核对：

- Backend 的 `edition` 与 `feature_profile`；
- Full 包不携带客户维护密码哈希；
- Customer 包携带可验证的 PBKDF2 哈希参数；
- 明文维护密码不出现在包内身份 JSON；
- Installer、Backend 和 Frontend commit 一致且 `dirty=false`；
- 原有 NSIS、数据根、PE 版本资源、SHA-256 和发布策略门禁全部通过。

## 客户版临时开启完整功能

Customer 包默认执行 `customer.json`。在桌面右上角版本号处按住 `Shift` 单击，可输入打包时配置的维护密码。校验成功后，Backend 仅在当前进程会话中切换到包内 `full.json`：

- 不写客户数据；
- 不写浏览器 `localStorage`；
- 不启用外部 Feature override 文件；
- 重启后自动恢复客户模式；
- 再次 `Shift` 单击版本号可主动恢复客户模式；
- 连续错误密码会触发短时限流。

维护密码只在打包进程中通过环境变量传入，仓库和客户版模板不得保存明文密码。

## 功能业务分类

版本与功能交付不再只按父级粗略归类，当前分为：基础与桌面、任务与 Agent、设备管理、AC 与 FIT-AP、配置采集与文件、轨道交通基础资料、轨旁 AP、列车在线与无人值守、车载 MR 采集与分析、MESH 日志分析、轨道交通综合、网络测试与工具集、日志/命令/系统维护、内部与实验功能。
