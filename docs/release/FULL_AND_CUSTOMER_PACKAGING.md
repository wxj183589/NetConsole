# Full Installer 与 Full Portable 交付

NetConsole v1.5.13 的当前正式产品只有：

- Full Installer：Windows NSIS 安装版。
- Full Portable：Windows 免安装版。

两种形态共享同一套 Electron、Vue、Python Backend、Feature Registry 和数据根契约；Portable 只改变启动与数据根承载方式，不裁剪正式功能。

## 当前交付边界

正式包使用包内只读 `full/full` Feature Profile。开发中、隐藏、危险、未验收和 internal-only 能力仍由 Feature Registry 与现有 Feature Gate 保护，不因“全功能”名称而自动开放。

旧 Customer 模板、客户版密码字段、Customer 运行时解锁和功能矩阵服务仅作为历史配置/旧构建兼容材料保留。它们不再有 Renderer 导航、页面、版本号隐藏操作、Backend HTTP API 或当前正式打包入口，也不能重新启用 Customer 交付。

历史报告和 CHANGELOG 中确实发生过的 Customer 构建保持原样，不将历史事实改写为从未存在。

## 构建命令

正式构建要求 Windows、干净工作区、HEAD 与 upstream 对齐并通过既有发布门禁：

```powershell
.\scripts\build\package_windows.ps1 -Edition full
```

Electron 工作目录中的入口为：

```powershell
pnpm package
pnpm package:full
pnpm package:portable
```

`pnpm package` 等价于 `package:full`。`package:portable` 生成 Full Portable 候选；它使用程序目录或显式 Portable 数据根，不自动写入正式 `release` 目录。

以下入口已退役并不再接受：`package:customer`、`package:all`、`both` 选择，以及 Customer 维护密码环境变量作为正式构建输入。

## 运行时与兼容性

正式包不读取外部 `feature_flags.local.json` 作为产品功能开关。旧配置文件仍可由兼容层识别或升级，但不会恢复 Customer 入口，也不会改变 Full/Portable 的正式功能边界。

旧 `/feature-flags` 地址保留一个明确的退役提示页，避免旧书签出现白屏；它不是功能配置页面。系统设置不再显示版本类型、客户预览、运行时覆盖清除或 Feature Gate 重载操作。

版本号只打开更新日志。Shift-click、客户版密码、临时 Full 解锁和重新锁回 Customer 均已从当前产品链移除。

## 制品验收

Installer 与 Portable 都必须复核：

- `edition=full`、`feature_profile=full` 和 Full Feature Profile；
- Installer、Backend、Renderer 的 commit 与构建身份一致；
- `admin_unlock_enabled=false`，包内不存在客户维护密码哈希；
- 正式功能可用，但开发/隐藏/internal-only 能力仍关闭；
- `package_smoke=PASS`、`packaged_dirty=false`，真实 Windows 安装/升级/卸载另行记录。

自动构建成功不能替代真实 Windows GUI 安装、升级、卸载、签名或现场设备验收。历史 Customer 制品和报告不得为了当前 Full-only 门禁删除。
