# 完整版与客户版打包

NetConsole 使用同一套 Electron、Vue 和 Python Backend 源码生成两个独立安装包，不复制客户版工程。

## 功能配置职责

| 配置目标 | 文件 | 保存后影响 | 用途 |
| --- | --- | --- | --- |
| 当前运行时 | 数据根 `runtime/feature_flags.local.json` | 立即刷新当前实例导航、路由和 Backend Gate | 开发调试、当前实例临时配置 |
| 完整版模板 | `config/profiles/features/full.json` | 不影响当前实例 | 下次构建 Full 安装包 |
| 客户版模板 | `config/profiles/features/customer.json` | 不影响当前实例 | 下次构建 Customer 安装包 |

“版本功能配置”页面可分别编辑 Full 与 Customer 模板。页面中的“会话预览”会临时应用草稿，但不会保存；退出预览或重启 Backend 后恢复。

客户版的“纳入客户版”与“显示/启用”是不同维度：

- 未纳入客户版：安装包运行时隐藏并禁用该能力。
- 已纳入但隐藏入口：Backend 能力保留，导航入口不显示。
- 已纳入并完全禁用：导航和 Backend Gate 均关闭。

内部专用、开发中、隐藏或已停用功能不能纳入客户版。父级和显式依赖必须形成完整的客户版依赖闭包。

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

版本功能配置不再只按父级粗略归类，当前分为：基础与桌面、任务与 Agent、设备管理、AC 与 FIT-AP、配置采集与文件、轨道交通基础资料、轨旁 AP、列车在线与无人值守、车载 MR 采集与分析、MESH 日志分析、轨道交通综合、网络测试与工具集、日志/命令/系统维护、内部与实验功能。
