# Tray 局点状态同步与重启

## 问题原因

此前 Electron Main 的 `TrayController` 在 `TrayRuntimeContext` 中保存了 `activeSiteId`、局点名称和局点列表。该上下文只在启动或部分 UI 操作后更新，因此 Backend 已切换到新局点时，Tray 仍可能展示启动时的旧局点。Backend 离线时也可能继续展示这份旧快照。

局点的唯一事实来源现在是 Backend `SiteApplicationService` 提供的：

- `GET /api/v1/sites/active`：当前局点；
- `GET /api/v1/sites`：局点列表；
- `POST /api/v1/sites/{site_id}/activate`：统一局点切换入口。

Tray 只保留 Backend/窗口/任务数量等运行态，不保存 current site。每次 Tray 菜单刷新都重新读取 Backend，名称只用于显示，所有选中和切换判断都使用 `site_id`。

## 修改方案

`TrayController.refreshTraySiteState()` 获取一次性的 Backend 状态输入并重建菜单。输入无效、Backend 不在线或读取失败时，菜单进入 fail-closed 状态：显示 `Backend Offline`，清除当前局点文字，禁用快速切换，不复用上一次局点。

系统设置、Tray 快速切换和导入完成后的自动切换都进入 Renderer `coordinateSiteSwitch()`。Backend 成功激活后，Renderer 重新读取当前局点并更新页面，再发送 `netconsole:current-site-changed`；随后通过受信任 IPC 请求 Electron Main 执行 `refreshTraySiteState()`。Backend 的异常回滚由同一个 `SiteApplicationService.switch_site()` 负责，Renderer 不做乐观更新。

```text
request switch(site_id)
        |
        v
Renderer preflight / workspace checkpoint
        |
        v
Backend SiteApplicationService.switch_site(site_id)
        |
        +-- failure -> Backend restores previous site -> Renderer/Tray keep old id
        |
        +-- success -> read /sites/active + /sites
                         |
                         v
                current-site-changed
                         |
                         +-> Renderer header + Settings refresh
                         |
                         +-> IPC refreshSiteContext
                                  |
                                  v
                         Main refreshTraySiteState()
```

The site list may be reordered without affecting the radio selection: the checked item is `item.siteId === activeSiteId`, never an array index or display-name comparison.

## Tray 菜单

Windows Tray 菜单包含：

1. 打开 NetConsole；
2. 快速切换局点（按 Backend 当前 `site_id` checked）；
3. 重启软件；
4. 退出 NetConsole。

现有的新建工作区和任务中心入口继续保留。快速切换点击只发送 `site_id`，随后由系统设置页复用同一切换协调器；在切换期间菜单禁用，已进入队列的快速请求按最新请求继续收敛。

## 重启机制

“重启软件”不是 Renderer `reload`。Main 在调用 `app.relaunch()` 前从当前 Backend 读取并校验：

- 当前 `active_site_id`；
- 当前数据路径；
- 运行模式 `DEV` 或 `PRODUCTION`。

持久模式将这些值写入受控 `bootstrap.json`（不写入 Token、密码或其他凭据），然后进入现有的受管关闭流程：关闭 Renderer/窗口、停止 Backend、退出当前 Electron process。`app.relaunch()` 启动新进程后，启动参数只作为 Backend 启动提示；启动完成后仍重新读取 Backend `/sites/active` 与 `/sites`，不相信旧缓存，并据此刷新 Renderer 和 Tray。

Backend 尚未 ready 时，重启请求被拒绝，不会写入不完整的局点状态。

## 验收标准

- PASS：Backend 当前局点、Renderer 顶部、系统设置和 Tray 显示使用同一个 `site_id`；
- PASS：系统设置切换后 Tray 名称和 radio checked 同步；
- PASS：Tray 切换后 Renderer 页面同步；
- PASS：切换失败时四个界面不发生乐观切换，旧 checked 保持有效；
- PASS：快速请求 A → B → C 最终收敛到 C；
- PASS：局点列表排序变化不改变 checked 项；
- PASS：Backend 离线时 Tray 显示 `Backend Offline`，不显示旧局点；
- PASS：Tray 重启执行真实 `app.relaunch()`，不是窗口 reload；
- PASS：重启后重新从 Backend 读取，当前局点与 Tray 一致。

自动验证覆盖 Tray Controller、切换协调器、导入自动切换、Bootstrap 重启检查点和 Electron 合同测试。真实 Windows 右键菜单、系统通知区域交互及跨进程重启仍需在本机按上述清单人工点击确认；源码 smoke 不能替代该人工验收。
