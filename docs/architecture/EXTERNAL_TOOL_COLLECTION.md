# 工具集

## 产品边界

“工具集”是 Electron Desktop 的本机第三方 Windows 工具启动器，Feature key 为 `module.tools`，路由为 `/tools`。它记录用户主动选择的 `.exe`，支持分类、收藏、常用排序、路径状态、程序图标、编辑、重新定位、启动权限和资源管理器定位。

工具程序不复制到 NetConsole 安装目录，也不进入 Python Backend、局点数据库、数据根、局点切换、`.ncsite` 或 `.ncresult`。主导航中的“工具集”包含“外部工具”、流量测试、连通性检测、无线扫描和网络测试组件；其中“外部工具”正式使用 `/tools` 路由和本页面，网络测试组件 iperf3 与 fping 由独立页面统一维护，支持内置组件优先和显式自定义回退，不自动登记为第三方 EXE。SecureCRT、Xshell 与 PuTTY 的用户可见配置入口位于“外部工具”页面；工具集默认预置这三张 `system_setting` 引用卡片，启动和定位时实时读取外部终端配置，不复制路径。

IPOP 是工具集中的普通独立工具。首次读取 schema v2 Store 时，Main 从兼容保留的旧 `ipop_path` 尝试一次迁移：空路径直接记录完成；有效 `IPOP.EXE` 在按规范化路径去重后加入“网络工具”并收藏；已存在相同路径只记录完成；无效路径或写入失败保持迁移可重试且不清除旧设置。新版系统设置 UI 和 Renderer Bridge 不再暴露 IPOP 选择或 `launch_ipop`，Python 字段与后端动作仅保留一个版本的兼容读取。

Browser 开发模式不显示导航，路由守卫拒绝直接访问；不存在 HTTP 启动、下载或 URL 回退。

## 数据与恢复

唯一持久化文件位于 Electron `app.getPath('userData')/external-tools.json`，schema 当前为 v2。v1 文件在读取时原位无损升级，旧工具补充独立来源、普通启动权限和管理员启动统计默认值。v2 的工具来源为 `independent` 或 `system_setting`；系统设置引用只保存 `source_key=securecrt|xshell|putty`，其 `executable_path / working_directory` 固定为 `null`。自定义图标复制到 `app.getPath('userData')/external-tools/icons/`，单文件上限 5 MiB；删除工具或替换图标只清理该记录对应的缓存，不删除真实 EXE。

Store 对分类、工具、UUID、路径、参数、时间和未知字段做严格校验。路径去重使用 Windows 规范化并忽略大小写；所有变更经过同一串行队列，以同目录临时文件和原子替换提交。JSON 损坏或 schema 不支持时，原始字节保留为带时间戳的 `.corrupt-*` 诊断副本，再恢复默认分类；写入失败明确返回 UI，不静默吞掉。

默认分类是网络工具、终端工具、分析工具、厂商工具和其他工具。“其他工具”承担删除非空分类时的受控转移，因此不能删除。

## IPC 与启动安全

Renderer 只通过 preload 暴露的 `external-tools:*` 固定 IPC 调用。Main 对每次请求重复验证受信 Renderer、严格 DTO、UUID、字符串长度、绝对 Windows 路径、`.exe` 扩展名和参数数组；自定义图标选择只向 Renderer 返回十分钟有效的 `selectionId` 和 data URL，不返回图标源路径。

启动请求严格限制为 `{ toolId, launchMode: "normal" | "administrator" }`；“在资源管理器中显示”只接收 `toolId`。Renderer 不能传 EXE、参数、工作目录或命令。Main 从 `ExternalToolStore` 取得已登记记录，系统设置引用还会实时读取外部终端路径，然后重新检查 EXE、普通文件和工作目录。

普通启动使用：

```text
child_process.spawn(executable_path, arguments, {
  shell: false,
  detached: true,
  stdio: "ignore",
  cwd: working_directory
})
```

管理员启动由 Electron Main 调用打包在 `resources/native/netconsole-elevated-launcher.exe` 的最小 Go helper。Main 先完成同样的可信 Store 解析和复验，再以固定 JSON stdin、空 argv、`shell:false` 启动 helper；helper 再次校验结构、路径与参数并调用 Win32 `ShellExecuteExW`，固定 `lpVerb="runas"`。禁止提升 `NetConsole.exe` 或当前应用可执行文件，也不提升 Backend、Renderer 或整个应用。

工具可配置 `normal / ask / administrator` 启动权限；卡片菜单还可单次请求管理员权限。普通进程发出 `spawn` 成功事件，或 helper 成功发起提升后，才更新 `launch_count / last_launched_at / last_launch_mode`，管理员成功时另增 `administrator_launch_count`。UAC 取消返回 `status=cancelled / errorCode=ELEVATION_CANCELLED`，使用独立提示且不计数；路径失效、普通启动失败或 helper 异常同样不计数。

实现不调用 `exec / execSync`，不使用 PowerShell、CMD、`shell:true` 或命令字符串，也不保存管理员密码或绕过 UAC。`.bat`、`.cmd`、PowerShell、管道、重定向、`&&` 和 `||` 不在支持范围内。

程序图标优先由 `app.getFileIcon` 生成 PNG data URL，并按路径做有界内存缓存；Renderer 不使用 `file://` 读取本地文件。单个图标或工具状态失败不会阻断其他工具列表。

## 验收边界

自动测试覆盖 v1 到 v2 升级、IPOP 幂等迁移/失败重试、终端引用、Store 增删改/并发/损坏恢复/图标清理、IPC 双重验证、preload 映射、普通与管理员启动请求、UAC 取消、失败不计数、自身提升拒绝、浏览器拒绝、导航/路由一致性、空状态、搜索、失效路径与收藏/常用排序。以下状态保持 `IMPLEMENTED_UNVERIFIED`，仍需 Windows Electron 实机验证：

- 原生 EXE、目录和图标选择器；
- 真实第三方 EXE 的启动、焦点和关闭后主窗口可用性；
- EXE 图标读取及不同 DPI 展示；
- 开发态与正式安装包重启持久化；
- 移动/卸载程序后的重新定位；
- 真实 UAC 接受和取消、普通 Windows 用户、不同第三方工具及系统终端路径动态变更；
- 正式安装包包含并可调用正确架构的 helper，且 helper 启动时无控制台闪现；
- Windows Server 2012 兼容性和没有权限/需要管理员权限的程序错误文案。
