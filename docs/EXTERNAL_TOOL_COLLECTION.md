# 工具集

## 产品边界

“工具集”是 Electron Desktop 的本机第三方 Windows 工具启动器，Feature key 为 `web.tool_collection`，路由为 `/tools`。它记录用户主动选择的 `.exe`，支持分类、收藏、常用排序、路径状态、程序图标、编辑、重新定位、启动和资源管理器定位。

工具程序不复制到 NetConsole 安装目录，也不进入 Python Backend、局点数据库、数据根、局点切换、`.ncsite` 或 `.ncresult`。现有系统设置中的 iperf3、fping、IPOP 和外部终端路径仍是内置业务依赖；工具集记录是独立快捷启动项，两套配置不互相写入。

Browser 开发模式不显示导航，路由守卫拒绝直接访问；不存在 HTTP 启动、下载或 URL 回退。

## 数据与恢复

唯一持久化文件位于 Electron `app.getPath('userData')/external-tools.json`，schema 当前为 v1。自定义图标复制到 `app.getPath('userData')/external-tools/icons/`，单文件上限 5 MiB；删除工具或替换图标只清理该记录对应的缓存，不删除真实 EXE。

Store 对分类、工具、UUID、路径、参数、时间和未知字段做严格校验。路径去重使用 Windows 规范化并忽略大小写；所有变更经过同一串行队列，以同目录临时文件和原子替换提交。JSON 损坏或 schema 不支持时，原始字节保留为带时间戳的 `.corrupt-*` 诊断副本，再恢复默认分类；写入失败明确返回 UI，不静默吞掉。

默认分类是网络工具、终端工具、分析工具、厂商工具和其他工具。“其他工具”承担删除非空分类时的受控转移，因此不能删除。

## IPC 与启动安全

Renderer 只通过 preload 暴露的 `external-tools:*` 固定 IPC 调用。Main 对每次请求重复验证受信 Renderer、严格 DTO、UUID、字符串长度、绝对 Windows 路径、`.exe` 扩展名和参数数组；自定义图标选择只向 Renderer 返回十分钟有效的 `selectionId` 和 data URL，不返回图标源路径。

启动和“在资源管理器中显示”只接收 `toolId`。Main 从 `ExternalToolStore` 取得已登记记录并重新检查 EXE、普通文件和工作目录，然后使用：

```text
child_process.spawn(executable_path, arguments, {
  shell: false,
  detached: true,
  stdio: "ignore",
  cwd: working_directory
})
```

只有子进程发出 `spawn` 成功事件后才 `unref()` 并更新 `launch_count / last_launched_at`；失败不计数。实现不调用 `exec / execSync`，不拼接命令字符串，不自动提权，也不记录启动参数。`.bat`、`.cmd`、PowerShell、管道、重定向、`&&` 和 `||` 不在 v1 支持范围内。

程序图标优先由 `app.getFileIcon` 生成 PNG data URL，并按路径做有界内存缓存；Renderer 不使用 `file://` 读取本地文件。单个图标或工具状态失败不会阻断其他工具列表。

## 验收边界

自动测试覆盖 Store 初始化/增删改/并发/损坏恢复/图标清理、IPC 双重验证、preload 映射、启动参数和 spawn 选项、浏览器拒绝、导航/路由一致性、空状态、搜索、失效路径与收藏/常用排序。以下仍需 Windows Electron 实机验证：

- 原生 EXE、目录和图标选择器；
- 真实第三方 EXE 的启动、焦点和关闭后主窗口可用性；
- EXE 图标读取及不同 DPI 展示；
- 开发态与正式安装包重启持久化；
- 移动/卸载程序后的重新定位；
- Windows Server 2012 兼容性和没有权限/需要管理员权限的程序错误文案。
