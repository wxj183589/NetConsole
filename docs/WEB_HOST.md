# Qt WebHost

## 当前状态

阶段 5C-0 在普通 Qt 主程序中增加可复用 WebHost。它复用既有 FastAPI、Vue、Task Center、Agent Controller、Traffic Service 和 Online MR 只读 Query Service，不建立第二套 Python Core，也不通过 QWebChannel 暴露业务方法。

主程序托盘和 Fluent 顶部“更多”菜单均可打开完整 Web 控制台。WebHost 按需启动，因此仅运行原生 Qt 页面时不会监听 HTTP 端口，也不会要求 FastAPI 服务提前启动。

## 运行结构

```text
Qt Main Window / System Tray
        |
        v
WebConsoleHost
        |
        +-- QWebEngineView（可用时）
        |
        +-- 系统默认浏览器（fallback）
        |
        v
127.0.0.1 随机端口
        |
        v
Existing FastAPI + Vue + Python Core
```

本地服务只绑定 `127.0.0.1`。桌面 WebHost 每次进程启动生成新的临时会话令牌；令牌通过 `POST /__desktop_session` 建立 HttpOnly、SameSite Cookie，不进入 URL。HTTP 和 WebSocket 在会话建立前均拒绝访问。

外部浏览器 fallback 会在 `runtime/cache/` 创建临时自提交页面，令牌只存在于 POST 表单正文，文件在 60 秒后或主程序退出时删除。该令牌只保护主程序本地 WebHost，不替代 Agent 的 `X-Agent-Token`，也不会写入任务、数据库或业务日志。

## 生命周期

- 第一次打开 Web 控制台时才创建 FastAPI 服务并启动 Uvicorn 线程；
- 关闭 Web 窗口只关闭显示窗口，主程序和本地服务继续存活，可从托盘重新打开；
- 主程序明确退出时先卸载 Web 页面，再停止 Uvicorn；
- QWebEngine 不可用时主程序仍可正常启动，并自动提供外部浏览器入口；
- 普通 `python main.py` 不会在未打开 Web 控制台时监听端口。

## 构建

`scripts/build/build_release.py` 在 Python 打包前执行 `apps/web` 的 `pnpm build`，并把忽略提交的 `apps/web/dist` 作为 `netconsole/assets/web` 内部资源打入 PyInstaller/Nuitka 发布包。构建机需先完成：

```powershell
cd apps/web
pnpm install --frozen-lockfile
cd ../..
```

缺少 pnpm、`node_modules` 或 `dist/index.html` 时，发布构建明确失败，不生成缺少完整 Web 页面的桌面包。

## 当前边界

- 当前 Web 页面包含 Dashboard、只读任务中心、Agent 管理、AC FIT-AP 资源、AC Mesh-Link 在线监控、Traffic 和只读 Online MR 实时展示；任务中心通过 GET-only `/api/job-center` 查询任务快照、结构化事件和 Online MR 映射，不提供 stop、force-stop、delete 或 retry；
- 任务列表按运行状态动态使用 2 秒或 5 秒轮询，连续失败后降为 10 秒；详情每 2 秒刷新，日志展开后每秒读取最后 300 条，页面隐藏或关闭后停止全部轮询；
- Job Center 查询以 SQLite `mode=ro` 和 `query_only` 打开当前局点 `tasks.db`，不初始化 schema、不修复状态，也不返回任务结果中的完整业务 payload；
- Online MR 没有 Web 启停、强停、解析或报告 API；
- Online MR Web 仅读取当前局点的 Session metadata、Task/Mapping、`view/*.json` 和 raw 白名单；页面隐藏或关闭后停止轮询；
- AC 管理通过 GET-only `/api/ac-management` 和 SQLite `mode=ro + query_only` 展示现有 AC/FIT-AP、Radio 1/2、LLDP、光衰及配置快照；不连接设备、不采集、不下发命令，配置文件仅通过受控 snapshot ID 分块读取；
- AC Mesh-Link 页面通过 GET-only `/api/ac-management/mesh-links` 读取既有结构化快照，按 30 秒 fresh/5 分钟 stale 边界保守展示 MR 状态；不把 MR 当作客户端，不执行 `display wlan mesh-link ap`，旧采集没有 raw 时明确显示不可用；
- Agent 远程 MR start/stop、`executor=AGENT`、远端包删除和 Agent 配置修改仍未开放；
- Agent Web 当前生产认证仍是可选 `X-Agent-Token`。示例配置虽保留 `web_username/web_password` 字段，但尚未实现用户名密码登录流程，不能把 `admin/admin` 描述为已生效认证；
- SNMP Center 和无线勘测继续保持 `DISABLED`。
